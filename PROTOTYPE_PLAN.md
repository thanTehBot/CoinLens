# CoinLens prototype - E2E status

Architecture: Expo -> Supabase Auth JWT -> Flask (JWT verify, OpenAI + Numista +
optional PCGS, authoritative persistence) -> Supabase `scans` (RLS) -> Expo
reads own data under RLS; leaderboard via a Supabase RPC that returns safe
aggregates only.

## STATUS

All milestones implemented and unit-tested; one live migration is pending
(cannot be run by this session - no raw-SQL execution path is exposed via the
Supabase REST API, only the SQL editor / CLI, which needs a human).

- M1 OpenAI identification: single Responses-API call (`server/app.py:identify_coin_with_ai`),
  structured JSON schema output, `status: identified|uncertain`, `OPENAI_MODEL` env-configurable.
- M2 Numista-first valuation: type search + scoring match (`search_numista_types`,
  `select_best_numista_match`), grade-aware price lookup, valuation reported
  `unavailable` (never invented) on any ambiguous/missing match. PCGS is an
  optional fallback only, never load-bearing.
- M3 persistence + history: `/api/identify-coin` derives `user_id` from the
  verified JWT, `source` from the authenticated request body, and inserts the
  authoritative row via the service-role client (`persist_scan`). Expo reads
  its own history straight from Supabase under RLS (`src/api/scans.js`).
  RLS cross-user isolation verified live (see TESTED).
- M4 leaderboard: `public.leaderboard()` RPC (aggregate-on-read, no new
  tables/materialized views) wired into `LeaderboardScreen.js`. The live RPC
  already existed and is already callable by `authenticated`, but returns no
  `user_id` column yet - the migration adds one; the screen degrades
  gracefully (falls back to name-matching for "is this me") until it's run.
- M5 badges: same 57 badges, same JS rule engine, now reading real
  `denom_canonical` / `is_foreign` / `year` / `local_hour` / `local_date`
  columns computed server-side instead of regex-parsing a display string.
  Leaderboard's cross-user "badges" column uses a safe tier-only aggregate
  (`tierBadgeCount`) so it never fetches another user's raw scan history.
- M6 quota/security: Supabase-backed `api_usage` table (survives
  restarts/multi-worker), counts AI *attempts* not just successes, 429 with a
  structured body, image size cap (413), request size cap, per-upstream
  timeouts, no retries on billing/quota errors.
- M7 mock/real: existing `MOCK_MODE`/`USE_MOCK_COIN_RESPONSE` preserved as the
  "MOCK_AI" mechanism; mock path still writes real scan rows to Supabase
  through the same persistence code, so history/badges/leaderboard all work
  in mock mode with zero OpenAI/Numista/PCGS calls.
- M8 E2E: automated suites green (21 Python + 22 JS). Manual checklist below.

## TESTED

- `server/tests`: 21/21 passing (`python -m unittest discover -s tests`, run
  from `server/` with `.venv` activated).
- `__tests__`: 22/22 passing (`npm test`), including a new `badges.test.js`
  covering scan-count/net-worth/membership/denom/foreign/streak predicates
  against realistic Supabase-row shapes.
- Live E2E against the real Supabase project (mock mode, two disposable
  signup accounts, cleaned up afterward): full identify-coin -> persist ->
  read-back round trip; confirmed user B's session reads zero of user A's
  scans (`GET /rest/v1/scans` with each user's own JWT); confirmed
  `leaderboard()` RPC already executes for `authenticated` sessions.
  Validation-error paths (`missing_image`, `invalid_source`, `invalid_image`,
  `auth_missing`) all confirmed live with the correct HTTP status/code.
  Confirmed the quota gate fails closed with a clean 503 (not a crash) when
  `api_usage` doesn't exist yet - i.e. behaves correctly even before the
  migration below is run.

## FAILED

- None. (Two latent bugs in the pre-existing test suite - missing auth
  headers on `/api/generate-ebay-listing` and `/api/openai/chat` tests, and a
  stale `/api/health` body assertion - were fixed as part of getting the
  suite green; they were failing before this work started, unrelated to the
  milestones themselves.)

## NEXT (external actions required)

1. **Run the migration** in the Supabase SQL editor:
   `supabase/migrations/0001_api_usage_and_leaderboard.sql`
   - Creates `public.api_usage` (server-only, RLS enabled with no policies).
   - Recreates `public.leaderboard()` with a `user_id` column added.
2. **Set on Render** (server/.env.example documents all of these):
   `OPENAI_API_KEY`, `NUMISTA_API_KEY` are required for real (non-mock)
   identification/valuation; `PCGS_BEARER_TOKEN` is optional. New tunables:
   `OPENAI_MODEL`, `DAILY_SCAN_LIMIT`, `MAX_IMAGE_BYTES`,
   `MAX_CONTENT_LENGTH_BYTES`, `OPENAI_TIMEOUT_SECONDS`,
   `NUMISTA_TIMEOUT_SECONDS`, `PCGS_TIMEOUT_SECONDS`.
3. **Set an OpenAI provider-level spending limit** on the OpenAI account
   (dashboard action only you can do) - this is independent of and in
   addition to `DAILY_SCAN_LIMIT`.
4. Run the manual physical-phone checklist (final report) with the three
   real test coins, in both mock and real mode.
