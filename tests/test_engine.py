"""The guarantees the answers rest on. Run: python3 -m unittest discover tests"""
import datetime as dt
import unittest

from navigator import engine, extract, facts

D = dt.date(2026, 10, 1)


def addr(**kw):
    a = {"address_id": "X", "state": "CA", "city": "San Francisco, CA", "postal_city": "San Francisco",
         "year_built": 1960, "units_low": 10, "units_high": 10, "units_basis": "assessor unit count 10",
         "flags": [], "use_description": "Apartment", "jurisdiction_basis": "test"}
    a.update(kw)
    return a


def rule(rid, **kw):
    r = {"team_rule_id": rid, "jurisdiction": "San Francisco, CA", "level": "city", "category": "rent_increase_limits",
         "lifecycle": "enacted", "effective_date": None, "coverage": {}, "title": rid, "citation": rid}
    r.update(kw)
    return r


class Coverage(unittest.TestCase):
    def test_cutoff_year_is_unknown(self):
        r = rule("r1", coverage={"built_on_or_before": "1979-06-13", "built_basis": "certificate_of_occupancy"})
        self.assertEqual(engine.lookup(addr(year_built=1979), [r], D)[0]["result"], "unknown")
        self.assertEqual(engine.lookup(addr(year_built=1978), [r], D)[0]["result"], "applies")
        self.assertEqual(engine.lookup(addr(year_built=1985), [r], D), [])

    def test_missing_year_is_unknown_not_guessed(self):
        r = rule("r1", coverage={"built_on_or_before": "1979-06-13"})
        row = engine.lookup(addr(year_built=None), [r], D)[0]
        self.assertEqual(row["result"], "unknown")
        self.assertIn("no year built", row["explanation"])

    def test_owner_exemption_cannot_reach_big_buildings(self):
        r = rule("r1", coverage={"owner_dependent": True, "owner_exemption_max_units": 4})
        self.assertEqual(engine.lookup(addr(units_low=5, units_high=None), [r], D)[0]["result"], "applies")
        self.assertEqual(engine.lookup(addr(units_low=None, units_high=None), [r], D)[0]["result"], "unknown")

    def test_dates(self):
        r = rule("r1", effective_date="2027-07-01")
        self.assertEqual(engine.lookup(addr(), [r], D)[0]["result"], "not_yet_effective")
        self.assertEqual(engine.lookup(addr(), [r], dt.date(2027, 7, 2))[0]["result"], "applies")
        self.assertEqual(engine.lookup(addr(), [rule("r2", lifecycle="pending_bill")], D)[0]["result"], "pending")
        self.assertEqual(engine.lookup(addr(), [rule("r3", lifecycle="failed")], D), [])


class Layers(unittest.TestCase):
    def test_state_cap_superseded_where_local_control_applies(self):
        state = rule("s", jurisdiction="CA", level="state", yields_to_local=True)
        local = rule("c", coverage={"built_on_or_before": "1979-06-13"})
        res = {r["team_rule_id"]: r["result"] for r in engine.lookup(addr(year_built=1950), [state, local], D)}
        self.assertEqual(res, {"s": "superseded", "c": "applies"})
        res = {r["team_rule_id"]: r["result"] for r in engine.lookup(addr(year_built=1990), [state, local], D)}
        self.assertEqual(res, {"s": "applies"})

    def test_preemption_is_flagged_not_decided(self):
        state = rule("s", jurisdiction="CA", level="state", category="algorithmic_rent_setting", preempts_local=True,
                     effective_date="2027-07-01")
        local = rule("c", category="algorithmic_rent_setting")
        rows = engine.lookup(addr(), [state, local], D)
        self.assertTrue(all(r["conflict_flag"] for r in rows))

    def test_other_city_rules_never_leak(self):
        r = rule("hob", jurisdiction="Hoboken, NJ")
        self.assertEqual(engine.lookup(addr(state="NJ", city="Jersey City, NJ"), [r], D), [])


class Facts(unittest.TestCase):
    def test_units_from_use_codes(self):
        self.assertEqual(facts.unit_bounds("", "Five or more apartments")[:2], (5, None))
        self.assertEqual(facts.unit_bounds("", "4-8-UNIT-APT")[:2], (4, 8))
        self.assertEqual(facts.unit_bounds("", "3S-F-D-6U-NH")[:2], (6, 6))
        self.assertEqual(facts.unit_bounds("", "3SB", "4C", "NJ")[:2], (5, None))
        self.assertEqual(facts.unit_bounds("", "SUBSD HOUSING S- 8", "A/125", "MA")[:2], (7, None))
        self.assertEqual(facts.unit_bounds("", "TIC Bldg 4 units or less")[:2], (1, 4))


class Quotes(unittest.TestCase):
    TEXT = "Section 1. A security deposit may not exceed\none and one-half months’ rent. Section 2. Other."

    def test_exact_after_whitespace_and_quotes(self):
        got, how = extract.locate("A security deposit may not exceed one and one-half months' rent.", self.TEXT)
        self.assertEqual(how, "exact")
        self.assertIn("\n", got)                   # the source's own characters come back

    def test_invented_quote_is_dropped(self):
        got, how = extract.locate("Landlords must pay tenants a bonus of five thousand dollars.", self.TEXT)
        self.assertIsNone(got)

    def test_state_law_on_city_page_is_state(self):
        r = extract.normalize_jurisdiction({"jurisdiction": "Los Angeles, CA", "level": "city", "citation": "AB 1482",
                                            "title": "Tenant Protection Act"}, {"jurisdictions": "Los Angeles, CA"})
        self.assertEqual((r["jurisdiction"], r["level"]), ("CA", "state"))


if __name__ == "__main__":
    unittest.main()
