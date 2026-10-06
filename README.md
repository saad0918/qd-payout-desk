Without `--reset` the evals need a fresh system (`docker compose down && docker compose up -d --wait`); riders that already have payouts are SKIPped, never failed. Unit tests: `pip install -r requirements-dev.txt && pytest`. To inspect what the agent did for a rider: `python scripts/show_trace.py R003` or the ops page. `LLM_BACKEND=mock` swaps the model for a rule-based stand-in (CI only; it tests the plumbing, not language understanding). Model: Groq `openai/gpt-oss-120b`, any OpenAI-compatible provider via `LLM_BASE_URL` / `LLM_MODEL`.

## Design
`POST /messages` → per-rider Postgres lock → dedupe on `message_id` (vendor retries get the stored reply, nothing re-runs) → agent loop → persist → `{reply}`. Any agent/model failure returns a holding reply and escalates; the endpoint never 5xxs.

| Model decides | Code decides |
|---|---|
| Understand Hinglish/English, which day/order, what to ask, which tool next, reply wording | What the rider is owed (policy engine over trips vs payout lines), what was already paid (PaySwift ledger), the amount, auto-pay vs ops vs reject, the payment |

Tools: `check_account(day | trip_id | trip_ids)`, `submit_claim(finding_ids)`, `escalate(reason)`. No tool takes a rider id or an amount, so a rider cannot reach another account or set a figure. Code groups findings into one dispute per (kind, IST day), so the model cannot split a claim to dodge limits. Rules (`app/rules.py`): ≤ ₹200 and no auto-payment yet today → pay; otherwise an ops approval; a unique DB index backs the once-a-day rule. Ops approval re-derives the amount from the engine and PaySwift at click time. Every step is stored in `trace_events` (`/trace/{rider}`) and shown in the ops page, which also approves/rejects.

PaySwift (probed, not assumed): a `504` **still records the payout**, calls can take 8s, `503` records nothing, `429` blocks the whole account ~30s. So: a deterministic idempotency key per dispute, key and body never change, every uncertain outcome is checked against the PaySwift ledger by `reference` before retrying, a throttle + circuit breaker for 429, and a background reconciler for payments left pending.

Model failures handled: Groq rejects a malformed tool call with a 400 (agent tells the model and retries; error body kept in the trace); per-minute 429s are waited out; a used-up daily token quota switches to a fallback model (`LLM_FALLBACK_MODELS`).

Data traps handled: trips are UTC but policy days are IST (63 trips cross midnight); 10 duplicate trip rows (R009 has 11 trips, not 12); 222 distances stored in metres; rider ids `R7`/`r19`; 0.5 rounds up.

## Assumptions
7-day window = trip IST day within 7 days before the message's IST date (inclusive); "once per day" uses the server's IST day when paying; a claim ops rejected is not re-opened by the rider (it is escalated); ops decisions are not pushed to the rider (the brief has no outbound channel); overpayments are never clawed back or netted against shortfalls.

## Eval results
Real model (Groq `openai/gpt-oss-120b`), fresh system before every scenario: **29/29 passed** on 7 Oct 2026 (24 sample conversations, webhook-retry storm, two messages racing for the daily auto-payment, never-overpay, trace and pending response shapes). Output: `evals/real_model_report.txt`. This is one full run; a real model's wording varies slightly between runs. Earlier runs found and led to fixes for: malformed tool calls, daily token-quota exhaustion, and replies that omitted the order id. The stand-in model runs the same suite in CI; a concurrent run of all riders against the chaotic sandbox (`scripts/chaos_check.py`, stand-in model) ended with every ledger exact and no double or over-payment.
On a free Groq key (8,000 tokens/min, 200,000/day per model) a full run takes roughly 15-25 minutes and uses most of a day's allowance.

## Skipped
Auth on the ops page; notifying riders after an ops decision; load testing beyond the concurrency scenarios; clawback of overpayments. The prompt was tuned on the sample conversations, so hidden conversations may expose wording failures I have not seen.