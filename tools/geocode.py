"""Module B, step 1: resolve each sample address to its legal jurisdiction with the US Census Geocoder.

    python3 tools/geocode.py          # writes data/geocode.json (cached; reruns only fill gaps)

postal_city is the mailing city, not the legal one (Van Nuys is in the City of Los Angeles, Dorchester is in
Boston), so the jurisdiction comes from the Census "Incorporated Places" layer at the matched point. Addresses
the geocoder cannot match keep place=None and are answered "unknown" for city rules downstream.
"""
import concurrent.futures as cf
import csv
import json
import re
import pathlib
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "starter/pack/data/sample_addresses.csv"
OUT = ROOT / "data/geocode.json"
URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?"


def normalize(street):
    """Assessor spellings the geocoder misses: '05TH AV' -> '5TH AVE', 'S 17TH' -> 'S 17TH ST'."""
    s = re.sub(r"\b0+(\d+(ST|ND|RD|TH))\b", r"\1", street)
    s = re.sub(r"\bAV$", "AVE", s)
    s = re.sub(r"^(\d+)-[\d.]+ ", r"\1 ", s)              # '521-523 S 17TH' -> '521 S 17TH'
    s = re.sub(r"\s+LOT\s+\S+$", "", s)
    if re.search(r"\d+(ST|ND|RD|TH)$", s):
        s += " ST"
    return s


def wrong_number(row, res):
    """The geocoder sometimes matches a different house ('322-322.5 Western Ave' -> '5 WESTERN AVE', in
    another city). A match whose house number differs from the input's is not trusted."""
    want = re.match(r"\d+", row["street_address"])
    got = re.match(r"\d+", res.get("matched_address") or "")
    return bool(want and got and want.group() != got.group())


def lookup(row, retry=False):
    street = normalize(row["street_address"]) if retry else row["street_address"]
    zip_ = "" if retry else row["zip"]                     # a few assessor zips belong to other towns
    q = f"{street}, {row['postal_city']}, {row['state']} {zip_}".strip()
    params = {"address": q, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
              "layers": "Incorporated Places,Census Designated Places,Counties", "format": "json"}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(URL + urllib.parse.urlencode(params), timeout=40) as r:
                matches = json.load(r)["result"]["addressMatches"]
            break
        except Exception as e:  # noqa: BLE001 - network hiccups are retried, then recorded
            err = repr(e)
            time.sleep(2 * (attempt + 1))
    else:
        return {"query": q, "status": "error", "error": err[:200]}
    if not matches:
        return {"query": q, "status": "no_match", "place": None}
    m = matches[0]
    g = m["geographies"]
    places = g.get("Incorporated Places") or []
    return {"query": q, "status": "matched", "matched_address": m["matchedAddress"],
            "lon": m["coordinates"]["x"], "lat": m["coordinates"]["y"],
            "place": places[0]["NAME"] if places else None,
            "place_geoid": places[0]["GEOID"] if places else None,
            "cdp": [p["NAME"] for p in g.get("Census Designated Places") or []],
            "county": [c["NAME"] for c in g.get("Counties") or []],
            "candidates": len(matches)}


def main():
    rows = list(csv.DictReader(SRC.open()))
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [r for r in rows if done.get(r["address_id"], {}).get("status") not in ("matched", "no_match")]
    with cf.ThreadPoolExecutor(8) as ex:
        for r, res in zip(todo, ex.map(lookup, todo)):
            done[r["address_id"]] = dict(res, retrieved_at=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()))
        again = [r for r in rows if "retry" not in done[r["address_id"]] and (
            done[r["address_id"]]["status"] == "no_match" or wrong_number(r, done[r["address_id"]]))]
        for r, res in zip(again, ex.map(lambda r: lookup(r, retry=True), again)):
            done[r["address_id"]] = dict(res, retry=True, original_query=done[r["address_id"]]["query"],
                                         retrieved_at=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()))
    OUT.write_text(json.dumps(dict(sorted(done.items())), indent=1))
    from collections import Counter
    print(Counter(v["status"] for v in done.values()), Counter(v.get("place") for v in done.values()))


if __name__ == "__main__":
    main()
