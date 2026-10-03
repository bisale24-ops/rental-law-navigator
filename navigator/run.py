"""Modules B and C end to end: rules.json + addresses -> lookups.json and changes.json.

    python3 -m navigator.run                    # as of 2026-10-01
    python3 -m navigator.run --as-of 2027-07-02

Change tests are answered by running the same engine at the dates each test names and comparing results, so a
new change case is data, not code: add it to the tests file and rerun.
"""
import datetime as dt
import json
import pathlib
import sys

from . import audit, facts
from .engine import lookup, parse_date

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "starter" / "pack"
AS_OF = dt.date(2026, 10, 1)


def load_rules():
    return json.loads((ROOT / "data" / "rules_full.json").read_text())


def all_lookups(rules, addrs, as_of):
    return {aid: lookup(a, rules, as_of) for aid, a in sorted(addrs.items())}


def submission_lookups(results, as_of):
    return {"as_of": as_of.isoformat(), "lookups": {
        aid: [{"team_rule_id": r["team_rule_id"], "result": r["result"], "explanation": r["explanation"],
               "conflict_flag": r["conflict_flag"]} for r in rows] for aid, rows in results.items()}}


# ---------------------------------------------------------------- Module C

def match_rules(rules, test):
    """Map an organizer test's rule ids (CA-ALG-01, HOB-ALG-01 ...) to our extracted rules by what they are:
    jurisdiction, category and lifecycle. The mapping is printed in notes so a reviewer can check it."""
    want = []
    for rid in test["rule_ids"]:
        prefix, cat = rid.split("-")[0], rid.split("-")[1]
        juris = {"CA": "CA", "NJ": "NJ", "MA": "MA", "HOB": "Hoboken, NJ", "JC": "Jersey City, NJ"}.get(prefix, prefix)
        category = {"ALG": "algorithmic_rent_setting", "RENT": "rent_increase_limits"}[cat]
        pending = rid.split("-")[2].startswith("P")
        hits = [r for r in rules if r["jurisdiction"] == juris and r["category"] == category
                and ((r["lifecycle"] != "enacted") == pending)]
        want.append((rid, hits))
    return want


def _ids_with(results, rule_ids, results_ok):
    return sorted(aid for aid, rows in results.items()
                  if any(r["team_rule_id"] in rule_ids and r["result"] in results_ok for r in rows))


