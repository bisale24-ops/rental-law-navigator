"""Module A, step 2: merge the candidates that describe the same rule, and write rules.json.

    python3 -m navigator.consolidate        # data/candidates.json -> out/rules.json

Several documents often describe one rule (a statute and an agency FAQ). A model groups candidates per state;
code checks the grouping (every candidate in exactly one group, same jurisdiction and category inside a group),
keeps the official source as the record's citation, keeps the others as supporting sources, and raises a
conflict flag when sources disagree on the effective date or the headline number.
"""
import collections
import datetime as dt
import json
import pathlib
import re
import sys

from . import audit
from .engine import parse_date, status_on
from .llm import ask_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
AS_OF = dt.date(2026, 10, 1)

SYSTEM = """You consolidate rental-housing rules extracted from several documents into a rule database with ONE
record per (jurisdiction, category) for enacted law, plus one record per bill or failed measure.

Input: candidate rules of one state (the state and its cities), each with an index.
For every (jurisdiction, category) that has enacted candidates, output one cell:
- members: indices of all enacted candidates of that jurisdiction and category (sub-provisions such as return
  deadlines, exceptions, annual adjustment amounts and relocation amounts belong to the main rule as details).
- canonical: the candidate that states the headline rule (the cap, the ban, the just-cause requirement itself),
  preferring official sources and the most direct quote.
- coverage_from: the candidate whose coverage fields best describe which buildings are covered (often a coverage
  table or the statute itself); default to canonical.
- requirement: one or two plain-language sentences for a tenant or landlord, covering the headline rule and the
  most important detail. Only facts present in the members.
- key_value: the headline number or formula, or null.
- effect: imposes_requirement (a cap, ban, limit or duty), prohibits_local_rules (the law bars cities from regulating,
  e.g. a state ban on rent control), or exemption_only (the record only describes who is exempt).
- conflict / conflict_note: true when members disagree on the effective date or the headline number for the same
  period; name the doc ids and the two values. Different annual figures for different years are not a conflict.
For pending bills and failed measures output one cell per bill (members = candidates about that bill).
Every candidate index must appear in exactly one cell."""

SCHEMA = {"type": "object", "properties": {"cells": {"type": "array", "items": {"type": "object", "properties": {
    "jurisdiction": {"type": "string"},
    "category": {"type": "string"},
    "kind": {"type": "string", "enum": ["enacted", "bill_or_failed"]},
    "members": {"type": "array", "items": {"type": "integer"}},
    "canonical": {"type": "integer"},
    "coverage_from": {"type": "integer"},
    "requirement": {"type": "string"},
    "key_value": {"type": ["string", "null"]},
    "effect": {"type": "string", "enum": ["imposes_requirement", "prohibits_local_rules", "exemption_only"]},
    "conflict": {"type": "boolean"},
    "conflict_note": {"type": ["string", "null"]}},
    "required": ["jurisdiction", "category", "kind", "effect", "members", "canonical", "coverage_from", "requirement",
                 "key_value", "conflict", "conflict_note"]}}}, "required": ["cells"]}


def _brief(i, c):
    return {"i": i, "doc": c["source_doc_id"], "source_type": c["source_type"], "jurisdiction": c["jurisdiction"],
            "category": c["category"], "lifecycle": c["lifecycle"], "title": c["title"],
            "requirement": c["requirement"], "key_value": c["key_value"], "effective_date": c["effective_date"],
            "citation": c["citation"], "coverage": (c.get("coverage") or {}).get("summary"),
            "quote": c["quoted_span"][:300]}


def bill_key(c):
    """'Senate, No. 2983', 'Bill S.2983', 'S2983' -> 'S2983'; ballot petitions by their number."""
    t = f"{c.get('citation', '')} {c.get('title', '')}"
    m = re.search(r"\b(Senate|House|Assembly)\s*,?\s*No\.?\s*(\d+)", t, re.I)
    if m:
        return m.group(1)[0].upper() + m.group(2)
    m = re.search(r"\b(AB|SB|[HSA])\.?\s?(\d{2,5})\b", t)
    if m:
        return m.group(1).upper() + m.group(2)
    m = re.search(r"(\d{2}-\d{2})", t)
    return m.group(1) if m else (c.get("citation") or c.get("title"))


