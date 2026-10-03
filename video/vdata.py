"""Numbers the videos say, read from the pipeline's own files at render time so cards never drift."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
C = json.loads((ROOT / "data" / "candidates.json").read_text())
RULES = json.loads((ROOT / "data" / "rules_full.json").read_text())
CH = json.loads((ROOT / "out" / "changes.json").read_text())
DOCS = len({c["source_doc_id"] for c in C["kept"] + C["dropped"]})
PROPOSED = len(C["kept"]) + len(C["dropped"])
EXACT = sum(c["span_check"] == "exact" for c in C["kept"])
REPAIRED = len(C["kept"]) - EXACT
DROPPED = len(C["dropped"])
NRULES = len(RULES)


def words(n):
    ones = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen").split()
    tens = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])
    return ones[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + words(n % 100))
