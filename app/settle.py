"""Everything that touches money. The LLM never reaches this with an amount: it names findings (issues the audit
engine already computed); the amount, the limits and the payment are decided here."""
import hashlib, psycopg
from datetime import datetime, date
from . import data, engine, payswift, rules
from .data import IST
from .db import trace, rider_lock, try_rider_lock

def today_ist() -> date: return datetime.now(IST).date()

def dispute_key(rider_id, ids) -> str:
    return "qd-" + hashlib.sha1((rider_id + "|" + ",".join(sorted(ids))).encode()).hexdigest()[:16]

def reference(key, mode, ids) -> str:            # this string is how PaySwift (the ledger we reconcile against) remembers why
    return f"{key}|{mode}|{','.join(sorted(ids))}"

def received_day(received_at: str | None) -> date:
    try: return datetime.fromisoformat(received_at).astimezone(IST).date()
    except Exception: return today_ist()

def ledger_view(rider_id):
    """From PaySwift, not our DB: which findings are already compensated, and has an auto-payment gone out today?"""
    comp, auto_today = set(), False
    for p in payswift.list_payouts(rider_id):
        parts = (p.get("reference") or "").split("|")
        if len(parts) < 3 or not parts[0].startswith("qd-"): continue
        comp.update(parts[2].split(","))
        if parts[1] == "auto" and payswift.created_day_ist(p) == today_ist(): auto_today = True
    return comp, auto_today

def _db_auto_today(conn, rider_id):
    return conn.execute("select 1 from payouts where rider_id=%s and pay_day=%s and auto and status in ('pending','paid')",
                        (rider_id, today_ist())).fetchone() is not None

def finding_states(conn, rider_id, findings):
    """open | already_paid | payment_processing | waiting_for_ops | rejected_by_ops | escalated"""
    try: comp, _ = ledger_view(rider_id); ledger_ok = True
    except Exception: comp, ledger_ok = set(), False
    st = {}
    for r in conn.execute("select finding_ids, status from disputes where rider_id=%s order by id", (rider_id,)).fetchall():
        for fid in r["finding_ids"]: st[fid] = r["status"]
    m = {"paid": "already_paid", "pending_payment": "payment_processing", "awaiting_approval": "waiting_for_ops",
         "rejected": "rejected_by_ops", "escalated": "escalated"}
    return {f.id: ("already_paid" if f.id in comp else m.get(st.get(f.id), "open")) for f in findings}, ledger_ok

def escalate(conn, rider_id, message_id, reason, dispute_id=None):
    dup = conn.execute("select id from approvals where rider_id=%s and type='escalation' and status='open' and reason=%s "
                       "and coalesce(message_id,'')=coalesce(%s,'')", (rider_id, reason, message_id)).fetchone()
    if not dup:
        conn.execute("insert into approvals(rider_id,dispute_id,type,amount,reason,message_id) values(%s,%s,'escalation',null,%s,%s)",
                     (rider_id, dispute_id, reason, message_id))
    trace(conn, rider_id, message_id, "decision", "escalated_to_ops", {"reason": reason}, {"ok": True})
    return {"outcome": "escalated_to_ops", "reason": reason}

def _set(conn, dispute_id, status, reason=None):
    conn.execute("update disputes set status=%s, reason=coalesce(%s,reason), updated_at=now() where id=%s", (status, reason, dispute_id))

def _apply_result(conn, payout_row_id, dispute_id, rider_id, message_id, res):
    if res.status == "paid":
        conn.execute("update payouts set status='paid', payout_id=%s, detail=%s, updated_at=now() where id=%s", (res.payout_id, res.detail, payout_row_id))
        _set(conn, dispute_id, "paid"); return "paid"
    if res.status == "failed":
        conn.execute("update payouts set status='failed', detail=%s, updated_at=now() where id=%s", (res.detail, payout_row_id))
        _set(conn, dispute_id, "escalated", f"payment failed: {res.detail}")
        escalate(conn, rider_id, message_id, f"PaySwift rejected the payout: {res.detail}", dispute_id); return "failed"
    conn.execute("update payouts set detail=%s, updated_at=now() where id=%s", (res.detail, payout_row_id))
    _set(conn, dispute_id, "pending_payment", res.detail); return "processing"       # reconciler finishes it

