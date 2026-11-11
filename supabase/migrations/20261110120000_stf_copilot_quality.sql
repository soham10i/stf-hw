-- The copilot's answer quality: one row per answer (services/api/storage/quality.py).
-- Scores only - groundedness, citations, the hallucination policy's action, confidence, latency,
-- tokens and cost, keyed by the request id. No question, no answer, no guest id: a row cannot
-- say who asked or what. Written only by the API server (the service key); RLS is on with no
-- policies, so the anon/authenticated roles reach nothing.

create table if not exists public.copilot_quality (
  request_id text primary key,
  t timestamptz not null default now(),
  mode text,
  model text,
  engine text,
  cached boolean,
  rules boolean,
  claims integer,
  supported integer,
  unsupported integer,
  unsure integer,
  groundedness double precision,
  min_support double precision,
  citation_coverage double precision,
  cited_by_model double precision,
  citation_precision double precision,
  numbers_unverified integer,
  retrieval_verdict text,
  action text,
  declined boolean,
  regenerated boolean,
  confidence double precision,
  judge_calls integer,
  latency_ms integer,
  tokens integer,
  cost_usd double precision
);

create index if not exists copilot_quality_t on public.copilot_quality (t desc);

alter table public.copilot_quality enable row level security;
