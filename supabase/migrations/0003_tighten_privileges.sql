-- CoinLens: remove database rights the app does not need.
--
-- Run this in the Supabase SQL editor after the other three files
-- (20260914000000, then 0001, then 0002). It is safe to run more than once.
-- If any line fails, nothing is changed.
-- Afterwards run supabase/verify.sql. Every check should say PASS.
--
-- Who the roles are:
--   anon           the app before anyone has signed in
--   authenticated  a signed-in user of the phone app
--   service_role   the Flask server
--
-- This file does not change what the app can read. Row level security
-- already limits that. It removes the right to write, which the app never
-- uses, and it limits who may call the leaderboard function.

begin;

-- The app never writes to these tables. Only the server does.
revoke insert, update, delete, truncate, references, trigger
  on table public.profiles, public.scans, public.api_usage
  from public, anon, authenticated;

-- The app never reads api_usage.
revoke select on table public.api_usage from public, anon, authenticated;

-- A signed-in user reads their own profile and their own scans.
grant select on table public.profiles, public.scans to authenticated;

-- The server. These are the same rights the earlier files give it.
grant select, insert, update, delete on table public.profiles, public.scans to service_role;
grant select, insert, update on table public.api_usage to service_role;

-- Only the server and signed-in users may call the leaderboard function.
revoke all on function public.leaderboard() from public, anon;
grant execute on function public.leaderboard() to authenticated, service_role;

commit;
