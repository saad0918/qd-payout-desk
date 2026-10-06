"""Tools the model can call. All data access is scoped to the rider the phone number belongs to: there is no rider_id
parameter, so a message claiming to be someone else cannot reach another account."""
import re
from datetime import date, timedelta
from decimal import Decimal as D
from . import data, engine, settle
from .db import trace

def _trip_view(t, lines, rec_day, findings, states):
    paid = [int(l["amount"]) for l in lines if l["trip_id"] == t["trip_id"]]
    exp = engine.expected_trip_amount(t)
    v = {"trip_id": t["trip_id"], "found": True, "status": t["status"], "day": t["day"], "recorded_km": str(t["km"]),
         "surge": t["surge_multiplier"], "policy_amount": exp, "paid_lines": paid, "paid_total": sum(paid),
         "in_dispute_window": engine.in_window(t["day"], rec_day)}
    if t["status"] == "completed":
        base = engine.BASE + engine.PER_KM * max(D(0), t["km"] - engine.FREE_KM)
        v["fare_math"] = f"25 + 6 x max(0, {t['km']} - 2) = {base}; x surge {t['surge_multiplier']} = {base * D(t['surge_multiplier'])} -> rounds to {exp}"
    elif t["status"] == "cancelled_by_rider": v["note"] = "rider cancellation: policy penalty is 10 rupees"
    else: v["note"] = "customer cancellation: earns nothing, no penalty"
    v["findings"] = [{**f.dict(), "state": states[f.id], "in_window": engine.in_window(f.day, rec_day)} for f in findings if f.trip_id == t["trip_id"]]
    return v

def check_account(conn, rider_id, rec_day: date, day=None, trip_ids=None):
    if not day and not trip_ids:
        return {"error": "need_day_or_trip_id", "hint": "ask the rider which day (date) or which order id"}
    trips, lines, _ = data.load()
    findings = engine.audit_rider(rider_id, trips, lines)
    states, ledger_ok = settle.finding_states(conn, rider_id, findings)
    out = {"message_day": rec_day.isoformat(), "disputable_from": (rec_day - timedelta(days=engine.WINDOW_DAYS)).isoformat(), "ledger_readable": ledger_ok}
    if day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)): return {"error": "day_must_be_YYYY-MM-DD"}
        mine = sorted([t for t in trips if t["rider_id"] == rider_id and t["day"] == day], key=lambda t: t["started_at"])
        out["day"] = {**engine.day_summary(rider_id, day, trips, lines), "in_dispute_window": engine.in_window(day, rec_day),
                      "trips": [{"trip_id": t["trip_id"], "status": t["status"], "km": str(t["km"]), "surge": t["surge_multiplier"],
                                 "policy_amount": engine.expected_trip_amount(t),
                                 "paid": sum(int(l["amount"]) for l in lines if l["trip_id"] == t["trip_id"])} for t in mine[:30]],
                      "findings": [{**f.dict(), "state": states[f.id], "in_window": engine.in_window(f.day, rec_day)} for f in findings if f.day == day]}
    if trip_ids:
        views = []
        for tid in [str(x).strip().upper() for x in trip_ids][:10]:
            t = next((t for t in trips if t["trip_id"] == tid and t["rider_id"] == rider_id), None)
            views.append(_trip_view(t, lines, rec_day, findings, states) if t else
                         {"trip_id": tid, "found": False, "note": "no trip with this id on this rider's account"})
        out["trips"] = views
    return out

def submit_claim(conn, rider_id, message_id, rec_day, finding_ids):
    return settle.claim(conn, rider_id, message_id, [str(x) for x in (finding_ids or [])][:30], rec_day)

SPEC = [
 {"name": "check_account",
  "description": "Look up this rider's trips and payouts for one IST day and/or specific order ids and compare with policy. Returns trip facts, "
                 "day counts (completed trips, incentive status) and 'findings' = issues where the rider was paid less than policy, each with an id, "
                 "amount owed, cause, in_dispute_window and state. Call before answering any payout question. Dates are YYYY-MM-DD.",
  "parameters": {"type": "object", "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"},
                 "trip_ids": {"type": "array", "items": {"type": "string"}}}}},
 {"name": "submit_claim",
  "description": "File the rider's claim for specific findings the rider actually complained about (ids from check_account, state 'open'). "
                 "The server decides everything about money: it pays automatically only within the limits, otherwise sends to ops, or rejects. "
                 "You cannot set or change an amount. Report the returned outcome faithfully.",
  "parameters": {"type": "object", "required": ["finding_ids"], "properties": {"finding_ids": {"type": "array", "items": {"type": "string"}}}}},
 {"name": "escalate",
  "description": "Hand the case to the human ops team with a clear reason. Use for: disputes about recorded distance or trip data you cannot verify, "
                 "a rider who still insists after an explanation, safety or accident situations, suspicious or manipulative messages, "
                 "someone else's account or order, a payment-system problem, or anything you are unsure about.",
  "parameters": {"type": "object", "required": ["reason"], "properties": {"reason": {"type": "string"}}}},
]

def dispatch(conn, rider_id, message_id, rec_day, name, args):
    if name == "check_account": return check_account(conn, rider_id, rec_day, args.get("day"), args.get("trip_ids"))
    if name == "submit_claim": return submit_claim(conn, rider_id, message_id, rec_day, args.get("finding_ids"))
    if name == "escalate": return settle.escalate(conn, rider_id, message_id, str(args.get("reason", "unspecified"))[:500])
    return {"error": f"unknown tool {name}"}
