"""PaySwift client against the failure modes observed in the sandbox."""
import httpx, pytest
from app import payswift

class Fake:
    def __init__(self, script, ledger=None): self.script, self.calls, self.ledger = list(script), [], ledger or []
    def __call__(self, request):
        if request.method == "GET": return httpx.Response(200, json={"data": self.ledger})
        self.calls.append(request.headers.get("Idempotency-Key"))
        a = self.script.pop(0)
        if isinstance(a, Exception): raise a
        if a == 201: return httpx.Response(201, json={"payout_id": "pout_1"})
        return httpx.Response(a, json={"error": str(a)})

@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(payswift, "MIN_INTERVAL", 0); monkeypatch.setattr(payswift.time, "sleep", lambda s: None)
    payswift._blocked_until = 0.0

def use(monkeypatch, fake):
    monkeypatch.setattr(payswift, "_client", lambda: httpx.Client(base_url="http://x", transport=httpx.MockTransport(fake)))

def test_success(monkeypatch):
    f = Fake([201]); use(monkeypatch, f); assert payswift.pay("R1", 25, "k", "ref").status == "paid"

def test_503_is_retried_with_same_key(monkeypatch):
    f = Fake([503, 503, 201]); use(monkeypatch, f); r = payswift.pay("R1", 25, "k", "ref")
    assert r.status == "paid" and f.calls == ["k", "k", "k"]

def test_504_that_actually_paid_is_recovered_not_repaid(monkeypatch):
    f = Fake([504], ledger=[{"reference": "ref", "payout_id": "pout_9"}]); use(monkeypatch, f)
    r = payswift.pay("R1", 25, "k", "ref"); assert r.status == "paid" and r.payout_id == "pout_9" and len(f.calls) == 1

def test_504_not_in_ledger_retries_same_key(monkeypatch):
    f = Fake([504, 201]); use(monkeypatch, f); r = payswift.pay("R1", 25, "k", "ref")
    assert r.status == "paid" and f.calls == ["k", "k"]

def test_timeout_is_treated_as_uncertain(monkeypatch):
    f = Fake([httpx.ReadTimeout("slow"), 201]); use(monkeypatch, f); assert payswift.pay("R1", 25, "k", "ref").status == "paid"

def test_429_opens_circuit_and_stops_sending(monkeypatch):
    f = Fake([429, 201]); use(monkeypatch, f)
    assert payswift.pay("R1", 25, "k", "ref").status == "blocked"
    assert payswift.pay("R2", 25, "k2", "ref2").status == "blocked" and len(f.calls) == 1   # second call never hits PaySwift

@pytest.mark.parametrize("code", [400, 409])
def test_hard_errors_are_not_retried(monkeypatch, code):
    f = Fake([code, 201]); use(monkeypatch, f); assert payswift.pay("R1", 25, "k", "ref").status == "failed" and len(f.calls) == 1

@pytest.mark.parametrize("amt", [0, -3, 10001])
def test_amount_outside_payswift_range_never_sent(monkeypatch, amt):
    f = Fake([201]); use(monkeypatch, f); assert payswift.pay("R1", amt, "k", "ref").status == "failed" and not f.calls
