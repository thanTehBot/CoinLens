-- Fixes: "permission denied for table api_usage" (42501) seen in production
-- when the daily-quota check ran on a real scan.
--
-- Root cause: public.api_usage (added in 0001) was created via raw SQL in
-- the SQL editor, not Supabase's Studio table editor, so it never got the
-- automatic grant Studio applies for new tables. RLS bypass and base table
-- privileges are two separate permission layers - service_role bypasses RLS
-- policies, but still needs an explicit GRANT to touch the table at all.
--
-- Idempotent: safe to run multiple times. This is also folded into
-- 0001_api_usage_and_leaderboard.sql for anyone bootstrapping a fresh
-- project from scratch; run this file directly if 0001 was already applied.

grant select, insert, update on public.api_usage to service_role;
