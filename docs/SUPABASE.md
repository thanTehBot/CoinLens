# Supabase reference

Supabase does two jobs for CoinLens:

1. **Sign-in.** The app signs users up and in with Supabase Auth and gets an access token.
2. **Database.** Postgres holds profiles, scans and the daily-limit records, with row level security.

The app talks to Supabase directly for sign-in and for reading the user's own rows. The Flask server uses the secret service-role key for every write and for anything that spans users.

## Where the schema lives

`supabase/migrations/` is the source of truth. SQL in Git does not prove it was run on a project, so `supabase/verify.sql` checks a live project against it.

Run the migration files by hand in the SQL editor, in this order. The file names do not sort in the right order.

1. `20260914000000_profiles_and_scans.sql`
2. `0001_api_usage_and_leaderboard.sql`
3. `0002_grant_api_usage_service_role.sql`
4. `0003_tighten_privileges.sql`

Then run `supabase/verify.sql`. It is one read-only query that returns a table of checks. Every check should say PASS. The last two rows are INFO, for you to read.

On an existing project, run `verify.sql` first to see where things stand, then `0003`, then `verify.sql` again, then open the app and confirm that history, badges and the leaderboard still load. `0003` is safe to run more than once. It does not change what the app can read.

`0003` and `verify.sql` were tested on a local Postgres set up to imitate Supabase, starting from several different schemas. Read the output the first time you run them on a real project.

## Setting up a new project

1. Create the project.
2. **JWT keys.** The server only accepts tokens signed with asymmetric keys (ES256 or RS256), which it checks against the project's public keys. Projects created since October 2025 use these by default. A project still on the legacy JWT secret must be migrated under Project Settings, JWT Keys, or every server request fails with 401.
3. **Authentication, Sign In / Providers.** Email on. Anonymous sign-ins off, because the daily limit is per account. Leave the default rate limits as they are.
4. **Confirm email.** On for anything public. That requires custom SMTP (see `docs/SERVICES.md`), because Supabase's built-in mailer only sends to the project's own team members, two messages an hour. With confirmation on and no session returned, the app tells the user to check their email.
5. **Data API.** The `public` schema must be exposed to the Data API. That is the default.
6. Run the four migration files, then `verify.sql`.
7. Copy the keys:

| Key | Goes in | Never in |
|---|---|---|
| Project URL | App `.env.local`, server `SUPABASE_URL` | |
| Publishable key (older name: anon) | App `.env.local`, server `SUPABASE_ANON_KEY` | |
| Secret key (older name: service_role) | Server `SUPABASE_SERVICE_ROLE_KEY` only | The app, Git, screenshots, chat |

The app and the server must point at the same project. If they differ, every scan fails with a sign-in error, because the server checks the token against its own project.

Supabase is replacing the older `anon` and `service_role` keys with the publishable and secret keys. Its announcement says a project restored from a pause no longer has the older keys, and that all projects will have to switch (planned for late 2026, date not confirmed). If sign-in or scans stop working after a restore, open the project's API keys page and copy the current keys into `.env.local` and Render again. The server sends its key both as the `apikey` header and as the bearer token; that was only tested with one key format, so scan a coin after any key change.

## Tables

### profiles

One row per user: `id`, `display_name`, `role` (`user` or `admin`), `created_at`.

- Created by a trigger at sign-up: `auth.users` insert, then `on_auth_user_created`, then `handle_new_user()`.
- `display_name` comes from the sign-up form. If it is missing, the trigger uses the part of the email before the `@`. Display names are shown on the leaderboard, so the sign-up form should always send one.
- `created_at` is the "member since" date used by the Member badges.
- `role` only controls whether the app shows the Admin screen.
- In the migration files, `id` references `auth.users` with cascade delete, so deleting a user removes their profile, scans and usage rows. Check 13 in `verify.sql` confirms this on a live project.

### scans

One row per saved scan. The server is the only writer. It sets `user_id` from the token and works out `estimated_value`, `denom_canonical`, `is_foreign`, `local_date` and `local_hour` itself. `estimated_value` is empty when the coin was identified but no trustworthy price was found.

### api_usage