def group_state(state, cands, replay_only=False):
    """Cells for one state. Code enforces the shape the model was asked for: one enacted cell per
    (jurisdiction, category), every candidate placed once, canonical inside its cell."""
    briefs = [_brief(i, c) for i, c in enumerate(cands)]
    out, meta = ask_json(SYSTEM, json.dumps(briefs, indent=0), SCHEMA, tag=f"consolidate-{state}",
                         replay_only=replay_only)
    seen, cells = set(), []
    for g in out.get("cells", []):
        mem = [m for m in g["members"] if 0 <= m < len(cands) and m not in seen]
        by_key = collections.defaultdict(list)
        for m in mem:
            c = cands[m]
            enacted = c["lifecycle"] == "enacted"
            by_key[(c["jurisdiction"], c["category"], enacted, None if enacted else bill_key(c))].append(m)
        for part in by_key.values():
            canon = g["canonical"] if g["canonical"] in part else part[0]
            cov = g["coverage_from"] if g["coverage_from"] in part else canon
            cells.append(dict(g, members=part, canonical=canon, coverage_from=cov,
                              conflict=g["conflict"] and len(part) > 1,
                              conflict_note=g["conflict_note"] if len(part) > 1 else None,
                              merged=len(part) == len(mem)))
            seen.update(part)
    for i in range(len(cands)):
        if i not in seen:
            cells.append({"members": [i], "canonical": i, "coverage_from": i, "requirement": None,
                          "key_value": None, "conflict": False, "conflict_note": None, "merged": False})
    # one enacted record per (jurisdiction, category), one per bill: fold leftovers into the cell that has it
    final, home = [], {}
    for c in cells:
        cand = cands[c["canonical"]]
        key = (cand["jurisdiction"], cand["category"]) if cand["lifecycle"] == "enacted" else \
            (cand["jurisdiction"], cand["category"], bill_key(cand))
        if key and key in home:
            home[key]["members"] += c["members"]
            continue
        if key:
            home[key] = c
        final.append(c)
    audit.log("consolidate.state", state=state, model=meta["model"], cached=meta["cached"], candidates=len(cands),
              rules=len(final))
    return final


COV_FIELDS = ["built_on_or_before", "built_after", "built_basis", "rolling_age_years", "min_units",
              "single_family_excluded", "owner_dependent", "owner_condition", "owner_exemption_max_units",
              "subsidized_excluded"]


def merge_coverage(primary, members):
    """Coverage of a rule = the chosen source's fields, with gaps filled from the rule's other sources
    (official before secondary). A coverage table on one page and the cap on another describe one rule."""
    cov = dict(primary.get("coverage") or {})
    # a secondary page that surveys many cities (a law-firm alert) cannot set coverage limits: its numbers may
    # belong to another city. Limits come from official sources only, or from the chosen source itself.
    if not primary["source_type"].startswith("official"):
        cov = {k: (v if k in ("summary", "unresolvable") else None) for k, v in cov.items()}
    order = sorted([m for m in members if m["source_type"].startswith("official")],
                   key=lambda m: m is not primary)
    filled = []
    for f in COV_FIELDS:
        if f in ("built_on_or_before", "built_after") and (cov.get("built_on_or_before") or cov.get("built_after")):
            continue                     # one cutoff direction per rule; never combine two sources' cutoffs
        if f == "built_basis" and cov.get(f) not in (None, "not_stated"):
            continue
        if cov.get(f) in (None, "not_stated"):
            for m in order:
                v = (m.get("coverage") or {}).get(f)
                if v not in (None, "not_stated"):
                    cov[f] = v
                    filled.append(f"{f} from {m['source_doc_id']}")
                    break
    if cov.get("built_basis") in (None, "not_stated") and (cov.get("built_on_or_before") or cov.get("built_after")):
        cov["built_basis"] = "construction"
    cov["filled_from"] = filled
    return cov


def fold_statements(rules):
    """Coverage statements (navigator.coverage) fill the coverage fields a rule's own sources left empty, and
    each filled field keeps the verbatim sentence it came from."""
    path = ROOT / "data" / "coverage_statements.json"
    if not path.exists():
        return
    sts = json.loads(path.read_text())
    for r in rules:
        if r["lifecycle"] != "enacted":
            continue
        mine = [x for x in sts if x["jurisdiction"] == r["jurisdiction"] and x["category"] == r["category"]
                and x["source_type"].startswith("official")]
        mine.sort(key=lambda x: not x["source_type"].startswith("official"))
        cov = r["coverage"]
        used = []
        for f in COV_FIELDS:
            if f in ("owner_dependent", "owner_condition"):
                continue
            if f in ("built_on_or_before", "built_after") and (cov.get("built_on_or_before") or cov.get("built_after")):
                continue
            if f == "built_basis":
                continue
            if cov.get(f) in (None, "not_stated"):
                for x in mine:
                    if x.get(f) not in (None, "not_stated"):
                        cov[f] = x[f]
                        if f.startswith("built_") and x.get("built_basis") not in (None, "not_stated"):
                            cov["built_basis"] = x["built_basis"]
                        used.append({"field": f, "value": x[f], "doc": x["source_doc_id"], "quote": x["quoted_span"]})
                        break
        if used:
            cov.setdefault("filled_from", []).extend(f"{u['field']} from {u['doc']}" for u in used)
            r["coverage_evidence"] = used
            r["coverage_conditions"] = cov


