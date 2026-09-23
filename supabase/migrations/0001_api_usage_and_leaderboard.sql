-- CoinLens prototype: API cost-protection accounting + leaderboard RPC.
-- Idempotent: safe to run multiple times.
--
-- Context: public.scans, RLS on scans, and profiles already exist and are left
-- untouched. This migration only adds:
--   1. public.api_usage - server-only accounting of AI attempts (for M6 quota)
--   2. public.leaderboard() - redefined with a superset return signature. The
--      function already existed and IS already callable by `authenticated`
--      (confirmed live), but its current columns don't include `user_id`,
--      which the Expo leaderboard needs to know which row is "me" without
--      matching on display_name. CREATE OR REPLACE cannot change a function's
--      return type, so this drops it first, then recreates it security
--      definer (safe: it only ever returns aggregates, never raw scan rows).

create table if not exists public.api_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  endpoint text not null,
  status text not null check (status in ('attempted', 'identified', 'uncertain', 'error')),
  scan_id uuid references public.scans (id) on delete set null
);

create index if not exists api_usage_user_created_idx
  on public.api_usage using btree (user_id, created_at desc);

-- Server-only table: accessed exclusively by Flask via the service-role key,
-- which bypasses RLS. RLS is still enabled with no policies so that even a
-- leaked anon/authenticated key can never read or write usage rows directly.
alter table public.api_usage enable row level security;

-- RLS bypass and base table privileges are two separate permission layers:
-- service_role bypasses RLS policies, but still needs an explicit GRANT to
-- touch the table at all. Supabase's Studio table editor applies this
-- automatically for tables created through it; a table created via raw SQL
-- (like this one) does not get it for free, which is exactly what caused
-- "permission denied for table api_usage" (42501) in production.
grant select, insert, update on public.api_usage to service_role;

-- Safe aggregate-only leaderboard: exposes counts/sums per user, never raw
-- scan rows, so it can be granted to any signed-in user without leaking
-- other users' scan history.
begin;
drop function if exists public.leaderboard();

create function public.leaderboard()
returns table (
  user_id uuid,
  display_name text,
  scan_count bigint,
  total_value numeric,
  avg_value numeric,
  member_since timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
  select
    p.id as user_id,
    coalesce(p.display_name, 'Member') as display_name,
    count(s.id) as scan_count,
    coalesce(sum(s.estimated_value), 0)::numeric as total_value,
    case when count(s.id) > 0
      then round(coalesce(sum(s.estimated_value), 0) / count(s.id), 2)
      else 0
    end as avg_value,
    p.created_at as member_since
  from public.profiles p
  left join public.scans s on s.user_id = p.id
  group by p.id, p.display_name, p.created_at;
$$;

grant execute on function public.leaderboard() to authenticated;

commit;