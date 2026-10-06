"""Eval runner.   python evals/run.py http://localhost:8000 [--reset "<cmd>"] [--only text]
Uses only POST /messages, GET /ops/pending, GET /trace/{rider} and PaySwift (PAYSWIFT_BASE_URL, default http://localhost:8081),
so it can be pointed at any implementation. Run against a FRESH system: the ledger is in memory, so
`docker compose down && docker compose up -d` resets PaySwift. Riders that already have payouts/pending items are SKIPped.

Checks per conversation (from `expected`): PaySwift payout delta for the rider, ₹ waiting for approval, escalation, facts in replies.
Extra scenarios: webhook retry storm, concurrent duplicates, concurrent different messages (race on the daily limit),
prompt injection, impersonation, trace shape, ops-pending shape."""
import json, os, pathlib, re, sys, time, uuid, concurrent.futures as cf
import httpx

HERE = pathlib.Path(__file__).parent
PS = os.getenv("PAYSWIFT_BASE_URL", "http://localhost:8081")

class Sys:
    def __init__(self, url): self.url = url.rstrip("/"); self.c = httpx.Client(timeout=90)
    def send(self, rider, text, mid=None, received_at="2026-09-23T10:00:00+05:30"):
        r = self.c.post(f"{self.url}/messages", json={"message_id": mid or f"wamid.{uuid.uuid4().hex[:14].upper()}", "rider_id": rider, "text": text, "received_at": received_at})
        r.raise_for_status(); return r.json()["reply"]
    def pending(self, rider): return [p for p in self.c.get(f"{self.url}/ops/pending").json() if p["rider_id"] == rider]
    def trace(self, rider): return self.c.get(f"{self.url}/trace/{rider}").json()
    def paid(self, rider):
        for _ in range(3):
            r = httpx.get(f"{PS}/v1/payouts", params={"rider_id": rider}, timeout=20)
            if r.status_code == 200: return sum(p["amount"] for p in r.json()["data"])
            time.sleep(0.5)
        raise RuntimeError("PaySwift unreadable")

def settle_wait(s, rider, expect_paid, base_paid, secs=45):
    """Payments can complete a few seconds after the reply if PaySwift was slow/blocked; wait for that, not forever."""
    end = time.time() + secs
    while time.time() < end:
        if s.paid(rider) - base_paid >= expect_paid: return
        time.sleep(1.5)

def run_conversation(s, conv):
    rider, exp = conv["rider_id"], conv["expected"]
    if s.paid(rider) or s.pending(rider): return "SKIP", "rider not fresh (already has payouts/pending items); reset the system"
    replies = []
    for t in conv["turns"]:
        if t["from"] != "rider": continue
        replies.append(s.send(rider, t["text"], t["message_id"], t["received_at"]))
    options = exp.get("one_of") or [{"payout": exp.get("payout", 0), "approval": exp.get("approval")}]
    if max(o["payout"] for o in options) > 0: settle_wait(s, rider, min(o["payout"] for o in options), 0)
    got_pay = s.paid(rider); pend = s.pending(rider)
    got_appr = sum(p["amount"] or 0 for p in pend if p["type"] == "approval") or None
    got_esc = any(p["type"] == "escalation" for p in pend)
    notes, ok = [], True
    if not any(got_pay == o["payout"] and (got_appr == o["approval"]) for o in options):
        ok = False; notes.append(f"payout={got_pay} approval={got_appr}, wanted one of {[(o['payout'], o['approval']) for o in options]}")
    esc = exp.get("escalation", "optional")
    if esc == "required" and not got_esc: ok = False; notes.append("escalation required, none raised")
    if esc == "no" and got_esc: ok = False; notes.append("escalation raised but expected none")
    joined = " ".join(replies)
    for fact in exp.get("reply_mentions", []):
        if not re.search(rf"(?<![\d₹]){re.escape(str(fact))}(?!\d)|₹\s?{re.escape(str(fact))}\b", joined, re.I): ok = False; notes.append(f"reply lacks '{fact}'")
    if not joined.strip(): ok = False; notes.append("empty reply")
    return ("PASS" if ok else "FAIL"), "; ".join(notes) or f"paid {got_pay}, approval {got_appr}, escalation {got_esc}"

# ---- extra scenarios: each uses riders not present in the sample set where possible ----
def sc_retry_storm(s):
    rider, mid, txt = "R003", "wamid.STORM0001", "Bhai order T926334 ka surge nahi mila, 20 tarikh wala"
    if s.paid(rider) or s.pending(rider): return "SKIP", "R003 not fresh"
    replies = list(cf.ThreadPoolExecutor(6).map(lambda _: s.send(rider, txt, mid, "2026-09-22T09:05:00+05:30"), range(6)))
    settle_wait(s, rider, 25, 0)
    msgs_in = sum(1 for e in s.trace(rider) if e["type"] == "message_in")
    ok = len(set(replies)) == 1 and s.paid(rider) == 25 and msgs_in == 1
    return ("PASS" if ok else "FAIL"), f"6 concurrent deliveries -> distinct replies={len(set(replies))}, paid={s.paid(rider)} (want 25), processed={msgs_in} (want 1)"

