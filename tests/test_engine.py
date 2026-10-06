from datetime import date
import pytest
from app import data, engine

trips, lines, riders = data.load()
def owed(rider, **k):
    return sum(f.owed for f in engine.audit_rider(rider, trips, lines) if all(getattr(f, a) == v for a, v in k.items()))

def test_fare_half_rupee_rounds_up():            # 5 km, 1.5x: (25+18)*1.5 = 64.5 -> 65 (policy: 0.5 rounds up, not banker's)
    assert engine.trip_fare(5.0, 1.5) == 65 and engine.trip_fare(2.0, 1.0) == 25 and engine.trip_fare(1.0, 1.0) == 25

def test_all_sample_conversation_amounts():       # derived from data/conversations.json `expected`
    cases = [("R003", dict(day="2026-09-20"), 25), ("R005", dict(day="2026-09-21"), 150), ("R014", dict(kind="penalty_duplicate"), 10),
             ("R016", dict(day="2026-09-19", kind="trip_unpaid"), 425), ("R024", dict(day="2026-09-18"), 150),
             ("R007", dict(trip_id="T840677"), 34), ("R031", dict(trip_id="T312538"), 22), ("R026", dict(trip_id="T672899"), 32),
             ("R033", dict(day="2026-09-20"), 176), ("R034", dict(day="2026-09-19", kind="trip_unpaid"), 249),
             ("R035", dict(trip_id="T980582"), 25), ("R027", dict(day="2026-09-20"), 15), ("R027", dict(day="2026-09-21"), 10)]
    for r, k, exp in cases: assert owed(r, **k) == exp, (r, k)

@pytest.mark.parametrize("rider,day", [("R011", "2026-09-19"), ("R025", "2026-09-19"), ("R009", "2026-09-17")])
def test_incentive_claims_that_are_wrong(rider, day):
    assert owed(rider, day=day) == 0                          # 10 / 11 / 11 completed trips, not 12

def test_duplicate_trip_rows_not_double_counted():            # R009's export lists T310191 twice -> 11 trips, not 12
    s = engine.day_summary("R009", "2026-09-17", trips, lines); assert s["completed"] == 11

def test_distance_in_metres_is_normalised():                  # 'distance_km'=5000 means 5 km
    t = next(t for t in trips if t["trip_id"] == "T312538"); assert str(t["km"]) == "5" or t["km"] == 5

def test_malformed_rider_ids_normalised():
    assert data.norm_rider("R7") == "R007" and data.norm_rider("r19") == "R019" and data.norm_rider(" R003 ") == "R003"
    assert any(t["trip_id"] == "T840677" and t["rider_id"] == "R007" for t in trips)

def test_policy_day_is_ist_not_utc():                         # a trip at 20:00Z belongs to the NEXT IST day
    t = next(t for t in trips if t["started_at"][:10] != t["day"]); assert t["day"] > t["started_at"][:10]
    assert data.to_ist("2026-09-18T20:00:00Z").date().isoformat() == "2026-09-19"

def test_other_riders_trip_is_not_findings_of_this_rider():
    assert all(f.trip_id != "T482410" for f in engine.audit_rider("R021", trips, lines))

def test_dispute_window():
    d = date(2026, 9, 23)
    assert engine.in_window("2026-09-16", d) and not engine.in_window("2026-09-15", d) and not engine.in_window("2026-09-13", d)
    assert not engine.in_window("2026-09-24", d)               # future days make no sense

def test_dispute_groups_are_deterministic_by_kind_and_day():
    fs = engine.audit_rider("R016", trips, lines) + engine.audit_rider("R027", trips, lines)
    assert sorted(len(g) for g in engine.dispute_groups(fs)) == [1, 1, 5]    # R016: five unpaid trips on one day = ONE dispute

def test_never_negative_owed():
    assert all(f.owed > 0 for r in riders for f in engine.audit_rider(r, trips, lines))
