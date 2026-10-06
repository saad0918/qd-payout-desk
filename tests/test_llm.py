import pytest
from app import llm, config, tools

class R:
    def __init__(self, code, body=None, headers=None, text=""): self.status_code, self._b, self.headers, self.text = code, body or {}, headers or {}, text
    def json(self): return self._b

OK = R(200, {"choices": [{"message": {"role": "assistant", "content": "hi", "reasoning": "ignored"}}]})
TPD = R(429, text='{"error":{"message":"Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199000","code":"rate_limit_exceeded"}}')
TPM = R(429, headers={"retry-after": "1"}, text='{"error":{"message":"Rate limit reached ... on tokens per minute (TPM)"}}')

@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "openai"); monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "LLM_MODEL", "big"); monkeypatch.setattr(config, "LLM_FALLBACK_MODELS", [])

def test_per_minute_429_is_waited_out_then_succeeds(monkeypatch):
    seq = [TPM, R(503), OK]; monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: seq.pop(0))
    assert llm.chat([{"role": "user", "content": "x"}])["content"] == "hi" and not seq

def test_hard_error_keeps_the_body_for_the_trace(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: R(400, text='{"error":{"code":"tool_use_failed"}}'))
    with pytest.raises(llm.LLMError) as e: llm.chat([{"role": "user", "content": "x"}])
    assert e.value.status == 400 and "tool_use_failed" in e.value.body

def test_daily_quota_switches_to_fallback_model_without_waiting(monkeypatch):
    used = []
    def post(url, json=None, **k): used.append(json["model"]); return TPD if json["model"] == "big" else OK
    monkeypatch.setattr(llm.httpx, "post", post); monkeypatch.setattr(config, "LLM_FALLBACK_MODELS", ["small"])
    assert llm.chat([])["content"] == "hi" and used == ["big", "small"]

def test_daily_quota_without_fallback_raises_immediately(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: (calls.append(1), TPD)[1])
    with pytest.raises(llm.LLMError) as e: llm.chat([])
    assert e.value.status == 429 and len(calls) == 1          # no 40-second retry loop for a daily limit

def test_all_models_out_of_quota_raises(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: TPD); monkeypatch.setattr(config, "LLM_FALLBACK_MODELS", ["small"])
    with pytest.raises(llm.LLMError): llm.chat([])

def test_reasoning_effort_only_sent_when_set(monkeypatch):
    sent = {}
    monkeypatch.setattr(llm.httpx, "post", lambda url, json=None, **k: (sent.update(json), OK)[1])
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", ""); llm.chat([]); assert "reasoning_effort" not in sent
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "low"); llm.chat([]); assert sent["reasoning_effort"] == "low"

@pytest.mark.parametrize("raw,exp", [("T840677", ["T840677"]), ("T1, T2", ["T1", "T2"]), (["T1"], ["T1"]), (None, []), ("", [])])
def test_tool_arguments_are_forgiving_about_string_vs_list(raw, exp):
    assert tools._as_list(raw) == exp
