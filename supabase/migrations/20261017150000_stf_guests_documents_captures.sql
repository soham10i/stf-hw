-- The STF live twin's database (docs/DATABASE.md, docs/CAPTURES.md): guests, their documents
-- (the copilot's sessions) and the inspection camera's photos, plus the photos' private bucket.
-- Only the API server reaches it, with the service key: row-level security is on and there are
-- no policies, and the browser roles get no privileges at all.

create table if not exists public.guests (
  id        text primary key check (id ~ '^[0-9a-f]{32}$'),
  created   double precision not null,
  last_seen double precision not null,
  visits    integer not null default 1
);
create index if not exists guests_last_seen on public.guests (last_seen);

create table if not exists public.documents (
  col   text not null,                       -- the collection: "copilot" for the chat's sessions
  owner text not null,                       -- the guest
  id    text not null,
  doc   jsonb not null,
  t     double precision not null,           -- last written
  primary key (col, owner, id)
);
create index if not exists documents_owner on public.documents (col, owner, t desc);

create table if not exists public.captures (
  id      text primary key check (id ~ '^[0-9a-f]{32}$'),
  t       double precision not null,
  flavour text not null check (flavour in ('chocolate', 'strawberry', 'vanilla')),
  n       integer not null default 0,
  source  text not null default 'twin',
  bytes   integer not null,
  w       integer not null,
  h       integer not null,
  owner   text not null default ''           -- the guest who took it
);
create index if not exists captures_t on public.captures (t desc);
create index if not exists captures_owner on public.captures (owner, t desc);

alter table public.guests enable row level security;
alter table public.documents enable row level security;
alter table public.captures enable row level security;
revoke all on public.guests, public.documents, public.captures from anon, authenticated;

-- the photos: a private bucket, JPEGs of at most 200 kB (captures.py MAX_BYTES)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('captures', 'captures', false, 200000, array['image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = 200000, allowed_mime_types = array['image/jpeg'];

-- the project's own helper that switches RLS on for every new table runs as an event trigger;
-- the API roles need not (and could not usefully) call it
do $$ begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end $$;
