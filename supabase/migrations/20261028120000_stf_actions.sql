-- Guarded actions (docs/architecture/guarded-action-plan.md, services/api/ledger.py): the
-- copilot's proposals, their at-most-once executions, and the signed audit chain. Everything
-- lives in the private schema `agent`, never in `public`: PostgREST serves `public`, and the
-- LangGraph checkpointer (phase 5, step 3) creates its own tables here without row-level
-- security. The API reaches this schema over a direct Postgres connection (SUPABASE_DB_URL).

create schema if not exists agent;

-- nobody but the API's own connection: on Supabase, revoke what the API roles get by default
do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on schema agent from %I', r);
      execute format('alter default privileges in schema agent revoke all on tables from %I', r);
    end if;
  end loop;
end $$;

-- one row per action the copilot proposed; its status only moves forward (ledger.TRANSITIONS)
create table if not exists agent.action_proposals (
  id            uuid primary key,
  thread_id     text not null unique,               -- the actuation graph's thread
  guest         text not null,                      -- salted hash of the guest who asked
  kind          text not null check (kind in ('order_submit', 'order_cancel')),
  params        jsonb not null,
  payload_hash  text not null check (length(payload_hash) = 64),
  reason        text not null default '',
  evidence      jsonb not null default '[]'::jsonb,
  precheck      jsonb not null default '[]'::jsonb,
  status        text not null check (status in (
                  'proposed', 'pending', 'approved', 'executing', 'done',
                  'refused', 'rejected', 'expired', 'unknown')),
  created_at    double precision not null,          -- unix seconds, as the API signs them
  expires_at    double precision not null,
  decided_by    text,
  decided_at    double precision,
  note          text,
  check (expires_at > created_at)
);
create index if not exists action_proposals_guest on agent.action_proposals (guest);
create index if not exists action_proposals_created on agent.action_proposals (created_at);

-- the at-most-once guard: written BEFORE the side effect, so a re-run that finds its row
-- reconciles instead of acting again
create table if not exists agent.action_executions (
  proposal_id  uuid primary key references agent.action_proposals (id) on delete cascade,
  state        text not null check (state in ('started', 'done', 'unknown', 'refused')),
  order_id     integer,
  result       jsonb,
  started_at   double precision not null,
  finished_at  double precision
);

-- the audit chain: each record is signed (HMAC-SHA256, STF_AUDIT_SECRET) over its fields and
-- the signature of the record before it, so an edited or removed record breaks the chain
create table if not exists agent.action_audit (
  seq       bigserial primary key,
  id        uuid not null unique,
  at        double precision not null,
  actor     text not null,
  action    text not null,
  params    jsonb not null,
  pre       text not null,
  post      text not null,
  status    text not null,
  reason    text,
  prev_sig  text not null,
  sig       text not null check (length(sig) = 64)
);
create index if not exists action_audit_action on agent.action_audit (action, seq);

-- append-only: no record changes, and none younger than 30 days goes (the API prunes past
-- STF_AUDIT_DAYS, default 365)
create or replace function agent.action_audit_append_only() returns trigger
language plpgsql
as $$
begin
  if tg_op = 'UPDATE' then
    raise exception 'agent.action_audit is append-only';
  end if;
  if old.at > extract(epoch from now()) - 30 * 86400 then
    raise exception 'agent.action_audit keeps every record for at least 30 days';
  end if;
  return old;
end $$;

drop trigger if exists action_audit_append_only on agent.action_audit;
create trigger action_audit_append_only
  before update or delete on agent.action_audit
  for each row execute function agent.action_audit_append_only();
