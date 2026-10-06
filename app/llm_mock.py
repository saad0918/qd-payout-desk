"""Rule-based stand-in for the LLM (LLM_BACKEND=mock). For CI and local plumbing tests ONLY: it proves the server side
(dedupe, limits, PaySwift handling, trace, ops queue) end to end without a model key. It is not the real agent and says
nothing about language understanding."""
import json, re
from datetime import date, timedelta

def _tc(i, name, args): return {"id": f"mock{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

def _days(text, today):
    out = []
    for m in re.finditer(r"(?<![\dT.])(\d{1,2})\s*(?:tarikh|tareekh|ko\b|wala|sept|sep|th\b)|sep(?:t)?\s*(\d{1,2})", text, re.I):
        d = int(m.group(1) or m.group(2))
        if 1 <= d <= 31: out.append(date(today.year, today.month, d).isoformat())
    if re.search(r"\bkal\b", text, re.I): out.append((today - timedelta(days=1)).isoformat())
    return list(dict.fromkeys(out))

def _kinds(text):
    k = set()
    if re.search(r"surge|distance|only|zyada|kam aaye", text, re.I) and not re.search(r"incentive", text, re.I): k.add("trip_underpaid")
    if re.search(r"penalty|cancel", text, re.I): k.add("penalty_duplicate")
    if re.search(r"incentive|\b12\b", text, re.I): k.add("incentive_missing")
    if re.search(r"nahi aaya|paisa|payment|missing", text, re.I) and not re.search(r"incentive", text, re.I): k.add("trip_unpaid")
    return k

def chat(messages, tools=None):
    sysmsg = messages[0]["content"]
    today = date.fromisoformat(re.search(r"Message date \(IST\): (\d{4}-\d{2}-\d{2})", sysmsg).group(1))
    last = max(i for i, m in enumerate(messages) if m["role"] == "user")
    users, text = [m["content"] for m in messages if m["role"] == "user"], messages[last]["content"]
    after = messages[last + 1:]
    called = [c["function"]["name"] for m in after if m["role"] == "assistant" for c in m.get("tool_calls", [])]
    results = [json.loads(m["content"]) for m in after if m["role"] == "tool"]
    allt = " ".join(users)
    days = _days(text, today) or _days(allt, today)
    trips = re.findall(r"\bT\d{6}\b", text, re.I) or re.findall(r"\bT\d{6}\b", allt, re.I)
    trips = [t.upper() for t in trips]
    if not called:
        if re.search(r"ignore (all )?(previous )?rules|\bSYSTEM:|this is R\d+|approve karo", text, re.I):
            return {"content": None, "tool_calls": [_tc(1, "escalate", {"reason": "possible manipulation or impersonation attempt"})]}
        if re.search(r"accident|hospital|emergency", text, re.I):
            return {"content": None, "tool_calls": [_tc(1, "check_account", {"trip_ids": trips} if trips else {"day": days[0]})]}
        if not days and not trips:
            return {"content": "Kaunse din ya kaunse order ka payout galat laga? Date ya order ID bata dijiye.", "tool_calls": None}
        calls = [_tc(i, "check_account", {"day": d}) for i, d in enumerate(days)] if not trips else [_tc(0, "check_account", {"trip_ids": trips})]
        return {"content": None, "tool_calls": calls}
    if called[-1] == "check_account" or all(n == "check_account" for n in called):
        if "submit_claim" not in called and "escalate" not in called:
            if re.search(r"accident|hospital|emergency", text, re.I) or (re.search(r"distance galat", text, re.I)):
                return {"content": None, "tool_calls": [_tc(9, "escalate", {"reason": "rider disputes a data point / safety situation; needs a human"})]}
            fs = []
            for r in results:
                fs += (r.get("day") or {}).get("findings", []) + [f for t in r.get("trips", []) for f in t.get("findings", [])]
            kinds = _kinds(allt)
            if not trips and kinds: fs = [f for f in fs if f["kind"] in kinds]
            ids = [f["id"] for f in fs if f["state"] == "open"]
            if ids: return {"content": None, "tool_calls": [_tc(2, "submit_claim", {"finding_ids": ids})]}
            return {"content": _explain(results, [f for f in fs]), "tool_calls": None}
    return {"content": _report(results), "tool_calls": None}

def _explain(results, fs):
    parts = []
    for r in results:
        for t in r.get("trips", []):
            if not t["found"]: parts.append(f"{t['trip_id']} aapke account pe nahi mila.")
            else: parts.append(f"{t['trip_id']}: {t['recorded_km']} km, surge {t['surge']} -> fare ₹{t['policy_amount']} banta hai, ₹{t['paid_total']} mila hai. Isme koi kami nahi hai.")
        d = r.get("day")
        if d and not d["findings"]:
            parts.append(f"{d['day']} ko aapke {d['completed']} trips complete hue. Incentive {d['incentive_threshold']} trips pe milta hai. Payout mein koi kami nahi mili.")
    return " ".join(parts) or "Humein is mein koi kami nahi mili."

def _report(results):
    parts = []
    for r in results:
        for x in r.get("results", []):
            o, amt = x.get("outcome"), x.get("amount")
            what = ", ".join(x.get("trip_ids") or []) or x.get("kind", "")
            if o == "paid": parts.append(f"{x['day']} ({what}): ₹{amt} kam mila tha, ₹{amt} PaySwift pe bhej diya gaya hai.")
            elif o == "payment_processing": parts.append(f"{what}: ₹{amt} ka payment process ho raha hai.")
            elif o == "awaiting_ops_approval": parts.append(f"{x['day']} ({what}): ₹{amt} ops team ke approval ke liye gaya hai, approve hote hi aa jayega.")
            elif o == "outside_dispute_window": parts.append(f"{x.get('trip_id') or ''} {x.get('day')} 7 din se purana hai, isliye ab dispute nahi ho sakta.")
            elif o in ("already_paid", "waiting_for_ops", "escalated", "rejected_by_ops"): parts.append(f"{x.get('trip_id') or x.get('finding_id')} ke liye status: {o}.")
            else: parts.append(f"Status: {o}.")
        if r.get("outcome") == "escalated_to_ops": parts.append("Hamari team ise check karegi aur aapse sampark karegi.")
    return " ".join(parts) or "Hamari team ise check karegi."
