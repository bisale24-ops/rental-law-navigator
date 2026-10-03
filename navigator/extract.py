"""Module A: read every document in the corpus and turn the rules it states into structured records.

    python3 -m navigator.extract            # data/candidates.json + audit lines in out/audit.jsonl

One model call per document returns candidate rules in a strict JSON schema. Code then has the last word:
a candidate whose quoted_span is not found in the document text (after whitespace and quote normalization)
is repaired to the exact source sentence when a near-identical one exists, and dropped otherwise. Nothing the
model writes reaches rules.json without a verbatim source span.
"""
import concurrent.futures as cf
import csv
import difflib
import json
import pathlib
import re
import sys

from . import audit
from .llm import MODELS, NoModel, ask_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "starter" / "pack"
CATEGORIES = ["rent_increase_limits", "just_cause_eviction", "security_deposits", "application_screening_fees",
              "screening_restrictions", "algorithmic_rent_setting"]

SYSTEM_V1 = """You extract housing-law rules from one source document for a rental-housing law database.

Categories (use exactly these):
- rent_increase_limits: caps or formulas limiting rent increases (rent control / stabilization, annual allowable increase).
- just_cause_eviction: limits on the reasons a landlord may terminate a tenancy, and required relocation payments tied to no-fault evictions.
- security_deposits: maximum deposit amounts, interest on deposits, return deadlines.
- application_screening_fees: limits on application or tenant-screening fees.
- screening_restrictions: limits on how applicants may be screened (criminal history / fair chance, source of income, credit, eviction records).
- algorithmic_rent_setting: bans or limits on algorithmic devices / software that set or recommend rents or occupancy.

Rules:
- Extract every distinct rule in these categories that the document itself states for a jurisdiction. One record per
  rule; split a document that states several rules. Skip rules outside the six categories.
- Also extract proposals that are not law (bills, ballot questions) with lifecycle "pending_bill", and measures that
  were struck down, vetoed or failed with lifecycle "failed". These matter: users must see they are NOT in force.
- quoted_span: copy one to three consecutive sentences EXACTLY as they appear in the document (same words, same
  numbers). It must be the operative text that states the requirement itself (the prohibition, the cap, the number,
  the coverage), never a short title, a findings clause or a heading. Never paraphrase inside quoted_span.
- citation: the official cite as the document gives it (code section, ordinance number, bill number). If the document
  gives none, use the most specific official name it gives (e.g. "Berkeley Municipal Code ch. 13.63"). Never invent
  section numbers that are not in the document.
- effective_date: the date the rule takes or took effect if the document states one (YYYY-MM-DD, or YYYY-MM / YYYY
  when only that is given); null when not stated. enacted_date likewise.
- coverage: fill only what the document says. built_on_or_before / built_after are the construction or certificate-of-
  occupancy cutoffs (say which in built_basis). rolling_age_years is for "buildings more than N years old" rules.
  min_units: smallest building size covered (e.g. 2 for "two or more units"). owner_dependent: true when coverage
  depends on who owns the property (corporate owner, small landlord, owner-occupied); owner_exemption_max_units: when
  an owner-based exemption can only apply to buildings or holdings of at most N units (e.g. small landlords owning
  no more than 4 units, owner-occupied duplexes = 2), give N. subsidized_excluded: true when government-subsidized
  or income-restricted units are exempt. unresolvable: other coverage
  conditions that need facts an address record cannot have (tenancy start date, subsidy, condo status).
- yields_to_local / preempts_local: true when the document says the rule does not apply where a stricter local rule
  applies, or that it overrides local rules.
- Use plain language in requirement (one or two sentences a tenant or landlord understands).
- jurisdiction: a state code ("CA", "NJ", "MA") for state law, or "City, ST" for city law.
- If the document states no rule in these categories, return an empty list."""

