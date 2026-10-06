create table if not exists messages(
  message_id text primary key, rider_id text not null, text text not null,
  received_at text, reply text, created_at timestamptz default now());
create index if not exists messages_rider on messages(rider_id, created_at);

create table if not exists trace_events(
  id bigserial primary key, rider_id text not null, message_id text,
  at timestamptz default now(), type text not null, name text not null, input jsonb, output jsonb);
create index if not exists trace_rider on trace_events(rider_id, id);

-- one row per (kind, IST day) group of findings; key = hash(rider + finding ids) makes re-claims idempotent
create table if not exists disputes(
  id serial primary key, key text unique not null, rider_id text not null, kind text not null, day text not null,
  finding_ids text[] not null, amount int not null,
  status text not null,   -- pending_payment | paid | awaiting_approval | rejected | escalated
  reason text, message_id text, created_at timestamptz default now(), updated_at timestamptz default now());
create index if not exists disputes_rider on disputes(rider_id);

create table if not exists payouts(
  id serial primary key, dispute_id int references disputes(id), rider_id text not null, amount int not null,
  idempotency_key text unique not null, reference text not null, status text not null,  -- pending | paid | failed
  auto boolean not null, pay_day date not null, payout_id text, detail text,
  created_at timestamptz default now(), updated_at timestamptz default now());
-- DB-level guard for "once per rider per day": at most one live auto-payout per rider per IST day
create unique index if not exists one_auto_per_rider_day on payouts(rider_id, pay_day) where auto and status in ('pending','paid');

create table if not exists approvals(
  id serial primary key, rider_id text not null, dispute_id int references disputes(id),
  type text not null,      -- approval | escalation
  amount int, reason text not null, status text not null default 'open',  -- open | approved | rejected | resolved
  decided_by text, decided_at timestamptz, message_id text, created_at timestamptz default now());
