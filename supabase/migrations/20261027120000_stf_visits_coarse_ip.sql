-- Visits keep the IP only shortened to its network, and no place (services/api/visits.py,
-- coarse_ip). This brings rows stored before that change into line: each address is cut to
-- its /24 (IPv4) or /48 (IPv6), the place columns the API no longer writes are dropped, and
-- anything older than the 90-day retention (STF_VISIT_DAYS) goes.

update public.visits
set ip = host(network(set_masklen(ip::inet, case when family(ip::inet) = 4 then 24 else 48 end)))
where ip ~ '^[0-9a-fA-F:.]+$' and ip <> 'local';

update public.visits set ip = null where ip is not null and ip !~ '^[0-9a-fA-F:.]+$' and ip <> 'local';

alter table public.visits
  drop column if exists country,
  drop column if exists region,
  drop column if exists city,
  drop column if exists lat,
  drop column if exists lon;

delete from public.visits where t < now() - interval '90 days';
delete from public.app_logs where t < now() - interval '90 days';