SYSTEM = """You extract housing-law rules from one source document for a rental-housing law database.

Categories (use exactly these):
- rent_increase_limits: caps or formulas limiting rent increases (rent control / stabilization, annual allowable increase).
- just_cause_eviction: limits on the reasons a landlord may terminate a tenancy, and required relocation payments tied to no-fault evictions.
- security_deposits: maximum deposit amounts, interest on deposits, return deadlines.
- application_screening_fees: limits on application or tenant-screening fees.
- screening_restrictions: limits on how applicants may be screened (criminal history / fair chance, source of income, credit, eviction records).
- algorithmic_rent_setting: bans or limits on algorithmic devices / software that set or recommend rents or occupancy.

Rules:
- Extract every distinct rule in these categories that the document itself states for a jurisdiction. One record per
  rule; split a document that states several rules. Skip rules outside the six categories.
- Also extract proposals that are not law (bills, ballot questions) with lifecycle "pending_bill", and measures that
  were struck down, vetoed or failed with lifecycle "failed". These matter: users must see they are NOT in force.
- quoted_span: copy one to three consecutive sentences EXACTLY as they appear in the document (same words, same
  numbers). It must be the operative text that states the requirement itself (the prohibition, the cap, the number,
  the coverage), never a short title, a findings clause or a heading. Never paraphrase inside quoted_span.
- citation: the official cite as the document gives it (code section, ordinance number, bill number). If the document
  gives none, use the most specific official name it gives (e.g. "Berkeley Municipal Code ch. 13.63"). Never invent
  section numbers that are not in the document.
- effective_date: the date the rule takes or took effect if the document states one (YYYY-MM-DD, or YYYY-MM / YYYY
  when only that is given); null when not stated. enacted_date likewise.
- coverage: fill only what the document says. built_on_or_before / built_after are the construction or certificate-of-
  occupancy cutoffs (say which in built_basis). rolling_age_years is for "buildings more than N years old" rules.
  min_units: smallest building size covered (e.g. 2 for "two or more units"). owner_dependent: true when coverage
  depends on who owns the property (corporate owner, small landlord, owner-occupied); owner_exemption_max_units: when
  an owner-based exemption can only apply to buildings or holdings of at most N units (e.g. small landlords owning
  no more than 4 units, owner-occupied duplexes = 2), give N. subsidized_excluded: true when government-subsidized
  or income-restricted units are exempt. unresolvable: other coverage
  conditions that need facts an address record cannot have (tenancy start date, subsidy, condo status).
- yields_to_local / preempts_local: true when the document says the rule does not apply where a stricter local rule
  applies, or that it overrides local rules.
- Use plain language in requirement (one or two sentences a tenant or landlord understands).
- jurisdiction: a state code ("CA", "NJ", "MA") for state law, or "City, ST" for city law.
- A bill or ballot page counts even when it only gives the bill's title and status: record it as pending_bill (or
  failed), with the title line as quoted_span and what the bill would do as requirement.
- Anti-discrimination statutes that protect applicants by source of income, housing subsidy, criminal record or
  credit are screening_restrictions rules: extract them.
- Statutes that forbid or allow local rent control are rent_increase_limits rules for the state.
- If the document states no rule in these categories, return an empty list."""

COVERAGE = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "built_on_or_before": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
    "built_after": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
    "built_basis": {"type": "string", "enum": ["certificate_of_occupancy", "construction", "first_occupancy", "not_stated"]},
    "rolling_age_years": {"type": ["integer", "null"]},
    "min_units": {"type": ["integer", "null"]},
    "single_family_excluded": {"type": ["boolean", "null"]},
    "owner_dependent": {"type": ["boolean", "null"]},
    "owner_condition": {"type": ["string", "null"]},
    "owner_exemption_max_units": {"type": ["integer", "null"]},
    "subsidized_excluded": {"type": ["boolean", "null"]},
    "unresolvable": {"type": ["string", "null"]}},
    "required": ["summary", "built_on_or_before", "built_after", "built_basis", "rolling_age_years", "min_units",
                 "single_family_excluded", "owner_dependent", "owner_condition", "owner_exemption_max_units",
                 "subsidized_excluded", "unresolvable"]}

SCHEMA = {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "object", "properties": {
    "jurisdiction": {"type": "string"},
    "level": {"type": "string", "enum": ["state", "city"]},
    "category": {"type": "string", "enum": CATEGORIES},
    "lifecycle": {"type": "string", "enum": ["enacted", "pending_bill", "failed", "repealed"]},
    "title": {"type": "string"},
    "requirement": {"type": "string"},
    "key_value": {"type": ["string", "null"]},
    "coverage": COVERAGE,
    "exemptions": {"type": ["string", "null"]},
    "effective_date": {"type": ["string", "null"]},
    "enacted_date": {"type": ["string", "null"]},
    "citation": {"type": "string"},
    "quoted_span": {"type": "string"},
    "yields_to_local": {"type": "boolean"},
    "preempts_local": {"type": "boolean"},
    "confidence": {"type": "number"}},
    "required": ["jurisdiction", "level", "category", "lifecycle", "title", "requirement", "key_value", "coverage",
                 "exemptions", "effective_date", "enacted_date", "citation", "quoted_span", "yields_to_local",
                 "preempts_local", "confidence"]}}},
    "required": ["rules"]}