One row per scan attempt, used for the daily limit. The row is written before the OpenAI call and updated afterwards to `identified`, `uncertain` or `error`. Row level security is on with no policies, so only the server can touch it.

### leaderboard()

A `security definer` function that returns one row of totals per user. The server calls it with the service role and adds badge counts. The app gets the leaderboard from the server.

## Who can do what

What each role needs:

| Role | Who that is | profiles | scans | api_usage | leaderboard() |
|---|---|---|---|---|---|
| `anon` | The app before sign-in | no rows | no rows | nothing | no |
| `authenticated` | Signed-in app user | read own row | read own rows | nothing | yes |
| `service_role` | The Flask server | read, write | read, write | read, insert, update | yes |

Two separate layers produce this table, and both must be right:

- **GRANT** decides whether a role may run an operation on a table at all.
- **Row level security** decides which rows that role may see or change.

The migration files create two policies: read own profile (`id = auth.uid()`) and read own scans (`user_id = auth.uid()`). They create no insert, update or delete policies. That is deliberate. Do not "fix" a failed client write by adding a policy. Add a server route instead.

`anon` may hold a read right on `profiles` and `scans` from Supabase's defaults. Row level security gives it no rows, and `0003` leaves that alone so a signed-out app gets an empty list instead of an error. Signed-in users may call `leaderboard()` because the first migration grants it; it returns the same totals the server's leaderboard route returns.

### The lesson behind this

A real scan once failed with:

```text
42501 permission denied for table api_usage
```

The server uses the service role, which bypasses row level security. But bypassing row level security does not grant table rights, and that table had no GRANT for the service role. The fix was one line:

```sql
grant select, insert, update on public.api_usage to service_role;
```

Supabase no longer grants rights on new tables automatically. This has been the default for new projects since May 30, 2026, and Supabase has announced that it applies to existing projects from October 30, 2026. Existing tables keep their rights. **Every new table needs its own GRANT statements, row level security, and policies, written in the same migration.**

## Admin accounts

To make someone an admin, find their user id under Authentication, Users, then run:

```sql
update public.profiles set role = 'admin' where id = '<USER_ID>';
```

`verify.sql` lists the current admins. Never read a role from `user_metadata`. Users can edit their own metadata.

## Proving the rules work

These run in the SQL editor and act as a signed-in user. Replace `<USER_ID>` with a real user id from Authentication, Users. Paste and run one block at a time.

A user sees only their own scans. `acting_as` must say `authenticated`. If it says `postgres`, the first two lines did not take effect and the count means nothing.

```sql
set local role authenticated;
set local request.jwt.claims = '{"sub":"<USER_ID>","role":"authenticated"}';
select current_user as acting_as, count(*) as scans_visible from public.scans;
```

A user cannot invent a scan. This must end in an error.

```sql
begin;
  set local role authenticated;
  set local request.jwt.claims = '{"sub":"<USER_ID>","role":"authenticated"}';
  insert into public.scans (user_id, coin_name, estimated_value, source)
  values ('<USER_ID>', 'Fake', 1000000, 'camera');
rollback;
```

A user cannot make themselves an admin. This must end in an error or return no rows. If it returns a row, a policy is letting users edit profiles: see check 4 below.

```sql
begin;
  set local role authenticated;
  set local request.jwt.claims = '{"sub":"<USER_ID>","role":"authenticated"}';
  update public.profiles set role = 'admin' where id = '<USER_ID>' returning id, role;
rollback;
```

Both blocks end with `rollback`, so nothing is changed even if a statement gets through.

The full end-to-end check is two accounts on two phones: each sees only its own history, and both see the same leaderboard.

## Fixing a failed check

| Check in `verify.sql` | Fix |
|---|---|
| 1, 9 | Run the migration file that was missed |
| 2 | `alter table public.<table> enable row level security;` |
| 3 | The details column says which case it is. No read right: run `0003`. Missing policy: recreate it (below). A read policy that does not use `auth.uid()` can show every user's rows: drop it |
| 4, 5 | `drop policy "<policy name>" on public.<table>;` |
| 6, 7, 8, 10 | Run `0003_tighten_privileges.sql` |
| 11 | Recreate the sign-up trigger (below). If the details say the function is not security definer, run the second line below |
| 12 | Create the missing profile rows (below) |
| 13 | Fix the links (below). Needed before account deletion is built |

