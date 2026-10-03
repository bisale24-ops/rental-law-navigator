"""Module A, step 3: coverage statements. Which buildings a rule covers is often written on a different page than
the rule itself (San Francisco's rent-increase cap; its June 13, 1979 certificate-of-occupancy cutoff is stated on
the just-cause page). One model pass per document lists every coverage or exemption statement with the category
it governs and a verbatim quote; code verifies each quote and folds the statements into the matching rule.

    python3 -m navigator.coverage           # data/coverage_statements.json
"""
import concurrent.futures as cf
import json
import re
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


CUE = re.compile(r"(certificate of occupancy|first occupied|built|constructed|construction|\b\d+\s+(or more\s+)?(dwelling\s+)?units\b|"
                 r"exempt|does not apply|do not apply|not subject|covered|coverage|single[- ]family|condominium|"
                 r"owner[- ]occupied|subsidi[sz]ed|\b1[5-9]\b years|\b(19|20)\d\d\b)", re.I)


def sentences(text):
    flat = re.sub(r"\s+", " ", text)
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z(])", flat) if 40 <= len(x.strip()) <= 600]


JURIS_SYSTEM = SYSTEM + """
You receive numbered sentences, already filtered to ones that mention coverage, from official documents about ONE
jurisdiction and its state. Return a statement only when the sentence really limits which buildings a rule covers.
Assign each to the category it governs. A sentence saying units are still covered by eviction protections but
exempt from rent limits governs rent_increase_limits (with the cutoff) and not just_cause_eviction."""


PAST = re.compile(r"\b(until|prior to|before) (january|february|march|april|may|june|july|august|september|"
                  r"october|november|december|\d{4})|\bwere capped\b|\bwas capped\b|\bpreviously\b", re.I)
RANGE_EXEMPT = re.compile(r"\b(\d+)\s*-\s*(\d+)\s*unit[^.]{0,60}\bexempt", re.I)


def sanity(st):
    """Code checks on a coverage statement before it can narrow a rule: a sentence about the past ("until June
    19, 2014, increases were capped ...") does not describe current coverage, and "1-4 unit properties are
    exempt" means the rule covers 5 or more, whatever number the model wrote."""
    q = st.get("quoted_span", "")
    if PAST.search(q):
        return None
    m = RANGE_EXEMPT.search(q)
    if m:
        st = dict(st, min_units=int(m.group(2)) + 1)
    return st


def by_jurisdiction(replay_only=False):
    """Coverage statements per jurisdiction from pre-filtered official sentences: a smaller, focused task than
    reading whole documents, and every quote is still checked against its document."""
    man = manifest()
    groups = {}
    for d, doc in man.items():
        t = load_text(d)
        if not t or not (doc.get("source_type") or "official").startswith("official"):
            continue
        groups.setdefault(doc["jurisdictions"], []).append((doc, t))
    out = []
    for j, docs in sorted(groups.items()):
        items, src = [], []
        for doc, t in docs:
            for snt in sentences(t):
                if CUE.search(snt):
                    items.append(f"[{len(items)}] ({doc['doc_id']}) {snt}")
                    src.append((doc, t))
        if not items:
            continue
        res, meta = ask_json(JURIS_SYSTEM, f"Jurisdiction: {j}\n\n" + "\n".join(items[:400]), SCHEMA,
                             tag=f"coverage-j-{j}", replay_only=replay_only)
        kept = 0
        for st in res.get("statements", []):
            st = sanity(st)
            if st is None:
                continue
            for doc, t in docs:
                exact, how = locate(st.get("quoted_span", ""), t)
                if exact:
                    st = normalize_jurisdiction(dict(st, citation=exact, title=""), doc)
                    out.append(dict(st, quoted_span=exact, span_check=how, source_doc_id=doc["doc_id"],
                                    source_type=doc.get("source_type") or "official", pass_="jurisdiction"))
                    kept += 1
                    break
        audit.log("coverage.jurisdiction", jurisdiction=j, model=meta["model"], cached=meta["cached"],
                  sentences=len(items), statements=len(res.get("statements", [])), kept=kept)
        print(j, len(items), "sentences ->", kept, "statements", flush=True)
    return out


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
    if "--by-jurisdiction" in argv:
        allst = by_jurisdiction(replay)
        prev = ROOT / "data" / "coverage_statements.json"
        old = [x for x in json.loads(prev.read_text()) if x.get("pass_") != "jurisdiction"] if prev.exists() else []
        prev.write_text(json.dumps(allst + old, indent=1))       # focused statements first: they win the fill
        print(len(allst), "jurisdiction statements;", len(old), "document statements kept")
        return
    with cf.ThreadPoolExecutor(3) as ex:
        for res in ex.map(work, enumerate(jobs)):
            allst += res
    (ROOT / "data" / "coverage_statements.json").write_text(json.dumps(allst, indent=1))
    print(len(allst), "coverage statements with verified quotes")


if __name__ == "__main__":
    main()
