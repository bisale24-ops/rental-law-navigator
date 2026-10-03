"""Module B: which rules apply at an address on a date. Pure code, no model: the same inputs give the same answer.

Each rule's coverage was extracted into fields (cutoff dates, unit minimums, rolling age, exemptions); each
address has facts with their basis (facts.py). A test is three-valued: covered, not covered, or unknown because
the record lacks the fact. Any unknown test makes the rule "unknown" for that address, with the missing fact named.
"""
import datetime as dt

LEVEL_ORDER = {"state": 0, "city": 1}
# categories where a state rule steps aside for a stricter local one (the extracted rule says so in yields_to_local)
LAYERED = {"rent_increase_limits", "just_cause_eviction"}


def parse_date(s, end=False):
    """'2026-03-01' / '2026-03' / '2026' -> date. A partial date is taken at its start, or its end when end=True."""
    if not s:
        return None
    parts = [int(p) for p in str(s).split("-")]
    if len(parts) == 1:
        return dt.date(parts[0], 12, 31) if end else dt.date(parts[0], 1, 1)
    if len(parts) == 2:
        if end:
            nxt = dt.date(parts[0] + (parts[1] == 12), parts[1] % 12 + 1, 1)
            return nxt - dt.timedelta(days=1)
        return dt.date(parts[0], parts[1], 1)
    return dt.date(*parts)


def _built_test(cov, a):
    """Construction/certificate cutoffs. Year built is not the certificate date: a building in the cutoff year is
    unknown, and so is one with no year."""
    out = []
    basis = cov.get("built_basis") or "construction"
    word = "certificate of occupancy" if basis == "certificate_of_occupancy" else "construction"
    yb = a["year_built"]
    for key, before in (("built_on_or_before", True), ("built_after", False)):
        cut = parse_date(cov.get(key))
        if not cut:
            continue
        if yb is None:
            out.append(("unknown", f"coverage depends on the {word} date ({'on or before' if before else 'after'} "
                                   f"{cut.isoformat()}) and the record has no year built"))
        elif yb == cut.year:
            out.append(("unknown", f"built in {yb}, the cutoff year; the {word} date decides and is not in the record"))
        elif (yb < cut.year) == before:
            out.append(("yes", f"built {yb}, {'before' if before else 'after'} the {cut.isoformat()} cutoff"))
        else:
            out.append(("no", f"built {yb}, {'after' if before else 'before'} the {cut.isoformat()} cutoff"))
    n = cov.get("rolling_age_years")
    if n:
        if yb is None:
            out.append(("unknown", f"covers buildings more than {n} years old; the record has no year built"))
        else:
            age_cut = a["_as_of"].year - n
            if yb < age_cut:
                out.append(("yes", f"built {yb}, more than {n} years before the query date"))
            elif yb > age_cut:
                out.append(("no", f"built {yb}, less than {n} years before the query date"))
            else:
                out.append(("unknown", f"built {yb}: whether it is more than {n} years old depends on the exact date"))
    return out


def _units_test(cov, a):
    m = cov.get("min_units")
    if not m or m <= 1:
        return []
    lo, hi = a["units_low"], a["units_high"]
    if lo is not None and lo >= m:
        return [("yes", f"{lo}+ units ({a['units_basis']}), at least the {m} required")]
    if hi is not None and hi < m:
        return [("no", f"at most {hi} units ({a['units_basis']}), fewer than {m}")]
    return [("unknown", f"covers buildings with {m}+ units and the record does not say how many units ({a['units_basis']})")]


def _exemption_tests(cov, a):
    out = []
    n = cov.get("owner_exemption_max_units")
    if cov.get("owner_dependent"):
        if n and a["units_low"] is not None and a["units_low"] > n:
            out.append(("yes", f"the owner-based exemption only reaches buildings of {n} units or fewer; this one has "
                               f"{a['units_low']}+ ({a['units_basis']})"))
        else:
            cond = cov.get("owner_condition") or "who owns the property"
            out.append(("unknown", f"coverage depends on the owner ({cond}); owner data is deliberately not in the "
                                   "public record"))
    if cov.get("subsidized_excluded") and "subsidized" in a["flags"]:
        out.append(("unknown", f"subsidized units may be exempt and the record says '{a['use_description']}'"))
    if cov.get("unresolvable"):
        out.append(("unknown", f"coverage also depends on {cov['unresolvable'].rstrip('.')}, which the record cannot show"))
    return out


