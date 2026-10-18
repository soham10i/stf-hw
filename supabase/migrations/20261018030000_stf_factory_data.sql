-- The factory's data (docs/DATABASE.md): what the dashboard shows, as tables, and what the 3D twin
-- does, as it does it. Seeded from the simulations' outputs by services/api/db_seed.py
-- (`make db-seed`); the twin's guests add their own orders and inspections through the API.
-- Like the guests' tables: only the API server reaches them, with the service key - row-level
-- security on, no policies, no privileges for the browser roles.

-- the simulated month (stf-cad/hbw/month.py): one row per 12-cookie order, on the Upgrade 7 machine
create table if not exists public.orders (
  id        bigint generated always as identity primary key,
  source    text not null check (source in ('month', 'twin')),
  owner     text not null default '',          -- the guest whose twin baked it ('' for the month)
  t         timestamptz not null,
  day       integer,
  shift     integer,
  dur_s     real,                              -- the order's time, s
  flavour   text,                              -- the twin's order line
  qty       integer,                           -- the twin's order line
  baked     integer not null default 0,        -- cookies baked, the QC test's included
  good      integer not null default 0,
  scrap     integer not null default 0,
  qc_fault  text check (qc_fault in ('', 'burnt', 'underbaked', 'cracked')),
  returned  integer,
  hall_c    real
);
create index if not exists orders_t on public.orders (source, t);
create index if not exists orders_owner on public.orders (owner, t desc);

-- the month's faults, warnings, work orders, maintenance and failures
create table if not exists public.events (
  id      bigint generated always as identity primary key,
  t       timestamptz not null,
  kind    text not null,
  what    text not null,
  comp    text,
  code    text,
  lost_s  real,
  down_h  real
);
create index if not exists events_t on public.events (t);

-- condition monitoring (Upgrade 6): each wear part's signal, smoothed, health index and life left
create table if not exists public.sensor_readings (
  t            timestamptz not null,
  component    text not null,
  observed     real,
  ewma_r       real,
  health_index real,
  rul_shifts   real,
  primary key (component, t)
);

-- per order: the hall, the colour sensor's three readings, the crane's current, the compressor
create table if not exists public.signals (
  t                 timestamptz primary key,
  temp_c            real,
  a4_chocolate_mv   real,
  a4_strawberry_mv  real,
  a4_vanilla_mv     real,
  i_hbw_a           real,
  air_duty          real
);

-- the month day by day: orders, cookies, stops and OEE
create table if not exists public.daily_kpis (
  day       integer primary key,
  date      text not null,
  orders    integer, baked integer, good integer, scrap integer, run_h real,
  faults    integer, maint integer, failures integer,
  a real, p real, q real, oee real
);

-- the microgrid month (Upgrade 9), every 15 minutes
create table if not exists public.energy_15min (
  t_h             real primary key,
  load_w          real, pv_w real, grid_w real, battery_w real, soc real,
  price_eur_kwh   real, co2_g_kwh real, dr_event boolean, irradiance_w_m2 real
);

-- the bake as a process (Upgrade 19): one shift's cookies per way of ending a bake
create table if not exists public.bakes (
  id         bigint generated always as identity primary key,
  policy     text not null,
  n          integer not null,
  lot        integer, fridge boolean, thick_mm real, t0_c real, x0 real,
  bake_s     real, browning real, water_pct real, core_peak_c real,
  verdict    text not null check (verdict in ('ok', 'underbaked', 'burnt')),
  target     real
);

-- the camera's decisions: the ten sample photos, and every cookie a guest's twin photographs
create table if not exists public.inspections (
  id         bigint generated always as identity primary key,
  source     text not null check (source in ('sample', 'twin')),
  owner      text not null default '',
  t          timestamptz not null default now(),
  n          integer not null,
  flavour    text not null,
  truth      text not null check (truth in ('ok', 'burnt', 'underbaked', 'cracked')),
  condition  text,
  p          real,
  verdict    text not null check (verdict in ('pass', 'reject', 'check')),
  ae         real,
  unusual    boolean,
  capture_id text references public.captures (id) on delete set null
);
create index if not exists inspections_owner on public.inspections (owner, t desc);
create index if not exists inspections_capture on public.inspections (capture_id);

alter table public.orders enable row level security;
alter table public.events enable row level security;
alter table public.sensor_readings enable row level security;
alter table public.signals enable row level security;
alter table public.daily_kpis enable row level security;
alter table public.energy_15min enable row level security;
alter table public.bakes enable row level security;
alter table public.inspections enable row level security;
revoke all on public.orders, public.events, public.sensor_readings, public.signals, public.daily_kpis,
  public.energy_15min, public.bakes, public.inspections from anon, authenticated;
