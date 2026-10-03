"""Module C, new law arrives: add one document and see what changes.

    python3 -m navigator.ingest path/to/ordinance.pdf --jurisdiction "Cambridge, MA" --test T6 --title "..."

The document goes through the same pipeline as the corpus (extraction with quote checks, consolidation, lookups).
The change case is answered by comparing every address's answer with and without the rules this document
contributed, at the query date and at the new rule's effective date. Nothing about the new law is hand-coded.
"""
import argparse
import csv
import json
import pathlib
import shutil
import subprocess
import time

from . import audit, consolidate, extract

ROOT = pathlib.Path(__file__).resolve().parents[1]


def to_text(path):
    p = pathlib.Path(path)
    if p.suffix.lower() == ".pdf":
        return subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, check=True).stdout
    if p.suffix.lower() in (".html", ".htm"):
        import html
        import re
        s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", p.read_text(errors="replace"))
        return html.unescape(re.sub(r"<[^>]+>", " ", s))
    return p.read_text(errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--jurisdiction", required=True)
    ap.add_argument("--test", default="T6")
    ap.add_argument("--title", default="New ordinance")
    ap.add_argument("--url", default=None)
    ap.add_argument("--doc-id", default=None)
    a = ap.parse_args(argv)
    man = extract.manifest()
    doc_id = a.doc_id or f"N{sum(1 for d in man if d.startswith('N')) + 1:03d}"
    text = to_text(a.path)
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    url = a.url or f"supplied:{pathlib.Path(a.path).name}"
    out = ROOT / "data" / "supplement" / "text"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{doc_id}.txt").write_text(f"SOURCE: {url}\nRETRIEVED: {when}\nCAPTURE: supplied change case {a.test}\n\n{text}")
    shutil.copy(a.path, out.parent / f"{doc_id}{pathlib.Path(a.path).suffix}")
    new = not extract.EXTRA.exists()
    with extract.EXTRA.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["doc_id", "jurisdictions", "url", "source_type", "test_id", "title"])
        w.writerow([doc_id, a.jurisdiction, url, "official (supplied change case)", a.test, a.title])
    audit.log("ingest", doc=doc_id, test=a.test, jurisdiction=a.jurisdiction, chars=len(text), source=url)
    print(f"{doc_id}: {len(text)} chars from {a.path}")
    # same pipeline as the corpus
    kept, dropped = extract.extract_doc(extract.manifest()[doc_id], (out / f"{doc_id}.txt").read_text())
    cands = json.loads((ROOT / "data" / "candidates.json").read_text())
    cands["kept"] = [c for c in cands["kept"] if c["source_doc_id"] != doc_id] + kept
    cands["dropped"] = [c for c in cands["dropped"] if c["source_doc_id"] != doc_id] + dropped
    (ROOT / "data" / "candidates.json").write_text(json.dumps(cands, indent=1))
    print(f"extracted {len(kept)} rules ({len(dropped)} dropped by the quote check)")
    consolidate.main([])
    extra = ROOT / "data" / "change_tests_extra.json"
    tests = json.loads(extra.read_text()) if extra.exists() else []
    tests = [t for t in tests if t["test_id"] != a.test] + [{
        "test_id": a.test, "title": a.title, "type": "new_document", "doc_id": doc_id, "as_of": "2026-10-01",
        "expected_behavior": f"Addresses whose answer changes once {a.title} ({a.jurisdiction}) is added."}]
    extra.write_text(json.dumps(tests, indent=1))
    from . import run
    run.main([])


if __name__ == "__main__":
    main()
