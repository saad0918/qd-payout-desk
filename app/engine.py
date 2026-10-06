"""Pure payout audit: what each rider should have earned (docs/policy.md) vs what the payout export shows.
No I/O, no LLM, no clock. Everything money-related that is not 'how much PaySwift says we paid' lives here."""
from dataclasses import dataclass, asdict
from decimal import Decimal as D, ROUND_HALF_UP
from datetime import date

BASE, PER_KM, FREE_KM = D(25), D(6), D(2)
INCENTIVE, INCENTIVE_TRIPS, PENALTY = D(150), 12, D(10)
WINDOW_DAYS = 7

def rupee(x: D) -> int:
    return int(x.quantize(D(1), rounding=ROUND_HALF_UP))      # 0.5 rounds up (policy)

def trip_fare(km, surge) -> int:
    km, s = D(str(km)), D(str(surge))
    return rupee((BASE + PER_KM * max(D(0), km - FREE_KM)) * s)

def expected_trip_amount(t) -> int:
    if t["status"] == "completed": return trip_fare(t["km"], t["surge_multiplier"])
    if t["status"] == "cancelled_by_rider": return -int(PENALTY)
    return 0                                                   # customer cancellations earn nothing

@dataclass(frozen=True)
class Finding:
    id: str            # stable: '<kind>:<trip_id or day>'
    kind: str          # trip_underpaid | trip_unpaid | penalty_duplicate | incentive_missing
    day: str           # IST day the trip/incentive belongs to
    trip_id: str | None
    expected: int
    paid: int
    owed: int          # rupees the rider is short (always > 0)
    cause: str         # plain-language reason, used in replies
    def dict(self): return asdict(self)

def _cause_underpaid(t, paid):
    km, s = t["km"], D(t["surge_multiplier"])
    no_surge = rupee(BASE + PER_KM * max(D(0), km - FREE_KM))
    flat = rupee(BASE * s)
    if s > 1 and paid == no_surge: return f"surge {s}x was not applied"
    if paid == BASE or paid == flat: return f"distance ({km} km) was not counted"
    return "paid less than the policy fare"

def audit_rider(rider_id: str, trips, lines) -> list[Finding]:
    mine = [t for t in trips if t["rider_id"] == rider_id]
    by_trip: dict[str, list] = {}
    for l in lines:
        if l["rider_id"] == rider_id and l["trip_id"]: by_trip.setdefault(l["trip_id"], []).append(l)
    out: list[Finding] = []
    for t in mine:
        exp, ls = expected_trip_amount(t), by_trip.get(t["trip_id"], [])
        paid = sum(int(l["amount"]) for l in ls)
        if t["status"] == "completed":
            if not ls:   out.append(Finding(f"trip_unpaid:{t['trip_id']}", "trip_unpaid", t["day"], t["trip_id"], exp, 0, exp,
                                            "completed trip has no payout line"))
            elif paid < exp: out.append(Finding(f"trip_underpaid:{t['trip_id']}", "trip_underpaid", t["day"], t["trip_id"], exp, paid,
                                                exp - paid, _cause_underpaid(t, paid)))
        elif t["status"] == "cancelled_by_rider" and len(ls) > 1 and paid < exp:
            out.append(Finding(f"penalty_duplicate:{t['trip_id']}", "penalty_duplicate", t["day"], t["trip_id"], exp, paid,
                               exp - paid, f"cancellation penalty was charged {len(ls)} times for one cancelled trip"))
    # daily incentive: >=12 completed trips on the IST day
    done: dict[str, int] = {}
    for t in mine:
        if t["status"] == "completed": done[t["day"]] = done.get(t["day"], 0) + 1
    got = {l["payout_date"] for l in lines if l["rider_id"] == rider_id and l["line_type"] == "daily_incentive"}
    for day, n in done.items():
        if n >= INCENTIVE_TRIPS and day not in got:
            out.append(Finding(f"incentive_missing:{day}", "incentive_missing", day, None, int(INCENTIVE), 0, int(INCENTIVE),
                               f"{n} completed trips that day, daily incentive was not paid"))
    return sorted(out, key=lambda f: (f.day, f.id))

def day_summary(rider_id: str, day: str, trips, lines) -> dict:
    mine = [t for t in trips if t["rider_id"] == rider_id and t["day"] == day]
    cnt = lambda s: sum(1 for t in mine if t["status"] == s)
    return {"day": day, "completed": cnt("completed"), "cancelled_by_rider": cnt("cancelled_by_rider"),
            "cancelled_by_customer": cnt("cancelled_by_customer"), "incentive_threshold": INCENTIVE_TRIPS,
            "incentive_paid": any(l["rider_id"] == rider_id and l["payout_date"] == day and l["line_type"] == "daily_incentive" for l in lines)}

def in_window(day: str, received_day: date) -> bool:
    d = (received_day - date.fromisoformat(day)).days
    return 0 <= d <= WINDOW_DAYS

def dispute_groups(findings: list[Finding]) -> list[list[Finding]]:
    """One dispute per (kind, IST day). Deterministic, so the LLM cannot split or merge claims to dodge limits."""
    g: dict[tuple, list[Finding]] = {}
    for f in findings: g.setdefault((f.kind, f.day), []).append(f)
    return [sorted(v, key=lambda f: f.id) for _, v in sorted(g.items())]