def coverage(rule, a):
    """('yes'|'no'|'unknown', reasons)."""
    cov = rule.get("coverage") or {}
    tests = _built_test(cov, a) + _units_test(cov, a) + _exemption_tests(cov, a)
    if any(t == "no" for t, _ in tests):
        return "no", [r for t, r in tests if t == "no"]
    if any(t == "unknown" for t, _ in tests):
        return "unknown", [r for t, r in tests if t != "no"]
    return "yes", [r for _, r in tests] or ["covers residential rentals in the jurisdiction; no size or age limit"]


def in_jurisdiction(rule, a):
    if rule["level"] == "state":
        return rule["jurisdiction"] == a["state"]
    if a["city"]:
        return rule["jurisdiction"] == a["city"]
    return rule["jurisdiction"] == f"{a['postal_city']}, {a['state']}"     # unresolved: say unknown, not absent


def status_on(rule, as_of):
    life = rule.get("lifecycle", "enacted")
    if life == "pending_bill":
        return "pending"
    if life in ("failed", "repealed"):
        return "failed"
    eff = parse_date(rule.get("effective_date"))
    if eff and eff > as_of:
        return "not_yet_effective"
    return "in_force"


def lookup(a, rules, as_of):
    """All rule results for one address on one date, in the submission's shape plus explanation detail."""
    a = dict(a, _as_of=as_of)
    rows = []
    for r in rules:
        if not in_jurisdiction(r, a):
            continue
        st = status_on(r, as_of)
        if st == "failed":
            continue                                  # never reported as a rule; shown as "not law" in the UI
        cov, why = coverage(r, a)
        if a["city"] is None and r["level"] == "city":
            cov, why = "unknown", [a["jurisdiction_basis"]]
        if cov == "no":
            continue                                  # rules that do not cover the address are left out
        if st == "pending":
            result = "pending"
            why = [f"a bill or proposal, not law, as of {as_of.isoformat()}"] + why
        elif st == "not_yet_effective":
            result = "not_yet_effective"
            why = [f"enacted; takes effect {r['effective_date']}, after the query date"] + why
        else:
            result = "applies" if cov == "yes" else "unknown"
        rows.append({"team_rule_id": r["team_rule_id"], "result": result, "category": r["category"],
                     "level": r["level"], "reasons": why, "conflict_flag": bool(r.get("conflict_flag")),
                     "conflict_note": r.get("conflict_note")})
    _layer(rows, rules)
    _preemption(rows, rules, a)
    for row in rows:
        row["explanation"] = "; ".join(row["reasons"])
    return rows


def _layer(rows, rules):
    """A state rule that yields to stricter local law is superseded where the local rule applies, and unknown
    where the local rule's own coverage is unknown."""
    by_id = {r["team_rule_id"]: r for r in rules}
    for row in rows:
        rule = by_id[row["team_rule_id"]]
        if row["level"] != "state" or not rule.get("yields_to_local") or row["category"] not in LAYERED:
            continue
        if row["result"] not in ("applies", "unknown"):
            continue
        local = [x for x in rows if x["level"] == "city" and x["category"] == row["category"]
                 and by_id[x["team_rule_id"]].get("lifecycle") == "enacted"]
        if any(x["result"] == "applies" for x in local):
            winner = next(x for x in local if x["result"] == "applies")
            row["result"] = "superseded"
            row["reasons"] = [f"covered, but the local rule {winner['team_rule_id']} "
                              f"({by_id[winner['team_rule_id']]['title']}) governs here"] + row["reasons"]
            row["superseded_by"] = winner["team_rule_id"]
        elif any(x["result"] == "unknown" for x in local) and row["result"] == "applies":
            other = next(x for x in local if x["result"] == "unknown")
            row["result"] = "unknown"
            row["reasons"] = [f"applies unless the local rule {other['team_rule_id']} covers the unit, and that "
                              "rule's coverage is unknown"] + row["reasons"]


def _preemption(rows, rules, a):
    """A state rule that may preempt local rules in its category: flag both for human review."""
    by_id = {r["team_rule_id"]: r for r in rules}
    for row in rows:
        rule = by_id[row["team_rule_id"]]
        if not rule.get("preempts_local"):
            continue
        local = [x for x in rows if x["level"] == "city" and x["category"] == row["category"]]
        for x in local:
            note = (f"possible conflict: {rule['title']} ({rule['citation']}) may preempt "
                    f"{by_id[x['team_rule_id']]['title']}; flagged for human review")
            for y in (row, x):
                y["conflict_flag"] = True
                y["conflict_note"] = note if not y.get("conflict_note") else y["conflict_note"] + " | " + note
                if note not in y["reasons"]:
                    y["reasons"].append(note)
