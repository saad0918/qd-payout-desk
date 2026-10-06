"""The only place that decides whether money moves automatically. Pure; unit-tested.
Finance: auto-pay up to Rs 200 per dispute, once per rider per day; bigger or repeat -> ops approval;
never pay more than owed (the amount always comes from engine findings, never from the rider or the LLM)."""
from dataclasses import dataclass

AUTO_LIMIT = 200
PAYSWIFT_MAX = 10_000       # one PaySwift call accepts 1..10000 rupees

@dataclass(frozen=True)
class Decision:
    action: str     # pay | approval
    reason: str

def decide(amount: int, auto_used_today: bool) -> Decision:
    if amount <= 0:
        raise ValueError("nothing to pay")            # callers must never ask to pay zero/negative
    if amount > AUTO_LIMIT:
        return Decision("approval", f"₹{amount} is above the ₹{AUTO_LIMIT} auto-pay limit")
    if auto_used_today:
        return Decision("approval", "rider already received an auto-payment today (limit: one per day)")
    return Decision("pay", f"₹{amount} is within the ₹{AUTO_LIMIT} auto-pay limit")