def execute_payout(conn, dispute_id, rider_id, message_id, key, ids, amount, mode):
    """mode 'auto' (counts toward the once-per-day limit) or 'ops' (human approved)."""
    ref = reference(key, mode, ids)
    try:
        row = conn.execute("insert into payouts(dispute_id,rider_id,amount,idempotency_key,reference,status,auto,pay_day) "
                           "values(%s,%s,%s,%s,%s,'pending',%s,%s) returning id",
                           (dispute_id, rider_id, amount, key, ref, mode == "auto", today_ist())).fetchone()
    except psycopg.errors.UniqueViolation:
        return "limit_raced"                         # DB guard: second auto-payout today, or key already used
    res = payswift.pay(rider_id, amount, key, ref)
    trace(conn, rider_id, message_id, "tool_call", "payswift.pay", {"rider_id": rider_id, "amount": amount, "idempotency_key": key, "reference": ref},
          {"status": res.status, "payout_id": res.payout_id, "detail": res.detail})
    return _apply_result(conn, row["id"], dispute_id, rider_id, message_id, res)

def _process_group(conn, rider_id, message_id, group, auto_used):
    ids, amount = [f.id for f in group], sum(f.owed for f in group)
    key, kind, day = dispute_key(rider_id, ids), group[0].kind, group[0].day
    base = {"kind": kind, "day": day, "trip_ids": [f.trip_id for f in group if f.trip_id], "finding_ids": ids, "amount": amount,
            "causes": sorted({f.cause for f in group})}
    dec = rules.decide(amount, auto_used)
    trace(conn, rider_id, message_id, "decision", "auto_pay_check", {"amount": amount, "auto_used_today": auto_used, "limit": rules.AUTO_LIMIT},
          {"action": dec.action, "reason": dec.reason})
    status = "pending_payment" if dec.action == "pay" else "awaiting_approval"
    row = conn.execute("insert into disputes(key,rider_id,kind,day,finding_ids,amount,status,reason,message_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                       "on conflict (key) do nothing returning id", (key, rider_id, kind, day, ids, amount, status, dec.reason, message_id)).fetchone()
    if not row:
        d = conn.execute("select status from disputes where key=%s", (key,)).fetchone()
        return {**base, "outcome": {"paid": "already_paid", "awaiting_approval": "waiting_for_ops", "pending_payment": "payment_processing"}.get(d["status"], d["status"])}
    did = row["id"]
    if dec.action == "pay":
        out = execute_payout(conn, did, rider_id, message_id, key, ids, amount, "auto")
        if out == "limit_raced":
            _set(conn, did, "awaiting_approval", "auto-payment limit already used today")
            conn.execute("insert into approvals(rider_id,dispute_id,type,amount,reason,message_id) values(%s,%s,'approval',%s,%s,%s)",
                         (rider_id, did, amount, "rider already received an auto-payment today", message_id))
            return {**base, "outcome": "awaiting_ops_approval", "reason": "only one automatic payment per rider per day"}
        return {**base, "outcome": {"paid": "paid", "processing": "payment_processing", "failed": "escalated_to_ops"}[out]}
    conn.execute("insert into approvals(rider_id,dispute_id,type,amount,reason,message_id) values(%s,%s,'approval',%s,%s,%s)",
                 (rider_id, did, amount, dec.reason, message_id))
    return {**base, "outcome": "awaiting_ops_approval", "reason": dec.reason}

def claim(conn, rider_id, message_id, finding_ids, rec_day: date) -> dict:
    trips, lines, _ = data.load()
    known = {f.id: f for f in engine.audit_rider(rider_id, trips, lines)}
    results, wanted = [], []
    for fid in dict.fromkeys(finding_ids or []):
        if fid in known: wanted.append(known[fid])
        else: results.append({"finding_id": fid, "outcome": "not_a_known_issue"})
    if not wanted:
        return {"results": results, "note": "nothing payable was found for these ids"}
    try:
        _, auto_ps = ledger_view(rider_id)
        states, _ = finding_states(conn, rider_id, wanted)
    except Exception as e:
        escalate(conn, rider_id, message_id, f"Could not read the PaySwift ledger, so nothing was paid: {e}")
        return {"results": results + [{"outcome": "escalated_to_ops", "reason": "payment system unavailable"}]}
    eligible = []
    for f in wanted:
        s = states[f.id]
        if s != "open": results.append({"finding_id": f.id, "trip_id": f.trip_id, "owed": f.owed, "outcome": s})
        elif not engine.in_window(f.day, rec_day):
            results.append({"finding_id": f.id, "trip_id": f.trip_id, "day": f.day, "owed": f.owed, "outcome": "outside_dispute_window",
                            "window": f"last {engine.WINDOW_DAYS} days"})
            trace(conn, rider_id, message_id, "decision", "outside_dispute_window", {"finding": f.id, "day": f.day}, {"outcome": "rejected"})
        else: eligible.append(f)
    auto_used = auto_ps or _db_auto_today(conn, rider_id)
    for g in engine.dispute_groups(eligible):
        r = _process_group(conn, rider_id, message_id, g, auto_used)
        results.append(r)
        auto_used = auto_used or r["outcome"] in ("paid", "payment_processing")
    return {"results": results}

# ---------------- ops ----------------
def ops_decide(conn, approval_id: int, action: str, who="ops") -> dict:
    a = conn.execute("select * from approvals where id=%s", (approval_id,)).fetchone()
    if not a or a["status"] != "open": return {"ok": False, "error": "not_open"}
    with rider_lock(conn, a["rider_id"]):
        a = conn.execute("select * from approvals where id=%s", (approval_id,)).fetchone()
        if a["status"] != "open": return {"ok": False, "error": "not_open"}
        result = None
        if a["type"] == "escalation":
            conn.execute("update approvals set status='resolved', decided_by=%s, decided_at=now() where id=%s", (who, approval_id)); result = "resolved"
        elif action == "reject":
            _set(conn, a["dispute_id"], "rejected", f"rejected by {who}")
            conn.execute("update approvals set status='rejected', decided_by=%s, decided_at=now() where id=%s", (who, approval_id)); result = "rejected"
        else:
            d = conn.execute("select * from disputes where id=%s", (a["dispute_id"],)).fetchone()
            trips, lines, _ = data.load()
            known = {f.id: f for f in engine.audit_rider(d["rider_id"], trips, lines)}
            comp, _ = ledger_view(d["rider_id"])               # never pay more than owed: re-derive from engine + PaySwift now
            ids = [i for i in d["finding_ids"] if i in known and i not in comp]
            amount = sum(known[i].owed for i in ids)
            if amount <= 0:
                _set(conn, d["id"], "paid", "already compensated"); result = "nothing_left_to_pay"
            else:
                out = execute_payout(conn, d["id"], d["rider_id"], None, d["key"], ids, amount, "ops")
                result = {"limit_raced": "failed"}.get(out, out)
            conn.execute("update approvals set status='approved', decided_by=%s, decided_at=now() where id=%s", (who, approval_id))
        trace(conn, a["rider_id"], None, "decision", f"ops_{action}", {"approval_id": approval_id, "by": who}, {"result": result})
    return {"ok": True, "result": result}

def reconcile(conn):
    """Finish payments left 'pending' by a timeout / rate-limit block. Safe to run any time: same key, verified against PaySwift."""
    rows = conn.execute("select * from payouts where status='pending' and updated_at < now() - interval '4 seconds' order by id limit 20").fetchall()
    for p in rows:
        with try_rider_lock(conn, p["rider_id"]) as got:
            if not got: continue
            cur = conn.execute("select status from payouts where id=%s", (p["id"],)).fetchone()
            if cur["status"] != "pending": continue
            try: hit = payswift.find_by_reference(p["rider_id"], p["reference"])
            except Exception: continue
            res = payswift.PayResult("paid", hit.get("payout_id"), "confirmed in PaySwift ledger") if hit else \
                  payswift.pay(p["rider_id"], p["amount"], p["idempotency_key"], p["reference"])
            trace(conn, p["rider_id"], None, "tool_call", "payswift.reconcile", {"idempotency_key": p["idempotency_key"]}, {"status": res.status, "detail": res.detail})
            _apply_result(conn, p["id"], p["dispute_id"], p["rider_id"], None, res)
    # a dispute left 'pending_payment' with no payout row (crash mid-request) would block the rider forever: hand it to a human
    for o in conn.execute("select d.id, d.rider_id from disputes d where d.status='pending_payment' and d.updated_at < now() - interval '30 seconds' "
                          "and not exists (select 1 from payouts p where p.dispute_id=d.id)").fetchall():
        _set(conn, o["id"], "escalated", "payment was never started"); escalate(conn, o["rider_id"], None, "A payment was approved but never started; check and pay manually", o["id"])
    old = conn.execute("select p.dispute_id, p.rider_id from payouts p where p.status='pending' and p.created_at < now() - interval '10 minutes' "
                       "and not exists (select 1 from approvals a where a.dispute_id=p.dispute_id and a.type='escalation')").fetchall()
    for o in old: escalate(conn, o["rider_id"], None, "Payment still unconfirmed after 10 minutes; check PaySwift manually", o["dispute_id"])
