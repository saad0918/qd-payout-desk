import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qd:qd@db:5432/qd")
PAYSWIFT_BASE_URL = os.getenv("PAYSWIFT_BASE_URL", "http://localhost:8081")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
# Any OpenAI-compatible endpoint (Groq, Gemini, ...). LLM_BACKEND=mock is for CI/tests only.
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_RETRY_SECONDS = float(os.getenv("LLM_RETRY_SECONDS", "40"))
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")
# Tried in order when the primary model has used up its DAILY token allowance (Groq quotas are per model). Empty = no fallback.
LLM_FALLBACK_MODELS = [m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", "openai/gpt-oss-20b").split(",") if m.strip()]
AGENT_BUDGET = float(os.getenv("AGENT_BUDGET", "40"))
