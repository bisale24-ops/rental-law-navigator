"""What the public record says about each address, and what it cannot say.

Every fact carries its basis, so an answer can explain itself: units come from the unit count when the assessor
gives one, otherwise from the use code ("Five or more apartments" proves at least 5, "4-8-UNIT-APT" bounds it to
4..8, a Jersey City description "3S-F-D-6U-NH" states 6 units). Missing facts stay missing.
"""
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "starter" / "pack"

PLACE = {"Los Angeles city": "Los Angeles, CA", "San Francisco city": "San Francisco, CA",
         "San Diego city": "San Diego, CA", "Berkeley city": "Berkeley, CA", "Santa Ana city": "Santa Ana, CA",
         "Jersey City city": "Jersey City, NJ", "Hoboken city": "Hoboken, NJ", "Newark city": "Newark, NJ",
         "Boston city": "Boston, MA", "Cambridge city": "Cambridge, MA"}

# Mailing names that lie wholly inside one incorporated city. Used only when the Census Geocoder cannot place
# the address (street-only assessor records). Boston's neighborhoods are not municipalities; San Francisco is a
# consolidated city and county, so every San Francisco mailing address is in the City.
POSTAL_INSIDE = {("Dorchester", "MA"): "Boston, MA", ("Roxbury", "MA"): "Boston, MA",
                 ("Hyde Park", "MA"): "Boston, MA", ("Mattapan", "MA"): "Boston, MA",
                 ("Boston", "MA"): "Boston, MA", ("San Francisco", "CA"): "San Francisco, CA"}


def unit_bounds(units, desc, use_code="", state=""):
    """(low, high, basis). high None = no upper bound known."""
    if units and units.strip().isdigit():
        n = int(units)
        return n, n, f"assessor unit count {n}"
    d = (desc or "").upper()
    m = re.search(r"(\d+)\s*TO\s*(\d+)\s*UNITS", d) or re.search(r"(\d+)-(\d+)[- ]UNIT", d) \
        or re.search(r"APT (\d+)-(\d+) UNITS", d)
    if m:
        return int(m.group(1)), int(m.group(2)), f"use code '{desc}'"
    m = re.search(r">\s*(\d+)-UNIT", d)
    if m:
        return int(m.group(1)) + 1, None, f"use code '{desc}'"
    m = re.search(r"(\d+)\s*UNITS OR MORE|(\d+)\s*OR MORE|\((\d+)\+ UNITS\)|FIVE OR MORE", d)
    if m:
        n = next((int(g) for g in m.groups() if g), 5)
        return n, None, f"use code '{desc}'"
    m = re.search(r"(\d+) UNITS OR LESS", d)
    if m:
        return 1, int(m.group(1)), f"use code '{desc}'"
    # New Jersey building descriptions: the 'NU' token is the unit count ('3S-F-D-6U-NH', '4B-8U', '2SF3UG').
    toks = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,3})U(?![A-Z])", d.replace("1OU", "10U"))]
    if toks:
        n = sum(toks) if "/" in d else toks[0]
        return n, n, f"building description '{desc}' states {n} units"
    # Property classes that are defined by size: New Jersey class 4C is "apartment" (5 or more units; 1-4 family
    # homes are class 2), and Boston land use "A" is residential with 7 or more units.
    if state == "NJ" and use_code == "4C":
        return 5, None, f"NJ property class 4C (apartments, 5+ units); description '{desc}' gives no count"
    if state == "MA" and use_code.startswith("A/"):
        return 7, None, f"Boston land use 'A' (7+ units), '{desc}'"
    return None, None, "no unit count in the record"


def flags(desc):
    d = (desc or "").upper()
    out = []
    if "SUBSD" in d or "S- 8" in d or "S-8" in d or "AFFORDABL" in d:
        out.append("subsidized")
    if "CO-OP" in d:
        out.append("cooperative")
    if "ELDERLY" in d:
        out.append("elderly_home")
    if "TIC" in d.split():
        out.append("tenancy_in_common")
    return out


def load():
    geo = json.loads((ROOT / "data" / "geocode.json").read_text())
    out = {}
    for r in csv.DictReader((PACK / "data" / "sample_addresses.csv").open()):
        g = geo.get(r["address_id"], {})
        place = PLACE.get(g.get("place") or "")
        if place:
            how = f"Census Geocoder: matched '{g['matched_address']}' inside {g['place']}"
            jconf = "geocoded"
        elif g.get("place"):
            place, how, jconf = None, f"Census Geocoder places it in {g['place']}, outside the covered cities", "geocoded"
        elif (r["postal_city"], r["state"]) in POSTAL_INSIDE:
            place = POSTAL_INSIDE[(r["postal_city"], r["state"])]
            how = (f"Census Geocoder found no match; mailing name '{r['postal_city']}' lies wholly inside "
                   f"{place.split(',')[0]}")
            jconf = "postal_inside"
        else:
            place, how, jconf = None, "Census Geocoder found no match and the mailing city spans several places", "unresolved"
        lo, hi, ubasis = unit_bounds(r["units"], r["use_description"], r["use_code"], r["state"])
        yb = int(r["year_built"]) if r["year_built"].strip().isdigit() and int(r["year_built"]) > 1700 else None
        out[r["address_id"]] = {
            "address_id": r["address_id"], "street": r["street_address"], "postal_city": r["postal_city"],
            "state": r["state"], "zip": r["zip"], "city": place, "jurisdiction_basis": how,
            "jurisdiction_confidence": jconf, "year_built": yb, "units_low": lo, "units_high": hi,
            "units_basis": ubasis, "use_code": r["use_code"], "use_description": r["use_description"],
            "flags": flags(r["use_description"]), "source_dataset": r["source_dataset"],
            "retrieved_at": r["retrieved_at"], "lat": g.get("lat"), "lon": g.get("lon")}
    return out


if __name__ == "__main__":
    from collections import Counter
    f = load()
    print(Counter(v["city"] for v in f.values()))
    print(Counter((v["city"], v["units_low"] is not None) for v in f.values()))
    for v in list(f.values()):
        if v["units_low"] is None and v["state"] == "NJ":
            print(v["address_id"], v["use_description"], v["units_basis"])
