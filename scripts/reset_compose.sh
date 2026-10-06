#!/usr/bin/env bash
# Returns the compose stack to a fresh state: wipes our tables and restarts the in-memory PaySwift ledger.
set -e
cd "$(dirname "$0")/.."
docker compose exec -T db psql -U qd -d qd -c "truncate messages, trace_events, approvals, payouts, disputes restart identity cascade" >/dev/null
docker compose restart payswift >/dev/null
for i in $(seq 1 30); do curl -sf localhost:8081/health >/dev/null && exit 0; sleep 0.5; done
echo "payswift did not come back" >&2; exit 1
