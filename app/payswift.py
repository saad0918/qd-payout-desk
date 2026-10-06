"""PaySwift client, written for how the sandbox actually behaves (probed, not assumed):
- 504 gateway_timeout: the payout WAS recorded (ghost success). Never re-pay blindly: re-send the SAME Idempotency-Key
  (or find it in the ledger by reference).
- 503: not recorded. Safe to retry with the same key.
- some calls take ~8s even when they succeed.
- 429 account_blocked: global block, lifts after ~30s of silence; hammering extends it -> circuit breaker + throttle.
- 409: key reused with a different body (our bug) -> hard failure. 400: invalid -> hard failure.
"""
import threading, time, httpx
from dataclasses import dataclass
from datetime import datetime
from . import config

_lock = threading.Lock()
_last_post = 0.0
_blocked_until = 0.0
MIN_INTERVAL = 0.6        # <= ~1.6 payouts/s from this service
BLOCK_COOLDOWN = 35.0

@dataclass
class PayResult:
    status: str                 # paid | unknown | failed | blocked
    payout_id: str | None = None
    detail: str = ""

def _client(): return httpx.Client(base_url=config.PAYSWIFT_BASE_URL, timeout=httpx.Timeout(14.0, connect=4.0))

def is_blocked() -> bool: return time.monotonic() < _blocked_until

def list_payouts(rider_id: str, tries: int = 3) -> list[dict]:
    """Authoritative ledger for a rider. Raises if PaySwift cannot be read (callers must then not pay)."""
    last = None
    for i in range(tries):
        try:
            with _client() as c:
                r = c.get("/v1/payouts", params={"rider_id": rider_id})
            if r.status_code == 200: return r.json().get("data", [])
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = type(e).__name__
        time.sleep(0.4 * (i + 1))
    raise RuntimeError(f"PaySwift ledger unreadable: {last}")

def find_by_reference(rider_id: str, reference: str) -> dict | None:
    return next((p for p in list_payouts(rider_id) if p.get("reference") == reference), None)

def _throttle():
    global _last_post
    with _lock:
        wait = _last_post + MIN_INTERVAL - time.monotonic()
        if wait > 0: time.sleep(wait)
        _last_post = time.monotonic()

def pay(rider_id: str, amount: int, key: str, reference: str) -> PayResult:
    """At-most-once by construction: same key + same body every time, and every uncertain outcome is verified."""
    global _blocked_until
    if not (1 <= amount <= 10_000): return PayResult("failed", detail=f"amount {amount} outside PaySwift range")
    body = {"rider_id": rider_id, "amount": int(amount), "reference": reference}
    for attempt in range(4):
        if is_blocked(): return PayResult("blocked", detail="PaySwift rate-limit block active")
        _throttle()
        try:
            with _client() as c:
                r = c.post("/v1/payouts", headers={"Idempotency-Key": key}, json=body)
            code = r.status_code
            if code in (200, 201): return PayResult("paid", r.json().get("payout_id"))
            if code == 429: _blocked_until = time.monotonic() + BLOCK_COOLDOWN; return PayResult("blocked", detail="429 account_blocked")
            if code in (400, 409): return PayResult("failed", detail=f"{code} {r.text[:120]}")
            if code == 503: time.sleep(0.5 * (attempt + 1)); continue            # not recorded: retry same key
            uncertain = f"HTTP {code}"                                             # 504 & anything else: may have been recorded
        except Exception as e:
            uncertain = type(e).__name__                                           # timeout/connection: may have been recorded
        try:
            hit = find_by_reference(rider_id, reference)
            if hit: return PayResult("paid", hit.get("payout_id"), f"recovered after {uncertain}")
        except Exception:
            return PayResult("unknown", detail=f"{uncertain}; could not verify")
        time.sleep(0.5)
    return PayResult("unknown", detail="retries exhausted")

def created_day_ist(p: dict):
    from .data import IST
    return datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")).astimezone(IST).date()