def fold_stale_proposals(rules):
    """A city proposal next to an enacted rule of the same city and category is the history of that rule (San
    Diego's ordinance materials, Santa Ana's council item): it becomes a supporting source, not a second record.
    Failed measures that repeat one another (three pages on one struck ballot question) become one record."""
    out = []
    for r in rules:
        if r["lifecycle"] == "enacted":
            out.append(r)
            continue
        home = None
        if r["level"] == "city":
            home = next((x for x in rules if x["lifecycle"] == "enacted" and x["jurisdiction"] == r["jurisdiction"]
                         and x["category"] == r["category"]), None)
        if home is None:
            home = next((x for x in out if x["lifecycle"] == r["lifecycle"] == "failed" and
                         x["jurisdiction"] == r["jurisdiction"] and x["category"] == r["category"]), None)
        if home is None:
            out.append(r)
            continue
        home["supporting_sources"].append({"doc": r["source_doc_id"], "url": r["source_url"], "retrieved": r["retrieved"],
                                           "effective_date": r["effective_date"], "key_value": r["key_value"],
                                           "quoted_span": r["quoted_span"], "note": f"earlier {r['lifecycle']}: {r['title']}"})
        home["supporting_sources"] += r["supporting_sources"]
        audit.log("consolidate.fold", into=home["title"], folded=r["title"], doc=r["source_doc_id"])
    return out


def _official_first(cands, g):
    canon = cands[g["canonical"]]
    if canon["source_type"] != "official":
        off = [m for m in g["members"] if cands[m]["source_type"] == "official"]
        if off:
            return off[0]
    return g["canonical"]


def build(candidates, replay_only=False):
    by_state = collections.defaultdict(list)
    for c in candidates:
        by_state[c["jurisdiction"][-2:]].append(c)
    rules = []
    for state, cands in sorted(by_state.items()):
        for g in group_state(state, cands, replay_only):
            canon = cands[_official_first(cands, g)]
            covsrc = cands[g["coverage_from"]]
            members = [cands[m] for m in g["members"]]
            dates = sorted({m["effective_date"] for m in members if m["effective_date"]})
            conflict, note = g["conflict"], g["conflict_note"]
            eff = canon["effective_date"] or (dates[0] if dates else None)
            rec = {
                "jurisdiction": canon["jurisdiction"], "level": canon["level"], "category": canon["category"],
                "status": None, "title": canon["title"], "requirement": g.get("requirement") or canon["requirement"],
                "key_value": g.get("key_value") or canon["key_value"], "coverage_conditions": merge_coverage(covsrc, members),
                "exemptions": canon["exemptions"], "overrides": [], "interaction": None,
                "effective_date": eff if eff and _valid(eff) else None, "citation": canon["citation"],
                "source_doc_id": canon["source_doc_id"], "source_url": canon["source_url"],
                "quoted_span": canon["quoted_span"], "confidence": round(float(canon.get("confidence") or 0.7), 2),
                "conflict_flag": bool(conflict), "conflict_note": note if conflict else None,
                # beyond the schema: what the engine and the UI need
                "lifecycle": canon["lifecycle"], "coverage": merge_coverage(covsrc, members),
                "effect": g.get("effect") or "imposes_requirement",
                "yields_to_local": any(m["yields_to_local"] for m in members),
                "preempts_local": any(m["preempts_local"] for m in members),
                "retrieved": canon["retrieved"], "span_check": canon["span_check"],
                "supporting_sources": [{"doc": m["source_doc_id"], "url": m["source_url"], "retrieved": m["retrieved"],
                                        "effective_date": m["effective_date"], "key_value": m["key_value"],
                                        "quoted_span": m["quoted_span"]}
                                       for m in members if m is not canon],
            }
            if rec["confidence"] > 0.95 and conflict:
                rec["confidence"] = 0.7
            rules.append(rec)
    rules.sort(key=lambda r: (r["jurisdiction"][-2:], r["level"] != "state", r["jurisdiction"], r["category"],
                              r["lifecycle"] != "enacted", r["title"]))
    fold_statements(rules)
    rules = fold_stale_proposals(rules)
    for r in rules:
        r["source_conflict"] = r["conflict_flag"]      # sources disagree; preemption flags are per address
    for n, r in enumerate(rules, 1):
        r["team_rule_id"] = f"r-{n:04d}"
        st = status_on(r, AS_OF)
        r["status"] = st
    _interactions(rules)
    return rules


def _valid(s):
    try:
        parse_date(s)
        return True
    except (ValueError, TypeError):
        return False


