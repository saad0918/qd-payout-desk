`riders.csv`: rider_id, name, city, joined_on

`trips.csv`: trip_id, rider_id, started_at, status, distance_km, surge_multiplier. Status is `completed`, `cancelled_by_customer` or `cancelled_by_rider`. Exported from the trips system, 12 to 21 Sep 2026.

`payout_lines.csv`: line_id, payout_date, rider_id, line_type, trip_id, amount. What riders were actually paid. Line type is `trip`, `daily_incentive` or `cancellation_penalty`; penalties are negative.

`conversations.json`: sample conversations, from one message to several. Rider turns are what the vendor sends; agent turns, where shown, are an example of a good reply, not required wording. `expected` is how the conversation should end.

`expected` means:
- `payout`: rupees that should reach the rider in PaySwift because of this message or conversation (0 if none)
- `approval`: rupees that should be waiting for ops approval, or null
- `escalation`: `required`, `optional` or `no`
- `reply_mentions` (conversations only): facts the rider should be told
- `one_of` (conversations only): any one of the listed end states is acceptable

Run each conversation against a fresh system.
