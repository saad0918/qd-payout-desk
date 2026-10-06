# QuickDrop Rider Payout Dispute Desk

## Run
```
cp .env.example .env                     # set LLM_API_KEY (Groq or Gemini free tier; Anthropic works too, see file)
docker compose up --build                # app :8000 (ops page at /), PaySwift sandbox :8081, Postgres
python evals/run.py http://localhost:8000 --reset "python scripts/reset_compose.py"
```
Without `--reset` the evals need a fresh system (`docker compose down -v && up`); non-fresh riders are SKIPped, never failed. Unit tests: `pip install -r requirements-dev.txt && pytest`. `LLM_BACKEND=mock` swaps the model for a rule-based stand-in (CI only; it tests the plumbing, not language understanding).

## Design
`POST /messages` → per-rider Postgres lock → dedupe on `message_id` (vendor retries get the stored reply, nothing re-runs) → agent loop → persist → `{reply}`. Any agent/model failure returns a holding reply and escalates; the endpoint never 5xxs.

| Model decides | Code decides |
|---|---|
| Understand Hinglish/English, which day/order, what to ask, which tool next, reply wording | What the rider is owed (policy engine over trips vs payout lines), what was already paid (PaySwift ledger), the amount, auto-pay vs ops vs reject, the payment |

Tools: `check_account(day | trip_ids)`, `submit_claim(finding_ids)`, `escalate(reason)`. There is no rider-id or amount parameter anywhere, so a rider cannot reach another account or set a figure. `submit_claim` groups findings into one dispute per (kind, IST day) in code, so the model cannot split a claim to dodge limits. Rules (`app/rules.py`): ≤ ₹200 and no auto-payment yet today → pay; otherwise an ops approval. Ops approval re-derives the amount from the engine and PaySwift at click time. Every step is in `trace_events` (`/trace/{rider}`), visible with approve/reject in the ops page.

PaySwift (probed, not assumed): a `504` **still records the payout**, calls can take 8s, `503` records nothing, `429` blocks the whole account ~30s. So: deterministic idempotency key per dispute, key + body never change, every uncertain outcome is checked against the PaySwift ledger by `reference` before retrying, a throttle + circuit breaker for 429, and a background reconciler for payments left pending.

Data traps handled: trips are UTC but policy days are IST (63 trips cross midnight); 10 duplicate trip rows (R009 has 11 trips, not 12); 222 distances in metres; rider ids `R7`/`r19`; 0.5 rounds up.

## Assumptions
7-day window = trip IST day within 7 days before the message's IST date (inclusive); "once per day" uses the server's IST day when paying; a claim ops rejected is not re-opened by the rider (escalate instead); ops decisions are not pushed to the rider (no outbound channel in the brief); overpayments are never clawed back or netted against shortfalls.

## Eval results
29/29 pass (24 sample conversations, retry storm, daily-limit race, never-overpay, trace + pending shapes) on a fresh system per scenario, **with `LLM_BACKEND=mock`**. A concurrent run of all riders against the chaotic sandbox ended with every ledger exact, no double or over-payment (`scripts/chaos_check.py`). **Not yet run with a real model**; run the command above with your key and read the failures.

## Skipped
Auth on the ops page; replies to riders after an ops decision; multi-process load testing; model-quality tuning of the prompt; clawback of overpayments.