def _interactions(rules):
    for r in rules:
        if r["level"] != "state" or r["lifecycle"] != "enacted":
            continue
        local = [x for x in rules if x["level"] == "city" and x["jurisdiction"].endswith(r["jurisdiction"])
                 and x["category"] == r["category"] and x["lifecycle"] == "enacted"]
        if r.get("yields_to_local") and local:
            r["overrides"] = [x["team_rule_id"] for x in local]
            r["interaction"] = ("Yields to stricter local law: where a listed local rule covers the unit, the local "
                                "rule governs and this one is reported as superseded.")
        if r.get("preempts_local") and local:
            r["overrides"] = [x["team_rule_id"] for x in local]
            r["interaction"] = ("May preempt the listed local rules once in force; every affected address is "
                                "flagged for human review rather than decided.")
            r["conflict_flag"] = True
            r["conflict_note"] = (r["conflict_note"] + " | " if r["conflict_note"] else "") + \
                "possible preemption of " + ", ".join(f"{x['team_rule_id']} ({x['jurisdiction']})" for x in local)
            for x in local:
                x["conflict_flag"] = True
                note = f"may be preempted by {r['team_rule_id']} ({r['title']}) from {r['effective_date']}"
                x["conflict_note"] = (x["conflict_note"] + " | " if x["conflict_note"] else "") + note


CATEGORIES = ["rent_increase_limits", "just_cause_eviction", "security_deposits", "application_screening_fees",
              "screening_restrictions", "algorithmic_rent_setting"]


def no_rule_findings(rules):
    """Every (jurisdiction, category) cell with no enacted rule is reported as a finding, not left silent: what
    was searched, what governs instead, and whether the gap may be a corpus gap (link-only sources)."""
    import csv
    man = list(csv.DictReader((ROOT / "starter" / "pack" / "corpus" / "corpus_manifest.csv").open()))
    juris = sorted({m["jurisdictions"] for m in man}, key=lambda j: (j[-2:], "," in j, j))
    out = []
    for j in juris:
        docs = [m for m in man if m["jurisdictions"] == j]
        with_text = [m["doc_id"] for m in docs if (ROOT / "starter/pack/corpus/text" / f"{m['doc_id']}.txt").exists()]
        link_only = [m["doc_id"] for m in docs if m["doc_id"] not in with_text]
        for c in CATEGORIES:
            here = [r for r in rules if r["jurisdiction"] == j and r["category"] == c]
            if any(r["lifecycle"] == "enacted" for r in here):
                continue
            state = j[-2:]
            st = [r for r in rules if r["jurisdiction"] == state and r["category"] == c and r["lifecycle"] == "enacted"]
            other = [r for r in here if r["lifecycle"] != "enacted"]
            note = f"No enacted {c.replace('_', ' ')} rule found for {j} in {len(with_text)} documents with text"
            if other:
                note += "; not law: " + ", ".join(f"{r['team_rule_id']} {r['title']} ({r['lifecycle']})" for r in other)
            if "," in j and st:
                note += f"; the state rule {st[0]['team_rule_id']} ({st[0]['title']}) governs"
            if link_only:
                note += f"; {len(link_only)} source(s) for {j} are link-only in the starter pack ({', '.join(link_only)}) " \
                        "and could hold a rule: human review"
            out.append({"jurisdiction": j, "category": c, "finding": "no_rule_in_corpus", "note": note,
                        "governing_rule_ids": [r["team_rule_id"] for r in st] if "," in j else [],
                        "documents_searched": with_text, "link_only_sources": link_only})
    return out


SCHEMA_KEYS = ["team_rule_id", "jurisdiction", "level", "category", "status", "title", "requirement", "key_value",
               "coverage_conditions", "exemptions", "overrides", "interaction", "effective_date", "citation",
               "source_doc_id", "source_url", "quoted_span", "confidence", "conflict_flag", "conflict_note"]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cands = json.loads((ROOT / "data" / "candidates.json").read_text())["kept"]
    rules = build(cands, replay_only="--replay" in argv)
    (ROOT / "data" / "rules_full.json").write_text(json.dumps(rules, indent=1))
    out = [dict({k: r[k] for k in SCHEMA_KEYS}, retrieved=r["retrieved"], lifecycle=r["lifecycle"],
                supporting_sources=[{k: s[k] for k in ("doc", "url", "retrieved", "effective_date")}
                                    for s in r["supporting_sources"]]) for r in rules]
    (ROOT / "out").mkdir(exist_ok=True)
    gaps = no_rule_findings(rules)
    (ROOT / "data" / "no_rule_findings.json").write_text(json.dumps(gaps, indent=1))
    (ROOT / "out" / "rules.json").write_text(json.dumps({"as_of": AS_OF.isoformat(), "rules": out,
                                                         "no_rule_findings": gaps}, indent=1))
    print(len(gaps), "no-rule findings")
    print(len(cands), "candidates ->", len(rules), "rules;",
          collections.Counter(r["status"] for r in rules), sum(r["conflict_flag"] for r in rules), "conflicts")


if __name__ == "__main__":
    main()
