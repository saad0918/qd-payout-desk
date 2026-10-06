# Submission logistics

- `docker compose up` starts your whole system: your service, Postgres and the `payswift` service already defined in `docker-compose.yml`. Keep the `payswift` service as it is.
- Your service listens on port **8000** and answers `GET /health` with 200 when it is ready.
- Your service reads the PaySwift URL from the environment variable `PAYSWIFT_BASE_URL`.
- `POST /messages` returns `{"reply": "..."}`. You may add fields; we only rely on `reply`.
- `GET /trace/{rider_id}` returns a JSON list of steps in order. Each step has at least:
  `at` (ISO time), `type` (`message_in`, `tool_call`, `decision`, `reply`, or `error`), `name`, `input`, `output`.
- `GET /ops/pending` returns a JSON list of items waiting for ops. Each item has at least:
  `id`, `rider_id`, `type` (`approval` or `escalation`), `amount` (rupees, for approvals), `reason`, `created_at`.
- Your eval command is one line in your README and takes the service URL as its argument, for example `python evals/run.py http://localhost:8000`.
- List every environment variable your service needs in `.env.example`. Don't commit `.env` or any key.
- `ai-logs/` holds the raw exports of the AI sessions you used, one file per session. Where to find them:
  Claude Code: `~/.claude/projects/<project>/<session>.jsonl` · Codex CLI: `~/.codex/sessions/<date>/rollout-*.jsonl` or `codex export` ·
  Cursor: chat menu (…) → Export Chat · GitHub Copilot in VS Code: Command Palette → "Chat: Export Chat…" ·
  Gemini CLI: `/export jsonl --output <file>` · Antigravity: the chat export, or the `antigravity-history` tool · ChatGPT: Settings → Data controls → Export.
  If your tool has no export, include whatever it does provide and say what it is.
- We use whatever is on `main` of the repo you link when the deadline passes.

## Output shapes

Only the shape is fixed. Step names, what goes in `input` and `output`, and how many steps there are depend entirely on how you design your agent.

`GET /trace/{rider_id}`

```json
[
  {"at": "<ISO time>", "type": "message_in", "name": "<name>", "input": {"message_id": "...", "text": "...", "received_at": "..."}, "output": null},
  {"at": "<ISO time>", "type": "tool_call",  "name": "<your tool>", "input": {"<argument>": "..."}, "output": {"<result>": "..."}},
  {"at": "<ISO time>", "type": "decision",   "name": "<what was decided>", "input": {"...": "..."}, "output": {"...": "..."}},
  {"at": "<ISO time>", "type": "reply",      "name": "<name>", "input": null, "output": "<text sent to the rider>"}
]
```

`GET /ops/pending`

```json
[
  {"id": "<id>", "rider_id": "<rider>", "type": "approval", "amount": 120, "reason": "<why it needs a human>", "created_at": "<ISO time>"},
  {"id": "<id>", "rider_id": "<rider>", "type": "escalation", "amount": null, "reason": "<why it needs a human>", "created_at": "<ISO time>"}
]
```