def change_tests(rules, addrs, tests):
    out = {}
    cache = {}

    def at(d):
        if d not in cache:
            cache[d] = all_lookups(rules, addrs, d)
        return cache[d]

    for t in tests:
        mapping = match_rules(rules, t)
        ids = {r["team_rule_id"] for _, hits in mapping for r in hits}
        mapped = "; ".join(f"{rid} -> {', '.join(h['team_rule_id'] for h in hits) or 'no extracted rule'}"
                           for rid, hits in mapping)
        kind = t["type"]
        if kind == "as_of":
            before, after = at(parse_date(t["as_of_before"])), at(parse_date(t["as_of_after"]))
            was = _ids_with(before, ids, {"not_yet_effective"})
            now = _ids_with(after, ids, {"applies", "unknown", "superseded"})
            affected = sorted(set(now) - set(_ids_with(before, ids, {"applies", "unknown", "superseded"})))
            conflict = sorted(aid for aid, rows in after.items()
                              if any(r["team_rule_id"] in ids and r["conflict_flag"] for r in rows))
            # a possible conflict is reported from enactment on, not only once it bites
            conflict = sorted(set(conflict) | {aid for aid, rows in before.items()
                                                if any(r["team_rule_id"] in ids and r["conflict_flag"] for r in rows)})
            notes = (f"{mapped}. As of {t['as_of_before']}: not_yet_effective at {len(was)} addresses. As of "
                     f"{t['as_of_after']}: in force at {len(now)} addresses; {len(affected)} change.")
            out[t["test_id"]] = {"affected_address_ids": affected, "conflict_flag_address_ids": conflict,
                                 "notes": notes}
        elif kind == "boundary":
            now = at(parse_date(t["as_of"]))
            per = {rid: _ids_with(now, {h["team_rule_id"] for h in hits}, {"applies", "unknown", "superseded"})
                   for rid, hits in mapping}
            affected = sorted({a for v in per.values() for a in v})
            wrong = [aid for rid, v in per.items() for aid in v
                     if addrs[aid]["city"] != {"HOB": "Hoboken, NJ", "JC": "Jersey City, NJ"}.get(rid.split("-")[0])]
            notes = (f"{mapped}. " + "; ".join(f"{rid}: {len(v)} addresses" for rid, v in per.items()) +
                     f". Addresses outside the ordinance's city: {len(wrong)}.")
            out[t["test_id"]] = {"affected_address_ids": affected, "conflict_flag_address_ids": [], "notes": notes}
        elif kind == "pending":
            now = at(parse_date(t["as_of"]))
            pend = _ids_with(now, ids, {"pending"})
            out[t["test_id"]] = {"affected_address_ids": pend, "conflict_flag_address_ids": [],
                                 "notes": f"{mapped}. Pending, not law, on {t['as_of']}: reported as 'pending' at "
                                          f"{len(pend)} addresses, which are the addresses affected if enacted."}
        elif kind == "negative":
            now = at(parse_date(t["as_of"]))
            st = [s for s in t.get("states", [])]
            by_id = {r["team_rule_id"]: r for r in rules}
            caps = sorted(aid for aid, rows in now.items() if addrs[aid]["state"] in st and any(
                r["category"] == "rent_increase_limits" and r["result"] in ("applies", "unknown", "superseded")
                and by_id[r["team_rule_id"]].get("effect", "imposes_requirement") == "imposes_requirement"
                for r in rows))
            failed = [h for _, hits in mapping for h in hits]
            out[t["test_id"]] = {"affected_address_ids": caps, "conflict_flag_address_ids": [],
                                 "notes": f"{mapped}. Recorded as failed: " +
                                          ", ".join(f"{h['team_rule_id']} {h['title']} ({h['status']})" for h in failed) +
                                          f". Rent caps reported in {', '.join(st)}: {len(caps)}."}
        elif kind == "new_document":
            # with vs without every rule this document contributed, at the query date and at each new rule's
            # effective date; an address is affected when any answer differs
            from_doc = [r for r in rules if r["source_doc_id"] == t["doc_id"] or
                        any(s["doc"] == t["doc_id"] for s in r.get("supporting_sources", []))]
            ids = {r["team_rule_id"] for r in from_doc}
            without = [r for r in rules if r["team_rule_id"] not in ids]
            dates = sorted({parse_date(t["as_of"])} | {parse_date(r["effective_date"]) + dt.timedelta(days=1)
                                                       for r in from_doc if r.get("effective_date")})
            affected, flagged = set(), set()
            for d in dates:
                a_with, a_without = all_lookups(rules, addrs, d), all_lookups(without, addrs, d)
                for aid in addrs:
                    key = lambda rows: sorted((x["team_rule_id"], x["result"], x["conflict_flag"]) for x in rows)  # noqa: E731
                    if key(a_with[aid]) != key(a_without[aid]):
                        affected.add(aid)
                    if any(x["team_rule_id"] in ids and x["conflict_flag"] for x in a_with[aid]):
                        flagged.add(aid)
            out[t["test_id"]] = {"affected_address_ids": sorted(affected), "conflict_flag_address_ids": sorted(flagged),
                                 "notes": f"{t['doc_id']} contributed " + ", ".join(
                                     f"{r['team_rule_id']} {r['title']} ({r['status']}, effective {r['effective_date']})"
                                     for r in from_doc) + f". Compared at {', '.join(d.isoformat() for d in dates)}: "
                                     f"{len(affected)} addresses change, {len(flagged)} flagged."}
        audit.log("change_test", test=t["test_id"], affected=len(out[t["test_id"]]["affected_address_ids"]),
                  conflicts=len(out[t["test_id"]]["conflict_flag_address_ids"]), mapping=mapped)
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    as_of = parse_date(argv[argv.index("--as-of") + 1]) if "--as-of" in argv else AS_OF
    rules = load_rules()
    addrs = facts.load()
    res = all_lookups(rules, addrs, as_of)
    audit.log("lookups", as_of=as_of.isoformat(), addresses=len(res), rows=sum(len(v) for v in res.values()))
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "lookups.json").write_text(json.dumps(submission_lookups(res, as_of), indent=1))
    tests = json.loads((PACK / "dev" / "change_tests.json").read_text())
    extra = ROOT / "data" / "change_tests_extra.json"
    if extra.exists():
        tests += json.loads(extra.read_text())
    ch = change_tests(rules, addrs, tests)
    (out / "changes.json").write_text(json.dumps(ch, indent=1))
    from collections import Counter
    print("lookups:", len(res), "addresses,", Counter(r["result"] for v in res.values() for r in v))
    for k, v in ch.items():
        print(k, len(v["affected_address_ids"]), "affected,", len(v["conflict_flag_address_ids"]), "flagged |",
              v["notes"][:160])


if __name__ == "__main__":
    main()
