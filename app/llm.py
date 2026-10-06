import httpx
from . import config

def chat(messages, tools=None, timeout=None):
    """One OpenAI-compatible chat completion (Groq, Gemini and Anthropic all expose this). Returns the assistant message dict."""
    if config.LLM_BACKEND == "mock":
        from . import llm_mock
        return llm_mock.chat(messages, tools)
    body = {"model": config.LLM_MODEL, "messages": messages, "temperature": 0}
    if tools: body["tools"] = [{"type": "function", "function": t} for t in tools]
    r = httpx.post(f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions", json=body,
                   headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, timeout=timeout or config.LLM_TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]
