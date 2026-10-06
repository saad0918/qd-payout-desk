import time, httpx
from . import config

class LLMError(RuntimeError):
    """Non-retryable model API error; keeps the response body so traces show WHY (e.g. Groq tool_use_failed)."""
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}"); self.status, self.body = status, body

def daily_limit_hit(status: int, text: str) -> bool:
    """429 caused by the per-DAY allowance (waiting a few seconds will not help; switch model instead)."""
    return status == 429 and any(k in text for k in ("(TPD)", "(RPD)", "per day"))

def _call(model, messages, tools, timeout):
    body = {"model": model, "messages": messages, "temperature": 0}
    if tools: body["tools"] = [{"type": "function", "function": t} for t in tools]
    if config.LLM_REASONING_EFFORT: body["reasoning_effort"] = config.LLM_REASONING_EFFORT   # gpt-oss on Groq: low|medium|high
    end = time.monotonic() + config.LLM_RETRY_SECONDS
    while True:
        r = httpx.post(f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions", json=body,
                       headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, timeout=timeout or config.LLM_TIMEOUT)
        if r.status_code in (429, 500, 502, 503) and time.monotonic() < end and not daily_limit_hit(r.status_code, r.text):
            try: wait = float(r.headers.get("retry-after", 3))
            except ValueError: wait = 3.0
            time.sleep(min(max(wait, 0.5), 15)); continue         # per-minute limits and blips: wait and retry
        if r.status_code >= 400: raise LLMError(r.status_code, r.text)
        return r.json()["choices"][0]["message"]

def chat(messages, tools=None, timeout=None):
    """One OpenAI-compatible chat completion. Per-minute 429/5xx: back off and retry. Daily-quota 429: try the next fallback model."""
    if config.LLM_BACKEND == "mock":
        from . import llm_mock
        return llm_mock.chat(messages, tools)
    last = None
    for model in [config.LLM_MODEL] + list(config.LLM_FALLBACK_MODELS):
        try: return _call(model, messages, tools, timeout)
        except LLMError as e:
            if not daily_limit_hit(e.status, e.body): raise
            last = e
    raise last
