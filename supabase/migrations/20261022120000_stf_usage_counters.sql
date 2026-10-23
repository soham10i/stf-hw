-- Daily usage counters shared by every instance of the API (services/api/usage.py): the caps
-- on paid model keys (questions, Gemini tokens and grounded searches, spoken answers) survive a
-- restart and are not multiplied by the number of Cloud Run instances.
create table if not exists public.usage_counters (
  day  date   not null,
  name text   not null,
  n    bigint not null default 0,
  primary key (day, name)
);

-- the API uses the service key; nobody else may read or write the counters
alter table public.usage_counters enable row level security;

-- an atomic increment that returns the new total (two instances adding at once both count)
create or replace function public.stf_usage_add(p_day date, p_name text, p_n bigint)
returns bigint
language sql
security invoker
set search_path = public
as $$
  insert into public.usage_counters as u (day, name, n)
  values (p_day, p_name, greatest(p_n, 0))
  on conflict (day, name) do update set n = u.n + excluded.n
  returning n;
$$;

revoke execute on function public.stf_usage_add(date, text, bigint) from public, anon, authenticated;
grant execute on function public.stf_usage_add(date, text, bigint) to service_role;
