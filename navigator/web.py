"""Rental Housing Law Navigator over HTTP. Standard library only; answers come from the same engine as the
submission files, so the page and lookups.json never disagree.

    python3 -m navigator.web          # http://127.0.0.1:8801
"""
import collections
import datetime as dt
import http.server
import json
import os
import pathlib
import sys
import urllib.parse

from . import audit, facts, spanish
from .engine import lookup, parse_date
from .run import AS_OF

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = pathlib.Path(__file__).with_name("page.html")
CATS = ["rent_increase_limits", "just_cause_eviction", "security_deposits", "application_screening_fees",
        "screening_restrictions", "algorithmic_rent_setting"]


class State:
    def __init__(self):
        self.reload()

    def reload(self):
        self.rules = json.loads((ROOT / "data" / "rules_full.json").read_text())
        self.by_id = {r["team_rule_id"]: r for r in self.rules}
        self.addrs = facts.load()
        self.changes = json.loads((ROOT / "out" / "changes.json").read_text()) if (ROOT / "out" / "changes.json").exists() else {}
        tests = json.loads((ROOT / "starter" / "pack" / "dev" / "change_tests.json").read_text())
        extra = ROOT / "data" / "change_tests_extra.json"
        self.tests = tests + (json.loads(extra.read_text()) if extra.exists() else [])
        self.cands = json.loads((ROOT / "data" / "candidates.json").read_text())
        self.es = spanish.load()
        self._cache = {}

    def lookups(self, as_of):
        if as_of not in self._cache:
            self._cache[as_of] = {aid: lookup(a, self.rules, as_of) for aid, a in self.addrs.items()}
        return self._cache[as_of]


S = State()


def rule_view(r):
    keep = ["team_rule_id", "jurisdiction", "level", "category", "status", "lifecycle", "title", "requirement",
            "key_value", "exemptions", "effective_date", "citation", "source_doc_id", "source_url", "retrieved",
            "quoted_span", "confidence", "conflict_flag", "conflict_note", "interaction", "overrides",
            "supporting_sources", "span_check", "coverage_evidence"]
    v = {k: r.get(k) for k in keep}
    v["coverage"] = (r.get("coverage") or {}).get("summary")
    return v


def meta():
    kept, dropped = S.cands["kept"], S.cands["dropped"]
    checks = collections.Counter("exact" if c["span_check"] == "exact" else "repaired" for c in kept)
    juris = sorted({r["jurisdiction"] for r in S.rules}, key=lambda j: (j[-2:], "," in j, j))
    matrix = {j: {c: [r["team_rule_id"] for r in S.rules if r["jurisdiction"] == j and r["category"] == c]
                  for c in CATS} for j in juris}
    docs = len({c["source_doc_id"] for c in kept + dropped})
    return {"as_of": AS_OF.isoformat(), "categories": CATS, "matrix": matrix,
            "rules": [rule_view(r) for r in S.rules],
            "pipeline": {"documents_read": docs, "candidates": len(kept) + len(dropped), "kept": len(kept),
                         "dropped": len(dropped), "exact": checks["exact"], "repaired": checks["repaired"],
                         "rules": len(S.rules), "conflicts": sum(r["conflict_flag"] for r in S.rules),
                         "status": collections.Counter(r["status"] for r in S.rules),
                         "models": collections.Counter(c.get("model") for c in kept)},
            "dropped": [{k: d.get(k) for k in ("source_doc_id", "title", "span_check", "quoted_span")} for d in dropped],
            "addresses": len(S.addrs),
            "addr_index": [{"id": a["address_id"], "city": a["city"] or "unresolved"} for a in S.addrs.values()],
            "cities": collections.Counter(a["city"] or "unresolved" for a in S.addrs.values())}


def address_list(q):
    q = (q or "").strip().lower()
    out = []
    for a in S.addrs.values():
        hay = f"{a['address_id']} {a['street']} {a['postal_city']} {a['city'] or ''} {a['zip']}".lower()
        if not q or all(t in hay for t in q.split()):
            out.append({k: a[k] for k in ("address_id", "street", "postal_city", "state", "city")})
    return out[:60]


def address_view(aid, as_of, lang="en"):
    a = S.addrs[aid]
    rows = S.lookups(as_of)[aid]
    if lang == "es":
        rv = lambda r: spanish.rule_es(rule_view(r), r, S.es)  # noqa: E731
        res = [dict(r, reasons=[spanish.reason(x) for x in r["reasons"]], rule=rv(S.by_id[r["team_rule_id"]]))
               for r in rows]
        addr = {k: v for k, v in a.items() if not k.startswith("_")}
        addr["jurisdiction_basis"] = spanish.reason(addr["jurisdiction_basis"])
        return {"as_of": as_of.isoformat(), "lang": "es", "address": addr, "results": res,
                "not_law": [rv(r) for r in S.rules if r["lifecycle"] in ("failed", "repealed")
                            and (r["jurisdiction"] == a["state"] or r["jurisdiction"] == a["city"])],
                "gaps": [c for c in CATS if not any(r["category"] == c for r in rows)]}
    return {"as_of": as_of.isoformat(), "address": {k: v for k, v in a.items() if not k.startswith("_")},
            "results": [dict(r, rule=rule_view(S.by_id[r["team_rule_id"]])) for r in rows],
            "not_law": [rule_view(r) for r in S.rules if r["lifecycle"] in ("failed", "repealed")
                        and (r["jurisdiction"] == a["state"] or r["jurisdiction"] == a["city"])],
            "gaps": [c for c in CATS if not any(r["category"] == c for r in rows)]}


def rule_map(rid, as_of):
    res = S.lookups(as_of)
    pts = []
    for aid, a in S.addrs.items():
        hit = next((r for r in res[aid] if r["team_rule_id"] == rid), None)
        pts.append({"id": aid, "lat": a["lat"], "lon": a["lon"], "city": a["city"], "street": a["street"],
                    "result": hit["result"] if hit else None, "conflict": bool(hit and hit["conflict_flag"])})
    return {"rule": rule_view(S.by_id[rid]), "as_of": as_of.isoformat(), "points": pts}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "navigator/0.1"

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            as_of = parse_date(q["as_of"]) if q.get("as_of") else AS_OF
        except (ValueError, TypeError):
            return self._send(400, {"error": "as_of must be YYYY-MM-DD"})
        if as_of < dt.date(2015, 1, 1) or as_of > dt.date(2035, 12, 31):
            return self._send(400, {"error": "as_of out of range"})
        if u.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/meta":
            return self._send(200, meta())
        if u.path == "/api/addresses":
            return self._send(200, address_list(q.get("q")))
        if u.path == "/api/lookup":
            if q.get("id") not in S.addrs:
                return self._send(404, {"error": "unknown address id"})
            audit.log("ui.lookup", address=q["id"], as_of=as_of.isoformat())
            return self._send(200, address_view(q["id"], as_of, q.get("lang", "en")))
        if u.path == "/api/map":
            if q.get("rule") not in S.by_id:
                return self._send(404, {"error": "unknown rule"})
            return self._send(200, rule_map(q["rule"], as_of))
        if u.path == "/api/changes":
            return self._send(200, {"tests": S.tests, "results": S.changes})
        if u.path == "/api/audit":
            p = audit.PATH
            lines = p.read_text().splitlines()[-int(q.get("n", 300)):] if p.exists() else []
            return self._send(200, [json.loads(x) for x in lines])
        if u.path == "/healthz":
            return self._send(200, {"ok": True, "rules": len(S.rules)})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8801"))
    srv = http.server.ThreadingHTTPServer((host, port), Handler)
    print(f"http://{host}:{port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
