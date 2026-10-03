"""The submission files themselves: the organizers' schema, all 500 addresses, and the behaviour the change
tests ask for (dev/change_tests.json). Run after `python3 -m navigator.run`."""
import csv
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "starter" / "pack"
SCHEMA = json.loads((PACK / "schema" / "rule_record.schema.json").read_text())
RULES = json.loads((ROOT / "out" / "rules.json").read_text())["rules"]
LOOK = json.loads((ROOT / "out" / "lookups.json").read_text())
CH = json.loads((ROOT / "out" / "changes.json").read_text())
ADDR = {r["address_id"]: r for r in csv.DictReader((PACK / "data" / "sample_addresses.csv").open())}
GEO = json.loads((ROOT / "data" / "geocode.json").read_text())


def city(aid):
    return (GEO[aid].get("place") or "").replace(" city", "")


class Schema(unittest.TestCase):
    def test_every_rule_matches_the_schema(self):
        props = SCHEMA["properties"]
        for r in RULES:
            for k in SCHEMA["required"]:
                self.assertIn(k, r, r.get("team_rule_id"))
            for k, spec in props.items():
                if k not in r:
                    continue
                v = r[k]
                if "enum" in spec:
                    self.assertIn(v, spec["enum"], (r["team_rule_id"], k))
                if k == "effective_date" and v is not None:
                    self.assertRegex(v, spec["pattern"])
                if k == "quoted_span":
                    self.assertGreaterEqual(len(v), 20)
                if k == "confidence" and v is not None:
                    self.assertTrue(0 <= v <= 1)
        self.assertEqual(len({r["team_rule_id"] for r in RULES}), len(RULES))

    def test_every_quote_is_in_its_source(self):
        def norm(s):
            s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "}))
            return re.sub(r"\s+", " ", s).strip().lower()
        for r in RULES:
            p = PACK / "corpus" / "text" / f"{r['source_doc_id']}.txt"
            if not p.exists():
                p = ROOT / "data" / "supplement" / "text" / f"{r['source_doc_id']}.txt"
            self.assertIn(norm(r["quoted_span"]), norm(p.read_text()), r["team_rule_id"])


class Lookups(unittest.TestCase):
    def test_all_500_addresses_with_valid_results(self):
        self.assertEqual(LOOK["as_of"], "2026-10-01")
        self.assertEqual(set(LOOK["lookups"]), set(ADDR))
        ids = {r["team_rule_id"] for r in RULES}
        for aid, rows in LOOK["lookups"].items():
            for x in rows:
                self.assertIn(x["result"], {"applies", "unknown", "superseded", "not_yet_effective", "pending"})
                self.assertIn(x["team_rule_id"], ids)
                self.assertTrue(x["explanation"])

    def test_city_rules_stay_in_their_city(self):
        by = {r["team_rule_id"]: r for r in RULES}
        for aid, rows in LOOK["lookups"].items():
            for x in rows:
                j = by[x["team_rule_id"]]["jurisdiction"]
                if "," in j and city(aid):
                    self.assertEqual(j.split(",")[0], city(aid), (aid, x["team_rule_id"]))


class ChangeTests(unittest.TestCase):
    def cities(self, ids):
        return {city(a) for a in ids}

    def test_t1_every_ca_address(self):
        ca = {a for a, r in ADDR.items() if r["state"] == "CA"}
        self.assertEqual(set(CH["T1"]["affected_address_ids"]), ca)

    def test_t2_boundary(self):
        hit = self.cities(CH["T2"]["affected_address_ids"])
        self.assertEqual(hit, {"Hoboken", "Jersey City"})

    def test_t3_nj_and_flags_only_in_jersey_city_and_hoboken(self):
        nj = {a for a, r in ADDR.items() if r["state"] == "NJ"}
        self.assertEqual(set(CH["T3"]["affected_address_ids"]), nj)
        self.assertEqual(self.cities(CH["T3"]["conflict_flag_address_ids"]), {"Hoboken", "Jersey City"})
        jc_hob = {a for a in nj if city(a) in ("Hoboken", "Jersey City")}
        self.assertEqual(set(CH["T3"]["conflict_flag_address_ids"]), jc_hob)

    def test_t4_pending_for_every_ma_address(self):
        ma = {a for a, r in ADDR.items() if r["state"] == "MA"}
        self.assertEqual(set(CH["T4"]["affected_address_ids"]), ma)

    def test_t5_no_rent_cap_in_massachusetts(self):
        self.assertEqual(CH["T5"]["affected_address_ids"], [])
        self.assertIn("failed", CH["T5"]["notes"])
        by = {r["team_rule_id"]: r for r in RULES}
        for aid, rows in LOOK["lookups"].items():
            if ADDR[aid]["state"] == "MA":
                for x in rows:
                    r = by[x["team_rule_id"]]
                    if r["category"] == "rent_increase_limits" and x["result"] == "applies":
                        self.assertIn("prohibit", (r["title"] + r["requirement"]).lower(), r["team_rule_id"])


if __name__ == "__main__":
    unittest.main()
