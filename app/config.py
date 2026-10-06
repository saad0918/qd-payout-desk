import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qd:qd@db:5432/qd")
PAYSWIFT_BASE_URL = os.getenv("PAYSWIFT_BASE_URL", "http://localhost:8081")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
# Any OpenAI-compatible endpoint (Groq, Gemini, Anthropic compat). LLM_BACKEND=mock is for CI/tests only.
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "12"))
AGENT_BUDGET = float(os.getenv("AGENT_BUDGET", "40"))   # soft cap for one message; vendor retries are safe (deduped)