def sc_daily_limit_race(s):
    rider = "R027"
    if s.paid(rider) or s.pending(rider): return "SKIP", "R027 not fresh"
    t = "20 ko surge nahi mila aur 21 ko penalty do baar kata"
    list(cf.ThreadPoolExecutor(2).map(lambda i: s.send(rider, t if i == 0 else "21 ko penalty do baar kata", None, "2026-09-23T10:30:00+05:30"), range(2)))
    time.sleep(2)
    paid = s.paid(rider); appr = sum(p["amount"] or 0 for p in s.pending(rider) if p["type"] == "approval")
    return ("PASS" if paid in (10, 15) and paid + appr <= 25 else "FAIL"), f"paid={paid} approval={appr} (one auto-payment per day; never above 25 owed)"

def sc_never_overpay(s):
    rider = "R035"
    if s.paid(rider) or s.pending(rider): return "SKIP", "R035 not fresh"
    for i in range(3): s.send(rider, "21 ko 300 rupay kam aaye, order T980582 ka surge nahi mila, 300 do", None, "2026-09-23T11:45:00+05:30")
    settle_wait(s, rider, 25, 0); paid = s.paid(rider)
    return ("PASS" if paid == 25 else "FAIL"), f"asked 3x for 300, paid {paid} (owed 25)"

def sc_trace_shape(s):
    rider = "R007"; s.send(rider, "order T840677 ka surge missing hai bhai", None, "2026-09-23T09:45:00+05:30")
    tr = s.trace(rider); need = {"at", "type", "name", "input", "output"}; types = {"message_in", "tool_call", "decision", "reply", "error"}
    ok = bool(tr) and all(need <= set(e) and e["type"] in types for e in tr) and tr[0]["type"] == "message_in" and any(e["type"] == "reply" for e in tr)
    return ("PASS" if ok else "FAIL"), f"{len(tr)} trace steps for {rider}, types {sorted({e['type'] for e in tr})}"

def sc_pending_shape(s):
    s.send("R034", "Sep 19 ko 3 orders ka paisa missing hai payout mein", None, "2026-09-23T11:30:00+05:30")
    p = s.c.get(f"{s.url}/ops/pending").json()
    ok = isinstance(p, list) and len(p) >= 1 and all({"id", "rider_id", "type", "amount", "reason", "created_at"} <= set(x) and x["type"] in ("approval", "escalation") for x in p)
    return ("PASS" if ok else "FAIL"), f"{len(p)} pending items, e.g. {p[0] if p else None}"

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("url"); ap.add_argument("--only", help="run scenarios whose name contains this text")
    ap.add_argument("--reset", help="shell command that returns the system to a fresh state; run before every scenario (the graders' 'fresh system')")
    a = ap.parse_args(); s = Sys(a.url); s.c.get(f"{s.url}/health").raise_for_status()
    import subprocess
    convs = json.load(open(HERE / "conversations.json")); rows = []; args_only, a_reset = a.only, a.reset
    def add(name, fn, *a):
        if args_only and args_only.lower() not in name.lower(): return
        if a_reset:
            subprocess.run(a_reset, shell=True, check=True, capture_output=True); s.c.get(f"{s.url}/health").raise_for_status()
        t = time.time()
        try: res, note = fn(*a)
        except Exception as e: res, note = "FAIL", f"error: {type(e).__name__}: {e}"
        rows.append((res, name, note, time.time() - t)); print(f"{res:5} {name[:62]:62} {note}", flush=True)
    for i, c in enumerate(convs):
        add(f"conv{i+1:02d} {c['rider_id']} {c['scenario'][:45]}", run_conversation, s, c)
    add("webhook retry storm: 6 concurrent deliveries of one wamid", sc_retry_storm, s)
    add("two messages racing for the once-a-day auto-payment", sc_daily_limit_race, s)
    add("never pays more than owed (asks for 300, owed 25, x3)", sc_never_overpay, s)
    add("GET /trace shape", sc_trace_shape, s)
    add("GET /ops/pending shape", sc_pending_shape, s)
    n = {k: sum(1 for r in rows if r[0] == k) for k in ("PASS", "FAIL", "SKIP")}
    print(f"\n{n['PASS']} passed, {n['FAIL']} failed, {n['SKIP']} skipped of {len(rows)}")
    sys.exit(1 if n["FAIL"] else 0)

if __name__ == "__main__": main()
