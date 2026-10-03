"""Fill gaps the starter pack left as link-only, where the site's robots.txt allows it: one request per page,
saved with its URL, retrieval time and sha256 under data/supplement/text/. Pages whose robots.txt disallows us
(ecode360, amlegal, justia, ...) are not fetched; they stay listed as link-only for human review.

    python3 tools/capture_links.py
"""
import csv
import hashlib
import html
import json
import pathlib
import re
import time
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "supplement" / "text"
UA = "KHLab-RentalLawNavigator/0.1 (hackathon research; one request per page)"


def to_text(raw, ctype):
    if "pdf" in ctype:
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(raw)
            f.flush()
            return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    s = raw.decode("utf-8", errors="replace")
    s = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = []
    robots = {}
    for r in csv.DictReader((ROOT / "starter/pack/corpus/links_only.csv").open()):
        u = r["url"]
        b = urlparse(u)
        host = f"{b.scheme}://{b.netloc}"
        if host not in robots:
            rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001
                rp = None
            robots[host] = rp
        rp = robots[host]
        if rp is None or not rp.can_fetch(UA, u):
            log.append({"doc": r["doc_id"], "url": u, "fetched": False, "reason": "robots.txt disallows or unreadable"})
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=40) as resp:
                raw, ctype = resp.read(), resp.headers.get("content-type", "")
        except Exception as e:  # noqa: BLE001
            log.append({"doc": r["doc_id"], "url": u, "fetched": False, "reason": repr(e)[:160]})
            continue
        text = to_text(raw, ctype)
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        (OUT / f"{r['doc_id']}.txt").write_text(f"SOURCE: {u}\nRETRIEVED: {when}\nCAPTURE: team, robots.txt allowed\n\n{text}\n")
        log.append({"doc": r["doc_id"], "url": u, "fetched": True, "chars": len(text), "retrieved": when,
                    "sha256": hashlib.sha256(raw).hexdigest()})
        time.sleep(2)
    (ROOT / "data" / "supplement" / "capture_log.json").write_text(json.dumps(log, indent=1))
    for x in log:
        print(x["doc"], x["fetched"], x.get("chars") or x.get("reason"))


if __name__ == "__main__":
    main()
