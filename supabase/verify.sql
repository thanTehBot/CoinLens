-- CoinLens: check a Supabase project against what the app expects.
--
-- Paste this whole file into the Supabase SQL editor and run it.
-- It only reads. It changes nothing. It is one query, so the editor shows
-- every check in one table.
--
--   PASS  good
--   FAIL  fix now (see docs/SUPABASE.md, "Fixing a failed check")
--   WARN  not a problem today, but fix it (same section)
--   INFO  for you to read (the last two rows)
--
-- If it stops with "relation ... does not exist", the files in
-- supabase/migrations have not all been run on this project.
--
-- Check 3 looks for auth.uid() in each read policy. It cannot judge every
-- possible policy, so read the policy text it shows in the details column.

with
tables(name) as (values ('profiles'), ('scans'), ('api_usage')),
tbl as (
  select name, to_regclass('public.' || name) as rel from tables
),
-- Policies that apply to the app. Policies written only for the server role
-- are ignored, because that role bypasses row level security anyway.
pol as (
  select tablename, policyname, cmd, coalesce(qual, '') as qual
  from pg_policies
  where schemaname = 'public'
    and tablename in (select name from tables)
    and roles && array['public', 'anon', 'authenticated']::name[]
),
priv as (
  select
    name,
    has_table_privilege('anon', rel, 'SELECT') as anon_read,
    has_table_privilege('anon', rel, 'INSERT, UPDATE, DELETE, TRUNCATE') as anon_write,
    has_table_privilege('authenticated', rel, 'SELECT') as auth_read,
    has_table_privilege('authenticated', rel, 'INSERT, UPDATE, DELETE, TRUNCATE') as auth_write,
    has_table_privilege('service_role', rel, 'SELECT')
      and has_table_privilege('service_role', rel, 'INSERT')
      and has_table_privilege('service_role', rel, 'UPDATE') as server_rw,
    has_table_privilege('service_role', rel, 'DELETE') as server_delete
  from tbl
  where rel is not null
),
-- Every link between these tables, and from profiles to auth.users.
fk as (
  select c.conname,
         c.conrelid::regclass::text as child,
         c.conrelid, c.confrelid, c.confdeltype
  from pg_constraint c
  where c.contype = 'f'
    and c.conrelid in (select rel from tbl where rel is not null)
    and c.confrelid in (to_regclass('auth.users'), to_regclass('public.profiles'), to_regclass('public.scans'))
),
links as (
  select
    exists (select 1 from fk where confdeltype = 'c'
            and conrelid = to_regclass('public.profiles') and confrelid = to_regclass('auth.users')) as profiles_users,
    exists (select 1 from fk where confdeltype = 'c'
            and conrelid = to_regclass('public.scans') and confrelid = to_regclass('public.profiles')) as scans_profiles,
    exists (select 1 from fk where confdeltype = 'c'
            and conrelid = to_regclass('public.api_usage') and confrelid = to_regclass('public.profiles')) as usage_profiles,
    exists (select 1 from fk where confdeltype = 'n'
            and conrelid = to_regclass('public.api_usage') and confrelid = to_regclass('public.scans')) as usage_scans,
    (select string_agg(child || '.' || conname, ', ' order by child, conname)
     from fk where confdeltype in ('a', 'r')) as blocking
),
lb as (
  select p.oid, p.prosecdef, coalesce('user_id' = any (p.proargnames), false) as has_user_id
  from pg_proc p
  where p.oid = to_regprocedure('public.leaderboard()')
),
checks(n, check_name, result, details) as (

  select 1, 'The three tables exist',
    case when count(*) filter (where rel is null) = 0 then 'PASS' else 'FAIL' end,
    coalesce('Missing: ' || string_agg(name, ', ') filter (where rel is null), 'profiles, scans, api_usage')
  from tbl

  union all
  select 2, 'Row level security is on for all three',
    case when count(*) filter (where not coalesce(c.relrowsecurity, false)) = 0 then 'PASS' else 'FAIL' end,
    coalesce('Off for: ' || string_agg(t.name, ', ') filter (where not coalesce(c.relrowsecurity, false)), 'On')
  from tbl t left join pg_class c on c.oid = t.rel

  union all
  select 3, 'Signed-in users can read only their own profile and scans',
    case
      when (select count(distinct tablename) from pol
            where cmd in ('SELECT', 'ALL') and tablename in ('profiles', 'scans')) < 2 then 'FAIL'
      when exists (select 1 from pol
                   where cmd in ('SELECT', 'ALL') and qual not like '%auth.uid()%') then 'FAIL'
      when exists (select 1 from priv
                   where name in ('profiles', 'scans') and not auth_read) then 'FAIL'
      else 'PASS'
    end,
    case
      when (select count(distinct tablename) from pol
            where cmd in ('SELECT', 'ALL') and tablename in ('profiles', 'scans')) < 2
        then 'A read policy is missing. Found: '
      when exists (select 1 from pol
                   where cmd in ('SELECT', 'ALL') and qual not like '%auth.uid()%')
        then 'A read policy does not use auth.uid(). Found: '
      when exists (select 1 from priv
                   where name in ('profiles', 'scans') and not auth_read)
        then 'Signed-in users have no read right. Run 0003. Policies: '
      else ''
    end
    || coalesce((select string_agg(tablename || ': ' || policyname || ' ' || qual, '; ' order by tablename, policyname)
                 from pol where cmd in ('SELECT', 'ALL')), 'none')

  union all
  select 4, 'No policy lets the app write',
    case when count(*) = 0 then 'PASS'
         when bool_or(pr.auth_write or pr.anon_write) then 'FAIL'
         else 'WARN' end,
    coalesce('Drop these, only the server writes: '
             || string_agg(p.tablename || ': ' || p.policyname || ' (' || p.cmd || ')', '; ' order by p.tablename, p.policyname),
             'None')
  from pol p join priv pr on pr.name = p.tablename
  where p.cmd <> 'SELECT'

  union all
  select 5, 'api_usage has no policies for the app',
    case when count(*) = 0 then 'PASS' else 'WARN' end,
    coalesce('Drop: ' || string_agg(policyname, ', '), 'None')
  from pol where tablename = 'api_usage'

  union all
  select 6, 'Before sign-in, the app has no write rights and cannot see api_usage',
    case when coalesce(bool_or(anon_write or (name = 'api_usage' and anon_read)), false) then 'WARN' else 'PASS' end,
    coalesce('anon has extra rights on: '
             || string_agg(name, ', ') filter (where anon_write or (name = 'api_usage' and anon_read))
             || '. Row level security is what blocks them. Run 0003.', 'OK')
  from priv

  union all
  select 7, 'Signed-in users have no write rights and cannot see api_usage',
    case when coalesce(bool_or(auth_write or (name = 'api_usage' and auth_read)), false) then 'WARN' else 'PASS' end,
    coalesce('authenticated has extra rights on: '
             || string_agg(name, ', ') filter (where auth_write or (name = 'api_usage' and auth_read))
             || '. Row level security is what blocks them. Run 0003.', 'OK')
  from priv

  union all
  select 8, 'The server role can read and write all three',
    case when coalesce(bool_and(server_rw and (name = 'api_usage' or server_delete)), false) then 'PASS' else 'FAIL' end,
    coalesce('service_role is missing rights on: '
             || string_agg(name, ', ') filter (where not (server_rw and (name = 'api_usage' or server_delete)))
             || '. Run 0003.', 'OK')
  from priv

  union all
  select 9, 'leaderboard() exists and returns user_id',
    case when (select count(*) from lb where prosecdef and has_user_id) = 1 then 'PASS' else 'FAIL' end,
    case
      when not exists (select 1 from lb) then 'Function is missing. Run 0001.'
      when exists (select 1 from lb where not has_user_id) then 'Old version without user_id. Run 0001.'
      when exists (select 1 from lb where not prosecdef) then 'Not security definer. Run 0001.'
      else 'OK'
    end

  union all
  select 10, 'Only the server and signed-in users can call leaderboard()',
    case
      when not exists (select 1 from lb) then 'FAIL'
      when (select has_function_privilege('anon', oid, 'EXECUTE') from lb) then 'FAIL'
      when not (select has_function_privilege('service_role', oid, 'EXECUTE') from lb) then 'FAIL'
      else 'PASS'
    end,
    case
      when not exists (select 1 from lb) then 'Function is missing'
      when (select has_function_privilege('anon', oid, 'EXECUTE') from lb) then 'Run 0003.'
      when not (select has_function_privilege('service_role', oid, 'EXECUTE') from lb) then 'The server cannot call it. Run 0003.'
      else 'OK'
    end

  union all
  select 11, 'Sign-up creates a profile row',
    case when count(*) filter (where p.prosecdef) > 0 then 'PASS' else 'FAIL' end,
    case
      when count(*) = 0 then 'No enabled trigger on auth.users calls handle_new_user()'
      when count(*) filter (where p.prosecdef) = 0 then 'handle_new_user() is not security definer, so sign-up will fail'
      else string_agg(t.tgname, ', ')
    end
  from pg_trigger t join pg_proc p on p.oid = t.tgfoid
  where t.tgrelid = to_regclass('auth.users')
    and t.tgfoid = to_regprocedure('public.handle_new_user()')
    and not t.tgisinternal
    and t.tgenabled <> 'D'

  union all
  select 12, 'Every user has a profile row',
    case when count(*) = 0 then 'PASS' else 'FAIL' end,
    case when count(*) = 0 then 'OK' else count(*) || ' user(s) without a profile. Their scans will fail.' end
  from auth.users u
  where not exists (select 1 from public.profiles p where p.id = u.id)

  union all
  select 13, 'Deleting a user also deletes their profile, scans and usage rows',
    case when profiles_users and scans_profiles and usage_profiles and usage_scans and blocking is null
         then 'PASS' else 'WARN' end,
    case when profiles_users and scans_profiles and usage_profiles and usage_scans and blocking is null then 'OK'
         else 'Needed for account deletion.'
              || case when not profiles_users then ' Missing: profiles to auth.users (cascade).' else '' end
              || case when not scans_profiles then ' Missing: scans to profiles (cascade).' else '' end
              || case when not usage_profiles then ' Missing: api_usage to profiles (cascade).' else '' end
              || case when not usage_scans then ' Missing: api_usage to scans (set null).' else '' end
              || coalesce(' These links would block a delete: ' || blocking || '.', '')
    end
  from links

  union all
  select 14, 'Admin accounts', 'INFO',
    count(*) || ' admin(s)' || coalesce(': ' || string_agg(display_name, ', ' order by display_name), '')
  from public.profiles where role = 'admin'

  union all
  select 15, 'Row counts', 'INFO',
    (select count(*) from public.profiles) || ' profiles, '
    || (select count(*) from public.scans) || ' scans ('
    || (select count(estimated_value) from public.scans) || ' with a value), '
    || (select count(*) from public.api_usage) || ' usage rows'
)
select n as "#", check_name as "check", result, details
from checks
order by n;
