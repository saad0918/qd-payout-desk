# Rules for anyone (human or AI) editing this repo
1. The model never supplies a rider id or an amount. Money = `engine` findings -> `rules.decide` -> `settle` -> PaySwift. Keep it that way.
2. Every money rule has a unit test first (tests/). `pytest` must pass before pushing.
3. `/messages` dedupes on `message_id`, holds the per-rider lock, never returns 5xx.
4. "What was paid" comes from the PaySwift ledger (matched by `reference`), not only our DB.
5. PaySwift: same Idempotency-Key + same body on every retry; verify uncertain outcomes (504 still pays!) against the ledger.
6. Every decision is written to `trace_events` in the SUBMISSION.md shape.
7. Data quirks live in `app/data.py` (IST days, duplicate trips, metres, rider ids). Don't re-parse trips elsewhere.