### Read policies

```sql
create policy profiles_select_own on public.profiles
  for select to authenticated using (id = auth.uid());
create policy scans_select_own on public.scans
  for select to authenticated using (user_id = auth.uid());
```

### Sign-up trigger

The function `handle_new_user()` comes from the first migration file and must already exist.

```sql
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

```sql
alter function public.handle_new_user() security definer set search_path = public;
```

### Missing profile rows

For users created before the trigger existed.

```sql
insert into public.profiles (id, display_name)
select u.id, coalesce(nullif(trim(u.raw_user_meta_data->>'display_name'), ''), 'Collector')
from auth.users u
where not exists (select 1 from public.profiles p where p.id = u.id);
```

### Links between tables

Start by listing the links and what each does when the row it points to is deleted:

```sql
select conrelid::regclass as table_name, conname as link_name, confrelid::regclass as points_to,
       case confdeltype when 'c' then 'CASCADE' when 'n' then 'SET NULL'
            when 'a' then 'NO ACTION' when 'r' then 'RESTRICT' else confdeltype::text end as on_delete
from pg_constraint
where contype = 'f'
  and confrelid in ('auth.users'::regclass, 'public.profiles'::regclass, 'public.scans'::regclass);
```

You want four rows: `profiles` to `auth.users` CASCADE, `scans` to `profiles` CASCADE, `api_usage` to `profiles` CASCADE, and `api_usage` to `scans` SET NULL.

If `profiles` has no link to `auth.users`, add it:

```sql
alter table public.profiles
  add constraint profiles_id_fkey
  foreign key (id) references auth.users (id) on delete cascade;
```

If that fails, a profile exists for a user who is gone. List those profiles:

```sql
select p.id, p.display_name
from public.profiles p
where not exists (select 1 from auth.users u where u.id = p.id);
```

Then remove them. Their scans and usage rows go with them.

```sql
delete from public.profiles p
where not exists (select 1 from auth.users u where u.id = p.id);
```

If a link exists with the wrong `on_delete`, drop it by the `link_name` from the list and add it again. For example, for `scans`:

```sql
alter table public.scans drop constraint <link_name>;
alter table public.scans
  add constraint scans_user_id_fkey
  foreign key (user_id) references public.profiles (id) on delete cascade;
```

The other two, if needed:

```sql
alter table public.api_usage
  add constraint api_usage_user_id_fkey
  foreign key (user_id) references public.profiles (id) on delete cascade;
alter table public.api_usage
  add constraint api_usage_scan_id_fkey
  foreign key (scan_id) references public.scans (id) on delete set null;
```

## Common errors

| What you see | Usual cause |
|---|---|
| Every scan fails with a sign-in error (401) | App and server point at different Supabase projects, or the project signs tokens with the legacy secret |
| 503 `quota_check_failed` | The service-role key is missing or wrong, the user has no profile row, or `api_usage` is missing its GRANT |
| `42501 permission denied for table ...` | A missing GRANT. Run `0003` |
| `Could not find the table ... in the schema cache` | The table was never created on this project. Run the migration files |
| Sign-up returns a user but no session | Confirm email is on. That is expected. The user must confirm, then sign in |
| `Database error saving new user` | The sign-up trigger failed. Look at Logs, Postgres |
| 429 during sign-up | Supabase's own sign-up or email rate limit |
| Leaderboard shows one user | An old `leaderboard()` is installed, or the app is calling the database directly. It should call the server |
| Everything fails at once after a quiet spell | The project is paused. See below |

## Free plan

Supabase pauses a free project after about a week with very little database activity. Real use of the app counts. Logging in to the dashboard does not. Supabase emails the project owner about a week before pausing and again when it happens.

While a project is paused, nobody can sign in and nothing loads. The owner restores it from the Supabase dashboard. Supabase keeps a paused project for a limited time (its help page said one year in October 2026). After a restore, check the keys as described under "Setting up a new project".