EXTRA = ROOT / "data" / "extra_manifest.csv"


def manifest():
    """The organizers' manifest plus documents added later with `python3 -m navigator.ingest`."""
    rows = {r["doc_id"]: r for r in csv.DictReader((PACK / "corpus" / "corpus_manifest.csv").open())}
    official = ROOT / "data" / "supplement" / "official_sources.csv"
    if official.exists():
        rows.update({r["doc_id"]: r for r in csv.DictReader(official.open())})
    if EXTRA.exists():
        rows.update({r["doc_id"]: r for r in csv.DictReader(EXTRA.open())})
    return rows


def load_text(doc_id):
    """Starter-pack text first; otherwise a team capture of a link-only page (tools/capture_links.py, only
    where robots.txt allows)."""
    for p in (PACK / "corpus" / "text" / f"{doc_id}.txt", ROOT / "data" / "supplement" / "text" / f"{doc_id}.txt"):
        if p.exists():
            return p.read_text()
    return None


def captured(doc_id):
    return not (PACK / "corpus" / "text" / f"{doc_id}.txt").exists()


def header(text):
    m = re.search(r"^RETRIEVED:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        " ": " ", "§": "§"})


def _norm(s):
    return re.sub(r"\s+", " ", s.translate(_TRANS)).strip().lower()


def locate(span, text):
    """Find span in text. Returns (exact source substring, method) or (None, reason).

    exact: the span appears verbatim after normalizing whitespace and typographic quotes; the returned string is
    cut from the source itself. repaired: the closest source window of the same length is at least 92% similar
    (the model dropped a word or changed a quote mark); the source's own words replace the model's."""
    if not span or len(span) < 20:
        return None, "span too short"
    # map normalized positions back to the original text
    norm_chars, index = [], []
    prev_space = True
    for i, ch in enumerate(text.translate(_TRANS)):
        if ch.isspace():
            if prev_space:
                continue
            norm_chars.append(" ")
            prev_space = True
        else:
            norm_chars.append(ch.lower())
            prev_space = False
        index.append(i)
    hay = "".join(norm_chars)
    needle = _norm(span)
    at = hay.find(needle)
    if at >= 0:
        a, b = index[at], index[at + len(needle) - 1] + 1
        return text[a:b], "exact"
    # fuzzy: slide over sentence-ish windows around the best matching block
    sm = difflib.SequenceMatcher(None, hay, needle, autojunk=False)
    blk = sm.find_longest_match(0, len(hay), 0, len(needle))
    if blk.size < 12:
        return None, "not in document"
    start = max(0, blk.a - blk.b)
    best, best_r = None, 0.0
    for d in range(-40, 41, 2):
        s = max(0, start + d)
        for extra in (-10, 0, 10):
            e = min(len(hay), s + len(needle) + extra)
            r = difflib.SequenceMatcher(None, hay[s:e], needle, autojunk=False).ratio()
            if r > best_r:
                best, best_r = (s, e), r
    if best and best_r >= 0.92:
        s, e = best
        return text[index[s]:index[e - 1] + 1].strip(), f"repaired ({best_r:.2f})"
    return None, f"not in document (best {best_r:.2f})"


STATE_CITE = re.compile(r"civil code|civ\.? code|gov(ernment)?\.? code|business and professions|\bA\.?B\.?[ -]?\d|"
                        r"\bS\.?B\.?[ -]?\d|n\.?j\.?s\.?a|\bp\.?l\.? ?\d{4}|general laws|m\.?g\.?l|chapter \d+[a-z]?,? "
                        r"section|c\.\s?\d+:|tenant protection act|fair employment and housing", re.I)
CITY_CITE = re.compile(r"municipal code|ordinance|\bbmc\b|\blamc\b|\bsdmc\b|rent board|council file|city code|"
                       r"administrative code", re.I)


def normalize_jurisdiction(r, doc):
    """Code decides the jurisdiction from facts the model also reports: a rule cited to a state code or bill is
    state law even when a city's page describes it (an LA page explaining AB 1482); a city rule must belong to a
    city the document is about. Every change is recorded on the record."""
    r = dict(r)
    doc_j = doc["jurisdictions"]
    state = doc_j[-2:]
    cite = f"{r.get('citation', '')} {r.get('title', '')}"
    want = r.get("jurisdiction", "")
    if STATE_CITE.search(cite) and not CITY_CITE.search(cite):
        fixed, level = state, "state"
    elif r.get("level") == "city" or CITY_CITE.search(cite):
        fixed, level = (doc_j if "," in doc_j else want), "city"
        if "," not in fixed or fixed[-2:] != state:
            fixed, level = doc_j, ("city" if "," in doc_j else "state")
    else:
        fixed, level = (want if want in (doc_j, state) else doc_j), r.get("level", "state")
        level = "city" if "," in fixed else "state"
    if (fixed, level) != (want, r.get("level")):
        r["jurisdiction_fix"] = f"{want}/{r.get('level')} -> {fixed}/{level}"
    r["jurisdiction"], r["level"] = fixed, level
    return r


def prompt_for(doc, text):
    return (f"doc_id: {doc['doc_id']}\nDocument jurisdiction(s): {doc['jurisdictions']}\nSource URL: {doc['url']}\n"
            f"Source type: {doc.get('source_type') or 'official'}\nQuery date for context: 2026-10-01\n\n"
            f"----- DOCUMENT TEXT -----\n{text}\n----- END -----")


PASSES = [("p1", lambda: SYSTEM_V1), ("p2", lambda: SYSTEM)]


def extract_doc(doc, text, replay_only=False, models=None):
    """Two passes with different instructions; their union goes to consolidation, which merges duplicates.
    A second reading with recall-oriented instructions catches bills and anti-discrimination rules the first
    pass skipped."""
    found, metas = [], []
    for name, system in PASSES:
        out, meta = ask_json(system(), prompt_for(doc, text), SCHEMA, tag=f"extract-{doc['doc_id']}",
                             replay_only=replay_only, models=models)
        found += [dict(r, _pass=name) for r in out.get("rules", [])]
        metas.append(meta)
    meta = {"model": "+".join(m["model"] for m in metas), "cached": all(m["cached"] for m in metas)}
    kept, dropped = [], []
    found = [normalize_jurisdiction(r, doc) for r in found]
    for i, r in enumerate(found):
        exact, how = locate(r.get("quoted_span", ""), text)
        stype = doc.get("source_type") or "official"
        rec = dict(r, source_doc_id=doc["doc_id"], source_url=doc["url"], retrieved=header(text),
                   source_type=stype + (" (team capture)" if captured(doc["doc_id"]) else ""),
                   span_check=how, model=meta["model"])
        if exact:
            rec["quoted_span"] = exact
            kept.append(rec)
        else:
            dropped.append(rec)
        audit.log("extract.candidate", doc=doc["doc_id"], i=i, category=r.get("category"),
                  jurisdiction=r.get("jurisdiction"), title=r.get("title"), span_check=how, kept=bool(exact))
    audit.log("extract.doc", doc=doc["doc_id"], model=meta["model"], cached=meta["cached"], kept=len(kept),
              dropped=len(dropped))
    return kept, dropped


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    replay = "--replay" in argv
    only = [a for a in argv if re.match(r"^[DSN]\d{3}$", a)]
    docs = manifest()
    kept_all, dropped_all, missing = [], [], []
    jobs = []
    for doc_id, doc in docs.items():
        if only and doc_id not in only:
            continue
        text = load_text(doc_id)
        if text is None:
            audit.log("extract.skip", doc=doc_id, reason="no text in the starter pack (link-only source)",
                      url=doc["url"])
            continue
        jobs.append((doc_id, doc, text))

    def work(k_job):
        k, (doc_id, doc, text) = k_job
        order = MODELS[k % 3:3] + MODELS[:k % 3] + MODELS[3:]     # spread documents over the flash models
        try:
            return doc_id, extract_doc(doc, text, replay_only=replay, models=order), None
        except NoModel as e:
            return doc_id, None, e

    with cf.ThreadPoolExecutor(3) as ex:
        for doc_id, res, err in ex.map(work, enumerate(jobs)):
            if err:
                missing.append(doc_id)
                audit.log("extract.error", doc=doc_id, error=str(err)[:300])
                print(doc_id, "NO MODEL", str(err)[:120], flush=True)
                continue
            kept, dropped = res
            kept_all += kept
            dropped_all += dropped
            print(f"{doc_id}: {len(kept)} kept, {len(dropped)} dropped", flush=True)
    out = ROOT / "data" / ("candidates.json" if not only else "candidates-partial.json")
    out.write_text(json.dumps({"kept": kept_all, "dropped": dropped_all, "missing": missing}, indent=1))
    print(f"{len(kept_all)} candidates kept, {len(dropped_all)} dropped, {len(missing)} docs without a model answer")


if __name__ == "__main__":
    main()
