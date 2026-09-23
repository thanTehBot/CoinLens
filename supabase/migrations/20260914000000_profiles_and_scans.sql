-- CoinLens Class 13: permanent profiles + scans foundation.
-- Run this once via `supabase db push`, `supabase migration up`, or by pasting
-- it into the Supabase SQL editor for this project. Idempotent-ish (uses
-- IF NOT EXISTS / OR REPLACE / DROP ... IF EXISTS) so it is safe to re-run.
--
-- Scope: profiles + scans only. No api_usage, quota, leaderboard, or badge
-- tables/policies are created here - those are later milestones.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null,
  role text not null default 'user' check (role in ('user', 'admin')),
  created_at timestamptz not null default now()
);

create table if not exists public.scans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  coin_name text,
  country text,
  denomination text,
  year integer,
  mint_mark text,
  estimated_grade text,
  estimated_value numeric,
  source text not null check (source in ('camera', 'gallery')),
  image_path text,
  created_at timestamptz not null default now(),
  -- Reserved for later milestones (badges/canonicalization). Left NULL today.
  denom_canonical text,
  is_foreign boolean,
  local_date date,
  local_hour integer check (local_hour is null or (local_hour between 0 and 23)),
  scanned_at timestamptz default now()
);

create index if not exists scans_user_id_idx on public.scans (user_id);
create index if not exists scans_created_at_idx on public.scans (created_at desc);

-- ---------------------------------------------------------------------------
-- Signup trigger: auth.users -> public.profiles
-- ---------------------------------------------------------------------------

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(
      nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
      split_part(new.email, '@', 1)
    )
  );
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.profiles enable row level security;
alter table public.scans enable row level security;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
  on public.profiles for select
  to authenticated
  using (id = auth.uid());

-- No client insert/update/delete policy on scans: the Flask server (using its
-- own elevated admin credential, which bypasses RLS) is the only writer.
drop policy if exists scans_select_own on public.scans;
create policy scans_select_own
  on public.scans for select
  to authenticated
  using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------

-- Narrow client grant: authenticated users may only ever SELECT, and RLS above
-- further restricts that to their own rows. No insert/update/delete grant.
grant select on public.profiles to authenticated;
grant select on public.scans to authenticated;

-- The server's elevated Supabase admin credential (SUPABASE_SECRET_KEY or the
-- legacy SUPABASE_SERVICE_ROLE_KEY) authenticates as service_role, which
-- bypasses RLS. It still needs explicit table privileges to read/write both
-- tables on its own behalf (e.g. inserting scans, reading profiles).
grant select, insert, update, delete on public.profiles to service_role;
grant select, insert, update, delete on public.scans to service_role;
