-- Usage traction (consent-gated) and shipped application logs.
-- Nothing here is personal: a visit row is the anonymous guest session id, the page, the time,
-- the IP and its coarse place (country/region/city/coordinates). No name, no email, no
-- fingerprint. A visitor who declines the banner is not tracked at all - the API stores no row.
-- Rows are written only by the API server (the service key); RLS is on with no policies, so the
-- anon/authenticated roles reach nothing.

create table if not exists public.visits (
  id bigint generated always as identity primary key,
  guest text not null,
  t timestamptz not null default now(),
  page text not null,
  ip text,
  country text,
  region text,
  city text,
  lat double precision,
  lon double precision,
  ua text
);

create index if not exists visits_guest_t on public.visits (guest, t desc);
create index if not exists visits_t on public.visits (t desc);

alter table public.visits enable row level security;

create table if not exists public.app_logs (
  id bigint generated always as identity primary key,
  t timestamptz not null default now(),
  level text not null,
  logger text not null,
  message text not null
);

create index if not exists app_logs_t on public.app_logs (t desc);

alter table public.app_logs enable row level security;
