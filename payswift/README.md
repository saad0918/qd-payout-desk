# PaySwift Payouts API (sandbox)

Runs with `docker compose up payswift` on port 8081. The ledger is in memory and is cleared on restart.

```
POST /v1/payouts
Content-Type: application/json
Idempotency-Key: <optional>

{ "rider_id": "R017", "amount": 120, "reference": "free text" }
```

`amount` is whole rupees, 1 to 10000. Returns `201` with `payout_id` and `status`. Other codes you may see: 400, 409, 429, 5xx.

```
GET /v1/payouts?rider_id=R017     list payouts (rider_id optional)
GET /health
```

Rate limits apply.
