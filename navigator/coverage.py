"""Module A, step 3: coverage statements. Which buildings a rule covers is often written on a different page than
the rule itself (San Francisco's rent-increase cap; its June 13, 1979 certificate-of-occupancy cutoff is stated on
the just-cause page). One model pass per document lists every coverage or exemption statement with the category
it governs and a verbatim quote; code verifies each quote and folds the statements into the matching rule.

    python3 -m navigator.coverage           # data/coverage_statements.json
"""
import concurrent.futures as cf
import json
import pathlib
import sys

from . import audit
from .extract import CATEGORIES, MODELS, load_text, locate, manifest, normalize_jurisdiction, prompt_for
from .llm import NoModel, ask_json

ROOT = pathlib.Path(__file__).resolve().parents[1]

SYSTEM = """From one housing-law document, list every statement about WHICH buildings or units a rule covers or
exempts: construction or certificate-of-occupancy cutoff dates, minimum unit counts, rolling building-age
exemptions, single-family/condo exemptions, owner-based exemptions, subsidized-housing exemptions.
For each statement give the category of the rule it governs (one of: """ + ", ".join(CATEGORIES) + """) and the
jurisdiction ("CA"/"NJ"/"MA" for state law, "City, ST" for city law). A sentence like "units first occupied after
June 13, 1979 are exempt from rent increase limits but still covered by just cause" gives two statements: the
rent_increase_limits rule covers units with certificate of occupancy on or before 1979-06-13, and the
just_cause_eviction rule has no such cutoff.
Fields: built_on_or_before / built_after (YYYY-MM-DD) with built_basis; min_units; rolling_age_years;
owner_exemption_max_units; subsidized_excluded; single_family_excluded. Leave a field null when the statement does
not give it. quoted_span: the exact sentence from the document. Return an empty list when there is none."""

SCHEMA = {"type": "object", "properties": {"statements": {"type": "array", "items": {"type": "object", "properties": {
    "jurisdiction": {"type": "string"}, "level": {"type": "string", "enum": ["state", "city"]},
    "category": {"type": "string", "enum": CATEGORIES},
    "built_on_or_before": {"type": ["string", "null"]}, "built_after": {"type": ["string", "null"]},
    "built_basis": {"type": "string", "enum": ["certificate_of_occupancy", "construction", "first_occupancy", "not_stated"]},
    "min_units": {"type": ["integer", "null"]}, "rolling_age_years": {"type": ["integer", "null"]},
    "owner_exemption_max_units": {"type": ["integer", "null"]}, "subsidized_excluded": {"type": ["boolean", "null"]},
    "single_family_excluded": {"type": ["boolean", "null"]}, "quoted_span": {"type": "string"}},
    "required": ["jurisdiction", "level", "category", "built_on_or_before", "built_after", "built_basis", "min_units",
                 "rolling_age_years", "owner_exemption_max_units", "subsidized_excluded", "single_family_excluded",
                 "quoted_span"]}}}, "required": ["statements"]}


def statements_for(doc, text, replay_only=False, models=None):
    out, meta = ask_json(SYSTEM, prompt_for(doc, text), SCHEMA, tag=f"coverage-{doc['doc_id']}",
                         replay_only=replay_only, models=models)
    kept = []
    for st in out.get("statements", []):
        exact, how = locate(st.get("quoted_span", ""), text)
        if not exact:
            continue
        st = normalize_jurisdiction(dict(st, citation="", title=""), doc)
        kept.append(dict(st, quoted_span=exact, span_check=how, source_doc_id=doc["doc_id"],
                         source_type=doc.get("source_type") or "official"))
    audit.log("coverage.doc", doc=doc["doc_id"], model=meta["model"], cached=meta["cached"],
              statements=len(out.get("statements", [])), kept=len(kept))
    return kept


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    replay = "--replay" in argv
    jobs = [(d, load_text(d)) for d in manifest()]
    jobs = [(manifest()[d], t) for d, t in jobs if t]

    def work(kj):
        k, (doc, text) = kj
        try:
            return statements_for(doc, text, replay, MODELS[k % 3:3] + MODELS[:k % 3] + MODELS[3:])
        except NoModel as e:
            print(doc["doc_id"], "NO MODEL", str(e)[:100], flush=True)
            return []
    allst = []
    with cf.ThreadPoolExecutor(3) as ex:
        for res in ex.map(work, enumerate(jobs)):
            allst += res
    (ROOT / "data" / "coverage_statements.json").write_text(json.dumps(allst, indent=1))
    print(len(allst), "coverage statements with verified quotes")


if __name__ == "__main__":
    main()
