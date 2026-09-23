# CoinLens — session context export (2026-09-12)

Purpose: capture everything done in today's session — implementation,
assumptions, and a live production bug — so it can be pasted as context into
a future session without re-deriving it.

Branch: `seperate`. Latest pushed commit: `f7ff5dd` (origin/seperate).

---

## 1. What was built today, in order

### 1a. Full E2E prototype build-out (Milestones 0–8)

Replaced the mock-only scan flow with the real architecture:

```
Expo (Supabase Auth JWT) -> Flask (verify JWT, OpenAI + Numista + optional
PCGS, authoritative persistence) -> Supabase scans (RLS) -> Expo reads own
data under RLS; leaderboard via a Supabase RPC returning aggregates only.
```

Server (`server/app.py` and friends):
- **Identification**: single OpenAI **Responses API** call (not Chat
  Completions), structured JSON-schema output, model set by `OPENAI_MODEL`
  (default `gpt-4o-mini`). Replaced the old 4-call chain (free-text
  description → JSON extraction → separate valuation guess → separate
  summary call). Called via raw `requests.post` to
  `https://api.openai.com/v1/responses`, not the `openai` SDK.
- **Valuation**: Numista-first. `search_numista_types` → `score_numista_candidate`
  (country/denomination/year scoring) → `select_best_numista_match` (requires
  an unambiguous top score, ≥3, with no tie) → `fetch_numista_price` (grade-aware).
  Reports `status: "unavailable"` rather than inventing a number on any weak
  or ambiguous match. PCGS (`lookup_pcgs`) is a pure optional fallback, only
  used when Numista has no price.
- **Persistence**: `/api/identify-coin` now derives `user_id` from the
  verified JWT and `source` ("camera"/"gallery") from the authenticated
  request body, computes `denom_canonical` / `is_foreign` / `local_date` /
  `local_hour` server-side, and inserts the row via
  `supabase_admin.insert_scan` (service-role client). Never trusts
  client-supplied identity or value.
- **Quota (M6)**: new Supabase-backed `api_usage` table. `check_and_reserve_quota`
  counts today's AI *attempts* (not just successes) via `count_api_usage_since`,
  reserves an attempt via `insert_api_usage` *before* calling OpenAI, and
  returns 429 `quota_exceeded` if `DAILY_SCAN_LIMIT` is hit. Survives
  restarts/multi-worker since it's DB-backed, not in-process memory. Also
  added: per-image byte cap (`MAX_IMAGE_BYTES`, 413 `image_too_large`),
  overall request size cap (`MAX_CONTENT_LENGTH_BYTES`), per-upstream
  timeouts (`OPENAI_TIMEOUT_SECONDS`, `NUMISTA_TIMEOUT_SECONDS`,
  `PCGS_TIMEOUT_SECONDS`), and no retries on billing/quota errors
  (`is_retryable_openai_error` explicitly excludes 402/quota/billing).
- **Mock mode**: existing `MOCK_MODE`/`USE_MOCK_COIN_RESPONSE` preserved as-is
  (treated as the spec's "MOCK_AI" concept — not renamed). Mock path still
  writes real scan rows to Supabase through the same `persist_scan` code, so
  history/badges/leaderboard all work in mock mode with zero OpenAI/Numista/
  PCGS calls. Quota check is skipped in mock mode.

Supabase (`supabase/migrations/`):
- `0001_api_usage_and_leaderboard.sql` — creates `public.api_usage`
  (server-only, RLS enabled with no policies); redefines `public.leaderboard()`
  (drops + recreates because Postgres can't `CREATE OR REPLACE` a changed
  return signature) to add a `user_id` column the frontend needs.
- `0002_grant_api_usage_service_role.sql` — see §3, added later today after
  a production error.

Expo (`src/`):
- `src/api/scans.js` (new) — `fetchMyScans()` and `fetchLeaderboard()`, both
  direct-to-Supabase reads with the user's own session (RLS), bypassing Flask
  entirely for reads per the architecture.
- `src/Root.js` — `userScans` now loaded from Supabase (`refreshScans`) on
  auth state change instead of `AsyncStorage`; passed down to Account/Stats/
  Badges/Leaderboard; `ScanScreen` gets `onScanSaved={refreshScans}`.
- `src/badges/badges.js` — same 57 badges/UI/thresholds, but predicates now
  read real Supabase columns (`denom_canonical`, `is_foreign`, `year`,
  `local_hour`, `local_date`, `estimated_value`, `scanned_at`) instead of
  regex-parsing a `{coin, time, value}` display string. Added
  `tierBadgeCount()` — a safe aggregate-only approximation (scan-count/net-worth/
  membership tiers only) used for *other* users on the leaderboard, since
  computing their real badge set would require reading their raw scan history.
- `src/screens/leaderboard/LeaderboardScreen.js` — rewritten to call
  `fetchLeaderboard()` (the RPC) on an interval instead of a hardcoded
  `FAKE_USERS` array with a random `setInterval` incrementing fake stats.
  "Is this me" matches on `row.user_id`, falling back to display-name match
  if `user_id` isn't present yet (pre-migration compatibility).
- `src/screens/account/AccountScreen.js` — reads `userScans` prop instead of
  `AsyncStorage`; **removed the TEMP debug UI** (`GET /api/me` and
  `POST /api/test-scan` buttons) since it shouldn't be in the normal app flow.
- `src/screens/stats/StatsScreen.js` — same `AsyncStorage` → `userScans` prop
  swap, field renames (`coin_name`, `estimated_value`, `scanned_at`).
- `src/screens/scan/ScanScreen.js` — sends `source` and
  `tz_offset_minutes` (`Date.getTimezoneOffset()`) with every identify-coin
  call; removed local `AsyncStorage` history writes (server is now
  authoritative); "Estimated Value" card redesigned for a single
  Numista/PCGS-sourced number instead of an AI-guessed low/high range.
- `src/api/client.js` — `identifyCoin(front, back, source)` signature change;
  added friendly `ERROR_DISPLAY` entries for the new error codes
  (`quota_exceeded`, `image_too_large`, `invalid_source`, etc).

Tests: `server/tests/` (Python, `unittest`) and `__tests__/` (JS,
`node --test`, including new `badges.test.js`). Verified live against the
real Supabase project using two disposable signup accounts (RLS cross-user
isolation confirmed, real persist round-trip confirmed), then deleted.

### 1b. Disabled eBay listing generation for V1

- `server/app.py`: `ENABLE_EBAY_LISTING` env flag (default `false`).
  `/api/generate-ebay-listing` now returns immediately —
  `{"feature_disabled": true, "feature": "ebay_listing", "message": "..."}`,
  HTTP 200 — *before* reading the body, before the mock check, before any
  OpenAI call. Implementation below the flag is untouched (kept for later
  re-enable).
- `src/screens/scan/ScanScreen.js`: `EBAY_LISTING_ENABLED = false` constant;
  the whole "eBay Listing Draft" card is wrapped in it. State/handler
  (`ebayListing`, `handleCreateEbayListing`, etc.) left in place, just
  unreachable.
- Tests updated/added in `server/tests/test_app.py` to prove: default is
  disabled with the exact structured body, and `requests.post` (OpenAI) is
  never called when disabled; the enabled path is still tested by
  explicitly flipping the flag.

### 1c. Removed the unused `/api/openai/chat` route

- Confirmed via repo-wide search: **zero callers**, anywhere. Both real
  OpenAI-calling paths (`identify_coin_with_ai` for scans,
  `openai_chat_content` for the eBay listing) already call OpenAI's HTTP API
  directly — neither ever routed through this local proxy endpoint.
- Removed the route + handler from `server/app.py`; removed the now-dead
  `build_mock_reply()` from `server/mock_openai.py` (its only caller) and the
  now-unused `import json` there; removed the now-unused import in
  `server/app.py`.
- `OPENAI_CHAT_URL`, `OPENAI_TIMEOUT`, `proxy_response` were **kept** — still
  used by `openai_chat_content` (eBay path) and the other proxy routes
  (`/api/numista-specs`, `/api/pcgs-value`, `/api/log-scan`, `/api/scans`).
- Test updated: trimmed the `/api/openai/chat` assertions out of
  `test_proxy_routes_return_mock_payloads` (kept the rest — numista/pcgs/
  log-scan/scans are unrelated); added `test_openai_chat_route_removed`.
  Note: that test asserts **500**, not 404 — this app has a blanket
  `@app.errorhandler(Exception)` that catches Flask's normal 404 for an
  unmatched route and turns it into a generic 500 `server_error`. This is
  **pre-existing, unrelated behavior**, left as-is; the test was written to
  match reality rather than "fix" something out of scope.

### 1d. Committed and pushed

- One commit, `d5cd4b7`, covering all of 1a + 1b + 1c (18 files changed).
- Tightened `.gitignore` (`server/__pycache__/` → `__pycache__/`) so test
  bytecode from the new `server/tests/__pycache__/` doesn't get committed.
- No secrets staged (`.env`/`.env.local`/`server/.env` correctly ignored).
- Pushed to `origin/seperate` (`f3f7357..d5cd4b7`).

### 1e. Follow-up commits (same day, after the incident in §3)

Three more focused commits, pushed together (`d5cd4b7..fe9369d`):
- `c2ee5d9` — the `service_role` grant fix for `api_usage` (§3/§4b).
- `4a7adce` — Numista/PCGS pipeline observability logging + a bugfix found
  while adding it (§6).
- `fe9369d` — this context export document itself.

---

## 2. Assumptions made (things a future session should sanity-check)

- **Numista v3 API shape is unverified against a live key.** No
  `NUMISTA_API_KEY` was available in this environment. `search_numista_types`
  defensively checks for `types`/`items`/`results` as the result-list key,
  and `fetch_numista_price` assumes a `/types/{id}/prices?currency=USD`
  endpoint returning a `prices` array with `grade`/`price` fields. **Spot-check
  this once a real key is added** — field names may need adjusting.
- **No `openai` Python package was installed.** Chose direct `requests.post`
  calls to `https://api.openai.com/v1/responses` instead of the SDK, to keep
  the identical error-handling/mocking pattern already used for every other
  upstream call in this file, and to avoid a new dependency whose
  availability in this sandbox was unverified. Functionally equivalent to
  using the SDK; can be swapped later if preferred.
- **Confidence floor of 40** (`MIN_IDENTIFICATION_CONFIDENCE`) is an
  additional safety net on top of the model's own `status` field
  (`identified`/`uncertain`), not the sole signal — per the instruction not to
  rely solely on a fabricated numeric percentage.
- **Numista match ambiguity threshold**: best candidate must score ≥3 *and*
  not tie with the runner-up, or the match is treated as "no confident
  match" (valuation → unavailable). This threshold was chosen conservatively
  and has not been tuned against real search results.
- **Quota scope**: `DAILY_SCAN_LIMIT` only gates `/api/identify-coin`. The
  eBay-listing endpoint (even when re-enabled) is a separate, user-triggered
  action and was deliberately not folded into the scan quota.
- **`tz_offset_minutes`** is accepted from the client (`Date.getTimezoneOffset()`)
  and used only to compute `local_date`/`local_hour` for badge display
  grouping — treated as non-authoritative/cosmetic, not a security- or
  value-sensitive field, so trusting client input here was judged acceptable
  (unlike `user_id` or `estimated_value`).
- **`denom_canonical` vocabulary** intentionally mirrors the old client-side
  `_denomOf()` logic (`wheat-penny` takes precedence over generic `penny`,
  etc.) for backward-compatible badge behavior, with a generic slugified
  fallback for non-US denominations (e.g. a Canadian 5¢ won't match any of
  the US-specific type badges — expected, not a bug).
- **`is_foreign`** is a simple string match against
  `{"united states", "usa", "u.s.", "u.s.a.", "united states of america"}` —
  no fuzzy matching or country-code lookup.
- **Leaderboard "Most Badges" column for other users** deliberately uses the
  cheap `tierBadgeCount()` approximation (built only from the RPC's safe
  aggregate fields), not each user's real 57-badge set — computing the real
  set would require reading another user's raw scan history, which the
  architecture explicitly forbids. Only *your own* row shows the real count.
- **Optional Numista/PCGS metadata columns** (composition, weight, diameter,
  `numista_type_id`, `valuation_source`) were **not** added to `scans` —
  judged as not genuinely required for the prototype to work end-to-end on
  the existing columns. Deferred, not forgotten.
- **`MOCK_MODE` was kept as the source of truth**, not renamed to `MOCK_AI` —
  treated as the existing implementation of that concept per "preserve
  existing... mock mode."
- **Both `require_auth` (JWKS, no network round-trip) and `require_user`
  (calls Supabase's `/auth/v1/user`) were preserved** as separate mechanisms
  per explicit instruction, even though they're redundant in principle.
- **eBay-disabled response is HTTP 200**, not 404/503 — chosen so any caller
  (automation, a future re-enabled UI probing the flag) parses it as a clean
  data shape rather than an error path.

---

## 3. Today's production incident: Supabase permission error

**Symptom** (from Render logs, real device, mock mode off):
```
ERROR:supabase_admin:supabase count_api_usage_since failed: status=403
body={"code":"42501","details":null,
"hint":"Grant the required privileges to the current role with:
GRANT SELECT ON public.api_usage TO service_role;",
"message":"permission denied for table api_usage"}
...
127.0.0.1 - - [...] "POST /api/identify-coin HTTP/1.1" 503 106 ...
```
Client saw: `{"error": {"code": "quota_check_failed", "message": "Could not
verify your usage limit. Try again shortly."}}`.

**Root cause**: `public.api_usage` (from migration `0001`) was created by
running raw SQL directly in the Supabase SQL editor, not through Supabase
Studio's table editor. Studio auto-grants new tables to
`service_role`/`anon`/`authenticated`; a table created via plain SQL does
not get that for free. RLS-bypass and base table privileges are two
*separate* permission layers — `service_role` already bypasses RLS (that
part was fine), but it still needs an explicit `GRANT` to touch the table at
all, which it never got. `scans`/`profiles` already worked because they
were created earlier (evidently via Studio or with grants already applied).

**Behavior validation**: the app did the *correct* thing here — it failed
closed with a clean 503, not a crash and not a silent bypass of the quota
gate. No app code changes were made or needed.

**Fix**: a database-only grant, broader than the error's own hint since
Flask also inserts and updates `api_usage` rows (would have hit the same
wall next):
```sql
grant select, insert, update on public.api_usage to service_role;
```

**Status**: fix is committed and pushed (`c2ee5d9`, see §4) but **has not
yet been confirmed run against the live database** — a `git push` does not
execute SQL against Supabase. That's still the one pending external action
from today (§7).

---

## 4. All SQL run/written so far (in order)

### 4a. `supabase/migrations/0001_api_usage_and_leaderboard.sql`
Written in an earlier session; **run once already** by the user in the
Supabase SQL editor. Since then, the file has also been amended in-place
(same file, not a new one) to add the `service_role` grant for
`api_usage` — see 4b for why a *second*, standalone migration was created
instead of asking for a re-run of the whole file.

```sql
-- CoinLens prototype: API cost-protection accounting + leaderboard RPC.
-- Idempotent: safe to run multiple times.

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

alter table public.api_usage enable row level security;

-- Added today (2026-09-12), after the production 42501 error:
grant select, insert, update on public.api_usage to service_role;

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
```

### 4b. `supabase/migrations/0002_grant_api_usage_service_role.sql`
**New today, NOT yet confirmed run.** This is the actual action item —
same single `GRANT` statement as embedded in 4a above, pulled out standalone
so the user's *already-migrated* project (which ran 0001 before this grant
was added to it) doesn't need to re-diff or re-run the whole original file:

```sql
grant select, insert, update on public.api_usage to service_role;
```

### 4c. Ad-hoc read-only verification (not migrations, not re-runnable SQL —
listed for completeness since they touched the live database)
Run via Supabase's PostgREST REST API (service-role/anon keys), during
earlier verification of Milestones 0–8, *before* today's session:
- Introspected live schema via `GET {SUPABASE_URL}/rest/v1/` (OpenAPI/Swagger
  document) to confirm `profiles`/`scans` columns and discover the
  pre-existing `leaderboard()` RPC.
- `GET /rest/v1/scans`, `GET /rest/v1/profiles` with anon key (no session) —
  confirmed RLS returns `[]`, not an error.
- `POST /rest/v1/scans` with anon key (no session) — confirmed RLS rejects
  the insert (`42501`).
- Signed up two disposable test accounts (`POST /auth/v1/signup`), ran two
  real `/api/identify-coin` calls in mock mode through the live Flask
  server, confirmed `GET /rest/v1/scans` with each user's own JWT shows only
  their own rows (RLS cross-user isolation).
- Cleaned up afterward: `DELETE /rest/v1/scans?user_id=eq.<id>`,
  `DELETE /auth/v1/admin/users/<id>` (×2) — production database was left in
  its original state.

None of 4c involved DDL or any statement that needs to be re-run; it's
included only so the full picture of what touched the live database today
(and in the lead-up to today) is in one place.

---

## 6. Follow-up change: Numista/PCGS pipeline observability + bugfix

**Trigger**: the user wanted to verify the Numista API contract end-to-end
(the assumptions flagged in §2 were made without a live key) and pointed out
that no Numista/PCGS response or error was being logged anywhere — so a
wrong field-name assumption would only ever show up as a silent "valuation
unavailable," never as a visible discrepancy.

**What was added** (`server/app.py` only, `commit 4a7adce`): tagged,
greppable `app.logger.info`/`.warning`/`.error` calls at every stage of the
pipeline, so a real test scan's Render logs read top-to-bottom against the
actual stages:

| Tag | What it shows |
|---|---|
| `[identify]` | OpenAI's structured result (status/confidence/country/denomination/year/grade); final valuation decision; scan-persisted confirmation with row id |
| `[numista]` | search query sent + **raw response body** (truncated to 1500 chars); candidate count; top 3 scored candidates (score, id, title); which one was selected and why, or why none qualified (score too low / tied with runner-up); type-detail fetch result; price-endpoint **raw response body**; exact-grade match vs. nearest-available-grade fallback |
| `[pcgs]` | whether the optional fallback was attempted, skipped (no PCGS reference), succeeded, or failed |
| `[valuation]` | final available/unavailable decision and why |

Raw response bodies are logged (truncated, not full) specifically so the
*actual* Numista JSON shape can be read directly from Render logs and
compared against the field names the code assumes
(`types`/`items`/`results`, `issuer.name`, `min_year`/`max_year`,
`prices[].grade`/`.price`) — this is the concrete mechanism for verifying
the contract in §2's first assumption.

**Bug found and fixed while adding this**: `fetch_numista_price`'s "no exact
grade match, use nearest available" fallback branch read a price entry via
`middle["value"]` instead of `middle["price"]` (the actual key on a Numista
price-list entry, consistent with the exact-match branch a few lines above
it, which already used `entry["price"]` correctly). This would have raised
`KeyError: 'price'` the first time a real scan's grade didn't exactly match
a priced grade in Numista's response — i.e. probably on the very first real
test scan. Caught by re-reading the diff before testing, not by a test
catching it.

**Verification performed**: wrote a one-off script (not committed — it was
throwaway) that patches `requests.get` to return realistic canned Numista
responses (a Canada 5 Cents search hit → type detail → a `prices` array with
no exact `"VF-30"` entry, forcing the nearest-available fallback) and ran
`lookup_numista()` + `estimate_value()` against it directly. Confirmed: no
crash, correct value selected, and every log line described above actually
appears in the expected order/format. This is the same technique available
for verifying real Numista responses later, just with real data instead of
a canned fixture.

**No behavior changed**: matching thresholds, scoring, valuation
decision logic, and return shapes are all identical to before — this was
purely additive logging plus the one real bug fix.

**Tests**: 24/24 Python (`python -m unittest discover -s tests` from
`server/`), 22/22 JS (`npm test`) — unaffected, since no existing test
exercises the Numista/PCGS HTTP calls directly (all gated behind
`NUMISTA_API_KEY`/mock mode in every current test, so none of them reach the
new logging code).

**Still not done**: an actual real scan against the live Numista API has not
happened yet in this session (no `NUMISTA_API_KEY` was available here). The
`[numista]` log lines are ready to read the moment that happens on Render.

---

## 7. Follow-up change: manual capture button replaces auto-capture

**Trigger**: the user reported the camera scan flow as "impractical and
broken" — it showed the scanning animation, auto-snapped the front photo
after a fixed ~2.5s timer, then auto-snapped the back photo ~2.5s after the
"flip the coin" prompt, with no way to control shutter timing.

**Root cause**: a single `useEffect` in `src/screens/scan/ScanScreen.js`
started a `setTimeout` calling `capture()` automatically whenever the camera
was ready, restarting itself every time `captureStage` flipped from
`front` → `back`. The round indicator under the camera preview was purely
decorative (an `Animated.View`, not a button) — there was no manual capture
path to fall back to at all.

**Fix** (commit `d04e3e8`, 4 files):
- `src/screens/scan/ScanScreen.js` — deleted the auto-capture `useEffect`
  and its timer ref entirely. Kept the scanning animation (corner brackets,
  scan-line sweep) unchanged. Wired the existing `capture()` state machine
  (front → back → identify — already correct, it just needed a manual
  trigger instead of a timer) to a tap on the round indicator, now a real
  `TouchableOpacity`. Added an `isCapturing` guard so a rapid double-tap
  can't fire two captures at once, and disabled the button until
  `cameraReady`.
- `src/theme/styles.js` — two small additive styles: `captureIndicatorDisabled`
  (dims the button while disabled/capturing) and `captureButtonInner` (a
  solid inner dot so the ring reads visually as a shutter button).
- `scanFlowLogic.js` — updated the front/back hint copy to say "tap the
  button below to capture the front/back of the coin" instead of "will
  capture automatically"; kept the "Flip the Coin" title as asked; dropped
  the now-unused `autoCaptureDelayMs`.
- `__tests__/scanFlowLogic.test.js` — updated the two assertions that
  specifically tested the old "automatically"/`autoCaptureDelayMs` behavior.

**Tests**: 22/22 JS passing. No Python files touched.

---

## 8. Follow-up change: identification confidence now means the COMPLETE id

**Trigger**: a real (non-mock) scan produced `status=uncertain,
confidence=84, country=Hong Kong, denomination=10 cents, year=Not legible`.
The 422/no-Numista behavior was already *correct* (status=uncertain
correctly blocked the scan) — the problem was purely semantic: a
confidence of 84 reads as "very sure" right next to "uncertain," which is
confusing and would be actively misleading if confidence were ever surfaced
to a user or used for any downstream decision. The model was evidently
scoring confidence based on how clearly it could read country/denomination,
ignoring that the year - also required for a Numista catalog lookup - was
illegible.

**Fix** (`server/app.py` only, prompt/schema text - no logic or contract
changes):
- `IDENTIFICATION_PROMPT` rewritten so `confidence` is explicitly defined as
  confidence in the *complete* identification needed for a Numista lookup -
  country **and** denomination **and** year **and** mint mark (when
  relevant) together, not just whichever field is easiest to read. Explicit
  worked example: "if the country and denomination are unmistakable but the
  year is worn away... confidence must be low (well under 40) and status
  must be 'uncertain'." `status` guidance updated to match (any one of those
  fields being illegible/guessed/unknown means uncertain, even if the rest
  are clear).
- `IDENTIFICATION_JSON_SCHEMA` — added non-breaking `"description"`
  annotations to the `status` and `confidence` properties reinforcing the
  same guidance directly in the structured-output schema (types/required/
  enum unchanged, so the wire contract is identical).
- `MIN_IDENTIFICATION_CONFIDENCE` (40) and `normalize_identification()`'s
  `identifiable = status == "identified" and confidence >= 40` logic were
  **not** changed — the 422 behavior was already correct; this fix is about
  making the *value* the model reports consistent with that behavior, not
  about how the server interprets it. No server-side clamping was added
  (e.g. forcibly capping confidence when status is "uncertain") since this
  was scoped as a prompt/schema fix, not a defensive-code fix.

**Tests added** (`server/tests/test_app.py`, all passing): since a live
model can't be invoked in a unit test, these exercise
`normalize_identification()` directly with realistic response shapes for
each scenario, plus one full-route test:
- `test_normalize_identification_fully_identified_coin_is_high_confidence` —
  all fields legible → `identified`, confidence ≥ 70.
- `test_normalize_identification_illegible_year_is_uncertain_and_low_confidence` —
  the exact reported scenario (country/denomination clear, year illegible)
  → `uncertain`, confidence < 40, country/denomination still surfaced.
- `test_normalize_identification_non_coin_is_uncertain` — nothing legible →
  `uncertain`, confidence < 40, fields fall back to "Unknown".
- `test_identify_coin_illegible_year_returns_422_without_numista` — full
  `/api/identify-coin` route test asserting 422, confidence below threshold,
  and that Numista search and scan persistence are never reached.

**Tests**: 28/28 Python passing (24 → 28), 22/22 JS passing (unaffected).

**Not yet verified against a real model call** — no `OPENAI_API_KEY` is
available in this environment, so whether GPT actually complies with the
strengthened prompt on real photos (like the reported Hong Kong 10 cents
case) still needs a live test scan to confirm.

---

## 9. Follow-up change: unmatched routes now return 404/405, not 500

**Trigger**: the user woke the Render server up in the morning by visiting
`/api/health` in a browser, then got confused seeing this in the logs:
```
GET /favicon.ico HTTP/1.1" 500 ...
GET /identify-coin HTTP/1.1" 500 ... "Mozilla/5.0 (iPhone; ...) Safari/604.1"
```
and worried the app might be crashing or someone was hitting the real scan
endpoint. Diagnosed as harmless: the `/identify-coin` hit was a plain
mobile-Safari `GET` to the wrong path (missing the `/api` prefix, wrong
HTTP method, no referer, User-Agent is Safari not the Expo app's
`Expo/... CFNetwork/... Darwin/...` signature) - confirmed by grepping the
entire client codebase and finding only one call site
(`src/api/client.js:108`), which correctly POSTs to `/api/identify-coin`.
Most likely just someone (possibly the user) typing/tapping that URL
directly into Safari, not a real scan attempt, a bot, or a security issue -
it never reached `require_auth`, so no auth, quota, OpenAI, Numista, or
Supabase code ran at all.

**Real (pre-existing) bug this surfaced**, independently flagged by another
AI reviewer as worth fixing before release testing: `server/app.py` had a
blanket `@app.errorhandler(Exception)` that catches *every* exception,
including Flask/Werkzeug's own routing-level `HTTPException`s (404 Not
Found, 405 Method Not Allowed, etc). With no more specific handler
registered for those, every wrong-URL or wrong-method request - completely
harmless - got logged and returned as a generic `500 server_error`, making
routine noise indistinguishable from a real crash. This is exactly what
made the log line above look alarming.

**Fix** (`server/app.py`): added `from werkzeug.exceptions import
HTTPException` and a new `@app.errorhandler(HTTPException)` handler that
returns the exception's real status code (404, 405, 400, etc.) in the
app's normal `{"error": {"code": ..., "message": ...}}` shape, with `code`
derived from the exception's name (e.g. `not_found`, `method_not_allowed`).
Registration order doesn't matter to Flask - it picks the most specific
match in the exception's MRO - so:
- the existing more-specific `@app.errorhandler(413)` still wins for
  oversized uploads (verified by a new test),
- the new `HTTPException` handler catches 404/405/400/etc. that have no
  more specific handler,
- the blanket `@app.errorhandler(Exception)` now only catches genuine,
  non-HTTP application bugs (verified by a new test that forces a
  `RuntimeError` and confirms it still comes back as 500).

No other behavior changed - identification, valuation, quota, persistence,
and the 422/429/413 contracts are untouched.

**Tests added** (`server/tests/test_app.py`):
- `test_unknown_route_returns_structured_404_not_500` - reproduces the
  exact `/identify-coin` scenario from the log.
- `test_wrong_method_returns_structured_405` - `GET /api/identify-coin`
  (POST-only) now 405s cleanly.
- `test_oversized_upload_still_returns_413_not_generic_http_exception` -
  confirms the new handler doesn't shadow the existing 413 handler.
- `test_unexpected_server_error_still_returns_500` - confirms a real bug
  still surfaces as 500.
- `test_openai_chat_route_removed` (existing, from an earlier session)
  updated to assert 404 instead of documenting the old 500-on-404 quirk,
  since that quirk is now fixed.

**Verified live**: booted the server locally in mock mode and reproduced
the user's exact log lines - `GET /favicon.ico` and `GET /identify-coin`
both now return 404 (previously 500); `GET /api/identify-coin` (wrong
method) returns 405; `GET /api/health` still works normally.

**Tests**: 32/32 Python passing (28 → 32), 22/22 JS passing (unaffected).

---

## 11. Follow-up change: quota_exceeded now shows "Back to Home" instead of "Try Again"

**Trigger**: after hitting the daily scan limit, the error screen still
offered a "Try Again" button that just replayed the same identify-coin
request the server would immediately 429 again — a useless retry for the
one error code where retrying can never succeed until the quota resets.

**Fix** (4 files, commit `f8038a3`):
- `scanErrorLogic.js` (new) — extracted `ScanError`, `ERROR_DISPLAY`, and
  `makeErrorDetail` out of `src/api/client.js` into a plain CommonJS module
  with no React Native imports, so it can be unit-tested directly under
  `node --test` (`client.js` pulls in `react-native` transitively via
  `src/api/supabase.js`, which can't load under plain Node — same reasoning
  as why `scanFlowLogic.js`/`aiLogic.js` already live outside `src/`). Added
  `isRetryableErrorCode(code)`, which returns `false` only for
  `quota_exceeded`; `makeErrorDetail` now also returns `code` and
  `retryable` on the detail object. Title/tip/body text is unchanged — the
  daily-limit body already comes dynamically from the server's
  `DAILY_SCAN_LIMIT`-based message (`f"Daily scan limit of {DAILY_SCAN_LIMIT}
  reached..."`), so no client-side hardcoded number was needed or added.
- `src/api/client.js` — now imports and re-exports `ScanError`/
  `makeErrorDetail` from `scanErrorLogic.js` instead of defining them
  inline; no behavior change.
- `src/screens/scan/ScanScreen.js` — in the `error` phase only, the button
  is now conditional on `ed.retryable`: `quota_exceeded` renders "Back to
  Home", whose handler calls `startNewScan()` (clears `errorDetail`/
  `frontImage`/`backImage`/phase, etc. — the same reset already used
  elsewhere) and then `navigate("home")` (the same home-navigation path the
  screen's own header back button and guest-mode exit already use). No API
  call is made and the camera is never reopened. Every other error code,
  and the separate `unidentifiable` phase (a distinct outcome, not an
  error), keep their existing "Try Again" → `startNewScan()` behavior
  unchanged.
- `__tests__/scanErrorLogic.test.js` (new) — 3 tests: `quota_exceeded` is
  non-retryable and keeps its title/dynamic-limit body; a sample of other
  codes remain retryable; a plain (non-`ScanError`) error falls back to
  retryable `unknown`.

**Not committed alongside this**: an unrelated, already-modified
`server/app.py` (pre-existing 1-line change in the working tree before this
task started) was deliberately left unstaged/uncommitted rather than swept
in with `git add -A`.

**Tests**: 25/25 JS passing (22 → 25). No Python files touched, no backend
quota logic (`DAILY_SCAN_LIMIT`, `check_and_reserve_quota`, etc.) changed.

---

## 13. Follow-up change: camera scan box shrunk + fixed zoom to fix out-of-focus captures

**Trigger**: the user reported that the square capture guide box in the
scan camera view was a bit too big — positioning a coin to fill it meant
holding the phone closer to the coin than the lens can actually focus at,
so the coin came out blurry.

**Diagnosis discussed before changing anything**: the blur is the phone's
autofocus failing at too-close a distance, not a bug in the guide box
itself. Two candidate fixes were weighed: (a) shrink the guide box, which
encourages standing farther back but also means the coin fills less of the
captured frame (a real tradeoff for AI identification, which wants
mint-mark/wear detail); (b) apply camera zoom so the phone can stay at a
safer focus distance while the coin still visually fills the frame, at the
cost of a digital-zoom crop. Decided to do both, but lean on zoom as the
main lever and only shrink the box slightly, rather than shrinking it a lot
and asking users to move even closer to compensate.

**Fix** (2 files, **not yet committed**):
- `src/theme/colors.js` — `BOX_SIZE` (used by both `ScanScreen.js` and
  `theme/styles.js` for the guide box and the scan-line animation range)
  260 → 230. All box-size usages already derive from this one constant, so
  no other file needed a change.
- `src/screens/scan/ScanScreen.js` — added `zoom={0.3}` (expo-camera's
  `CameraView` zoom prop, range 0–1) to the capture `CameraView`, so the
  preview/capture is digitally zoomed in a fixed, fairly conservative
  amount rather than relying on the user standing unnaturally close.

**Not done / explicitly deferred**:
- Rounding the guide box corners (raised as a "make it round-ish if easy"
  option) was **not** applied — decided the zoom+size change was the
  substantive fix for the blur complaint, and roundness is purely cosmetic
  with no effect on focus.
- `zoom={0.3}` is a starting guess, not measured against a real device in
  this session (no physical device/camera available here) — flagged as
  needing a real on-device check, see §14.

**Tests**: 25/25 JS passing, unaffected (no test exercises `CameraView`
props or pixel-level box size). No Python files touched.

---

## 14. Follow-up change: retry on transient Supabase gateway errors

**Trigger**: a real (non-mock) scan against the live Render deployment
identified a Canadian 2016 1-dollar coin correctly, then failed with
`Couldn't Save Scan` in the app. Render logs showed the true cause:
```
ERROR:supabase_admin:supabase insert_scan failed: status=504 body={"message":"Gateway Timeout"}
ERROR:app:scan insert failed for user_id=...: scans insert failed: status=504 body={"message":"Gateway Timeout"}
```
Not a schema, grant, or auth problem (unlike §3) — Supabase's own REST
gateway returned a 504 before our 10s client-side timeout was even reached.
The concerning part: the identification (and the quota attempt it
consumed) had already succeeded, so a single transient gateway blip cost
the user one of their daily scans for nothing.

**Fix** (`server/supabase_admin.py` only, **not yet committed**): added a
small `_request_with_gateway_retry(method, *args, **kwargs)` helper that
retries a `requests` call up to `MAX_GATEWAY_RETRIES` (2) times, with a
short linear backoff (`RETRY_BACKOFF_SECONDS = 0.5`, so 0.5s then 1s),
*only* when the response status is 502/503/504 — a real 4xx (bad data,
auth) or any 2xx returns immediately without retrying, so this can't mask
an actual bug as a "transient" one. Applied to the three admin calls that
hit Supabase's REST gateway and currently raise on failure: `insert_scan`,
`insert_api_usage`, `count_api_usage_since`. Deliberately **not** applied
to `update_api_usage` — that's already a best-effort, never-raises
bookkeeping call (out of the scope the user confirmed).

**Not changed**: `REQUEST_TIMEOUT` (10s, the client-side timeout — the
504 in the log was returned *by* Supabase, not a local timeout, so raising
this wouldn't have helped), and none of the quota/persistence decision
logic in `server/app.py` — this is purely a transport-layer retry around
the existing calls.

**Tests added** (`server/tests/test_supabase_admin.py`, new file, 5 tests,
mocks `requests.post`/`requests.get` and `time.sleep` so no real delay or
network call happens):
- `insert_scan` retries once on a transient 504 then succeeds.
- `insert_scan` gives up after 2 retries (3 total attempts) on a
  persistent 503, still raising `SupabaseAdminError`.
- `insert_scan` does **not** retry a real 400 (confirms retries are scoped
  to gateway statuses only).
- `insert_api_usage` retries on a transient 502 then succeeds.
- `count_api_usage_since` retries on a transient 503 then succeeds (and
  still parses the `Content-Range` header correctly on the retry).

**Tests**: 37/37 Python passing (32 → 37, all in 0.06s — confirms the
backoff sleep is properly mocked, not actually slowing the suite down).
25/25 JS passing, unaffected.

**Not yet done**: this has not been verified against a real Supabase
gateway timeout in production — the original 504 was intermittent, so
there's no guaranteed way to reproduce it on demand; the next time it
happens, the Render logs should show a `WARNING:supabase_admin:supabase
request got a transient 504, retrying...` line followed by a success
instead of the scan failing outright.

---

## 15. Follow-up change: resize images before identification + log OpenAI token usage

**Trigger**: the user hit `Rate Limit Hit` ("AI provider rate or quota limit
reached") twice, many minutes apart — not a burst pattern, which pointed
away from a per-minute request-count limit. They shared their OpenAI
usage-tier page: on the free/lowest tier, the models available are capped
at **10,000 TPM / 3 RPM** (one row, "gpt-5.6-luna", got 60,000 TPM / 10
RPM), and their usage dashboard showed **104,337 input tokens across just
6 requests** (~17.4K tokens/request average) — nowhere near the 50
requests/day cap, but plausibly already over a 10K-tokens-*per-minute* cap
on a single request, independent of timing between requests.

**Diagnosis**: `identify_coin_with_ai` (`server/app.py`) sends one Responses
API call per scan with one or two full-resolution photos as
`input_image`/`data_url` content. Vision models bill images by tiling them
into fixed-size chunks, so an uncompressed/undownscaled phone photo (often
3000-4000px on the long edge) can cost far more tokens than a resized one
without a proportional accuracy benefit — plausibly enough, on its own, to
exceed a low-tier account's per-minute token budget regardless of how far
apart requests are spaced. This was reasoned from the account's own
dashboard numbers, not confirmed with an exact per-request token count
(OpenAI's Responses API does return a `usage` object we weren't logging —
see the second half of the fix below, added specifically to close that gap
for next time).

**Fix** (6 files, commit `5992a54`, **user confirmed "both now" before this
was implemented** — chose to do the accuracy-affecting resize *and* the
safe logging-only addition together rather than logging first and waiting
for another failure):

- `src/api/imagePrep.js` (new) — `prepareImageForIdentification(photo)`
  takes an expo-camera capture result or an expo-image-picker asset
  (`{ uri, base64, width, height }`), and if the long edge exceeds 1280px,
  uses `expo-image-manipulator`'s `manipulateAsync` to resize (preserving
  aspect ratio) and re-encode as JPEG at `compress: 0.9`, returning the new
  base64. Images already at or under 1280px are returned untouched (no
  pointless re-compression). Added `expo-image-manipulator` as a new
  dependency via `npx expo install` (SDK-57-compatible version resolved
  automatically: `~57.0.17`).
- `src/screens/scan/ScanScreen.js` — both capture paths now call
  `prepareImageForIdentification` before storing/sending a photo: the
  front/back camera captures in `capture()`, and the gallery photo in
  `startUploadedPhotoScan()`. `identifyCoin()` itself, its signature, and
  the persisted-scan/valuation logic are all unchanged — only the bytes
  going *into* the OpenAI call are smaller.
- `server/app.py` (`identify_coin_with_ai`) — logs OpenAI's real
  `usage.input_tokens`/`output_tokens`/`total_tokens` (tagged `[identify]`)
  right after parsing the response body, *before* checking `upstream.ok`,
  so the real per-request cost is captured whether the call succeeds or
  gets rejected (a rejected/429 response may or may not include `usage`;
  the code only logs it when present, no assumption either way). Purely
  additive — no change to the 401/402/429/`quota`/`rate_limit` mapping
  logic itself.

**1280px chosen, not a smaller/"low detail" option, deliberately**: an
alternative considered (and explicitly *not* chosen) was setting OpenAI's
per-image `"detail": "low"` parameter, which gives a small, fixed token
cost regardless of resolution — but low-detail vision inputs are coarse
enough that reading mint marks, dates, and wear (the whole point of this
app) would likely suffer. Resizing to 1280px keeps "auto"/high-fidelity
tiling behavior, just on a smaller source image, trading some token
headroom for not touching identification-quality behavior.

**Not changed**: `REQUEST_TIMEOUT`/`OPENAI_TIMEOUT_SECONDS`, the
401/402/429 → `key_invalid`/`quota`/`rate_limit`/`quota` code mapping in
`identify_coin_with_ai`, `MAX_IMAGE_BYTES` (the byte-size cap, a different
axis from pixel dimensions), and nothing server-side about *when* to call
OpenAI (no retry loop was added here, unlike §14's Supabase gateway retry
— a 429 that's genuinely over a TPM/RPM cap wouldn't be fixed by an
immediate retry the way a one-off Supabase gateway blip is).

**Tests added** (`server/tests/test_app.py`):
- `test_identify_coin_openai_rate_limit_returns_429` — a real upstream 429
  from OpenAI itself (message without "quota"/"billing") maps to our
  `rate_limit` code and still marks the reserved quota attempt as
  `"error"` — this exact path (as opposed to our own `quota_exceeded`) had
  no prior test coverage.
- `test_identify_coin_logs_openai_token_usage_on_success` — a mocked
  Responses API reply carrying a `usage` object produces the
  `[identify] OpenAI usage: input_tokens=...` log line, asserted via
  `assertLogs`.

**Tests**: 39/39 Python passing (37 → 39), 25/25 JS passing (unaffected —
`imagePrep.js` isn't unit-tested; like `src/api/client.js`, it imports a
native Expo module and can't load under plain `node --test`).

**Not yet done**:
- Not verified against a real device/OpenAI call in this session (no
  camera or `OPENAI_API_KEY` available here) — the next real scan's Render
  logs should show a much lower `input_tokens` number, and ideally no more
  `Rate Limit Hit` errors on this tier.
- 1280px and `compress: 0.9` are reasoned defaults, not tuned against a
  real photo → real OpenAI token count. If a rate limit still occurs after
  this, the new usage logging will show whether it's still image-token-
  dominated (tune the constant down further) or something else entirely.

---

## 16. Follow-up change: raised max_output_tokens after a truncated-response bug

**Trigger**: the very next real scan after §15's image-resize fix. Render
logs showed the rate-limit problem was solved (`input_tokens=4584`, well
under the account's TPM caps, no 429), but a *new* failure appeared:
```
[identify] OpenAI usage: input_tokens=4584 output_tokens=1000 total_tokens=5584 status=200
```
...followed by `Coin Not Recognized` / "AI provider returned an empty
response." (HTTP 422, `identification_failure`) in the app.

**Diagnosis**: `output_tokens=1000` exactly equals the `max_output_tokens`
hard cap that was already set in `identify_coin_with_ai`'s payload — the
response was truncated at the token limit before any visible answer was
produced. This is a known behavior with reasoning-capable models: part of
`usage.output_tokens` can be silent "reasoning tokens" spent *before* the
final JSON, and if the cap is too low, the entire budget can be consumed
by reasoning with zero visible output text — which matches the symptom
exactly (not malformed JSON, which would mean *some* text came back;
*empty*, which means none did). `extract_responses_output_text` correctly
returned `None` and the existing `identification_failure` path handled it
without crashing - this was a real product gap (every real, non-mock scan
would likely hit this), not a code bug in the error handling itself.

**Fix** (`server/app.py`, `identify_coin_with_ai`, **not yet committed**):
- `max_output_tokens` 1000 → 2000 — doubles the budget so there's room for
  hidden reasoning *and* the final structured JSON. Chosen to stay
  comfortably under the account's TPM ceiling even combined with the
  §15-resized ~4-5K input tokens (4584 + 2000 = 6584, still well under the
  10,000 TPM floor tier from §15's diagnosis) - deliberately not raised
  further than needed, since more output-token headroom trades directly
  against the same rate-limit budget §15 just fixed.
- Extended the `[identify] OpenAI usage` log line to also report
  `usage.output_tokens_details.reasoning_tokens` (when present) and the
  Responses API's own `status` field, so a future truncation shows the
  reasoning/final-answer split directly instead of just a total.
- Added a new `app.logger.warning` right where `identification_failure` is
  raised for empty output, logging the response's `status` and
  `incomplete_details` (e.g. `{"reason": "max_output_tokens"}`) - this is
  the single most direct diagnostic for "was it truncation, and why."

**Not changed**: the 401/402/429 upstream-error mapping, the
`identification_failure`/422 contract itself (still the correct response
shape for "no usable answer"), and nothing about which model is used or
its reasoning settings (a `reasoning: {"effort": ...}` parameter was
considered to reduce reasoning-token spend directly, but not added -
unclear whether the currently configured `OPENAI_MODEL` accepts that
parameter at all, and guessing wrong could turn a working non-reasoning
model call into a hard 400).

**Tests added** (`server/tests/test_app.py`):
- `test_identify_coin_sends_headroom_for_reasoning_tokens` — asserts the
  outgoing payload's `max_output_tokens` is at least 2000 (a regression
  guard so this can't silently drop back to a too-low value).
- `test_identify_coin_truncated_by_max_output_tokens_logs_incomplete_details`
  — reproduces the exact production shape (`output_tokens` at the cap,
  `output_tokens_details.reasoning_tokens` equal to it, `status:
  "incomplete"`, empty `output`) and asserts it still surfaces as
  `identification_failure`/422 (not a crash), logs the incomplete-details
  warning, and marks the quota attempt `"error"`.

**Tests**: 41/41 Python passing (39 → 41), 25/25 JS passing (unaffected -
no JS files touched).

**Not yet done**:
- Not verified against a real device/OpenAI call in this session. The next
  real scan's Render logs should show a `reasoning=` value in the usage
  line (confirming or ruling out the reasoning-token theory) and, ideally,
  a completed identification instead of another 422.
- If 2000 still isn't enough (e.g. `output_tokens` again lands exactly at
  the cap), the reasoning-token figure logged here will make that obvious,
  and the next lever would be either raising the cap further (watch the
  TPM math from §15) or revisiting the `reasoning.effort` idea once the
  configured model is confirmed to support it.

---

## 17. Investigation + fix: Numista type-vs-issue matching and pricing endpoint

**Trigger**: two different real, non-mock scans (a 2016 Canada 1 dollar,
and the 2012 UK 20 pence from §16) both came back "Estimated Value: Not
available." The user asked whether hooking up PCGS would help, and then
asked for a full investigation per an explicit brief: inspect the exact
query, `score_numista_candidate`, `select_best_numista_match`, the real
logged candidate fields, and the type-detail/pricing assumptions; determine
whether the failure was a search problem, a scoring problem, or a
type-vs-issue problem; do not just lower the confidence threshold.

**Why PCGS wouldn't have helped either failure**: `lookup_pcgs()` only ever
runs off a PCGS cross-reference number that comes from an already-confident
Numista *type* match (`numista_data.get("references")`) - it returns `None`
immediately otherwise. Both failures happened at the Numista *matching*
stage, before there was ever a type to pull a PCGS number from. PCGS is
also almost entirely a US-coins database; neither example coin is American.

**Evidence directly from the two real scans' logs** (not hypothetical -
this is what made root-causing possible without a live Numista key in this
environment):
- Canada query: `search response: query='Canada 1 dollar' ... body={"count":1559,"types":[{"title":"1 Dollar - Elizabeth II (4th Portrait - Rotary Centenary)","issuer":{"code":"australie","name":"Australia"},...},{"title":"1 Dollar - Elizabeth II (...Olympic Team...)","issuer":{"name":"Australia"},...},...`
  - Numista's own free-text relevance search returned **Australian** "1
    Dollar" types ranked ahead of the actual Canadian coin, because the
    2-word query matches the denomination phrase for *any* country.
  - Our own scorer then re-ranked what came back and put Canadian "1 Cent
    - Victoria" (country match, wrong 1800s denomination, score 3) above
    everything, because a bare country-name match (+3) outweighs no match
    at all - it never saw a correctly-denominated Canadian dollar
    candidate score higher, implying one either wasn't in the small
    `count=8` window or didn't literally contain "1 dollar" in its title.
- UK query: `search response: query='United Kingdom 20 pence' ... body={"count":366,"types":[{"title":"20 Cents - Elizabeth II...","issuer":{"name":"Australia"},...},{"title":"25 Pence - Charles III...","issuer":{"name":"Alderney"},...},{"title":"20 Pence - Elizabeth II (Viking Arms and Armour"` (cut off by the 1500-char log truncation before its `issuer` field)
  - Same pattern: non-UK candidates (Australia, Alderney) surfaced ahead of
    what looks like the genuinely correct UK type (id 10799), which then
    only scored 2 (denomination-only) in our own ranking - its `issuer`
    field was truncated out of the log, so whether it failed the country
    check for a real reason or a logging-truncation artifact could not be
    confirmed from existing logs alone. This is exactly why fuller
    candidate logging (added below) was necessary, not optional.

**Independent, code-level confirmation of a third root cause** (not
inferable from our logs at all): `fetch_numista_price` was calling
`GET /types/{id}/prices`. Numista's docs (`en.numista.com/api/doc/...`)
are Cloudflare-blocked from this sandbox and the schema endpoint
(`api.numista.com/api/doc/swagger.yaml`) requires an API key we don't have
here, so this was verified instead against a hand-written third-party
Python SDK (`namachieli/numista-api-sdk` on GitHub) whose source explicitly
builds requests from Numista's own `swagger.yaml` (`API_SCHEMA_URL` in its
source) - its `getPrices()` method builds
`f"/types/{type_id}/issues/{issue_id}/prices"`, and it separately confirms
a `GET /types/{type_id}/issues` endpoint exists (`getIssues()`) distinct
from `GET /types/{type_id}` (`getType()`). This matches the user's own
architectural hint exactly: **pricing is issue-specific, not type-level**.
Every real scan that reached the pricing stage - regardless of matching
quality - was hitting a URL that doesn't match Numista's real API.

**Root cause: a combination, all three categories, not one**:
- **(A) Search** - confirmed directly from real log bodies: Numista's own
  relevance ranking for a bare `"{country} {denomination}"` query does not
  reliably surface the correct country's match near the top of even a
  modest `count=8` window.
- **(B) Scoring** - likely a contributing factor (title-substring matching
  is brittle against real Numista title conventions - e.g. a type titled
  just "Dollar" rather than "1 Dollar" would silently lose the
  denomination-match points), but not fully confirmed for the UK case
  specifically due to log truncation cutting off the one candidate that
  mattered.
- **(C) Type-vs-issue** - confirmed independently of the two real scans,
  via the third-party SDK's source: the pricing endpoint was simply wrong,
  and a type's own min/max-year range is not a substitute for checking a
  specific issue.

**Fix** (`server/app.py`, commit `1d07df6`, **not yet pushed**) - replaces
score-and-threshold matching with score-to-shortlist, then require-a-real-
issue matching, per the user's specified flow (search -> rank -> inspect
top few types' real issues -> require an issue matching the year, mint
mark to disambiguate -> select type+issue -> fetch prices for that issue):
- `score_numista_candidate` is now backed by
  `_score_numista_candidate_breakdown`, which returns *why* a candidate
  scored what it did (a dict of named components), not just a number.
  `resolve_numista_type_and_issue` logs this breakdown, plus the exact
  `cand_country` text compared, for **every** candidate returned by the
  search (not just the top 3 as before) - the single change that makes
  the next real scan's failure mode (A vs. B) conclusively diagnosable
  instead of inferred from partial log excerpts.
- New `fetch_numista_issues(type_id)` calls the now-confirmed
  `GET /types/{id}/issues` and logs the response + the years found.
- New `_issue_matches_year` (exact year, or within an issue's own
  min/max range) and `_issue_mint_text`/`_select_issue_for_year` (mint
  mark used only to disambiguate multiple same-year issues, never as a
  hard requirement - not every denomination carries one).
- New `resolve_numista_type_and_issue`: scores all candidates, takes the
  top `NUMISTA_MATCH_CANDIDATES_TO_INSPECT` (3) scoring at least
  `NUMISTA_MATCH_MIN_SCORE` (2), and for each (in score order) fetches its
  issues and requires one to match the identified year. **The first one
  with a real matching issue wins - even if a different, higher-scored
  candidate was checked first and rejected.** This directly fixes the
  observed failure mode: a wrong-era title match that scores well no
  longer wins just because of its score. If nothing among the inspected
  candidates has a matching issue, the result is `(None, None)` -
  unavailable, never invented, same honesty guarantee as before.
- `fetch_numista_price(type_id, issue_id, grade)` now takes an
  `issue_id` and calls the issue-scoped URL; `estimate_value` requires
  both a `numista_type_id` and `numista_issue_id` before attempting a
  price lookup.
- `search_numista_types`'s `count` raised 8 -> 12 (still one search call;
  gives the new inspect-top-3 step a wider net, directly addressing the
  (A) search-window evidence above).
- `_numista_result_list` now also unwraps a bare list or an `"issues"` key
  (previously only `"types"`/`"items"`/`"results"`), since the issues
  endpoint's exact wrapper shape is unconfirmed without a live key.

**Explicitly not done, per the brief**: the confidence threshold number
itself (a bare title/country score of 3) was **not** lowered or removed as
an acceptance rule - it no longer exists as an acceptance rule at all,
replaced by a strictly more rigorous factual check (a real issue for the
identified year). `NUMISTA_MATCH_MIN_SCORE` (2) is a *pre-filter* for
which candidates are worth an extra HTTP call, not an acceptance
threshold - a candidate can score 2 and still be correctly selected (as
the UK-style candidates would be), and a candidate can score 7 and still
be correctly rejected (as demonstrated by the new regression test). Also
not done: OpenAI identification, auth/quota/persistence/badges/leaderboard,
and no new database columns (none were needed - `numista_issue_id` lives
only in the in-memory `numista_data` dict passed between functions within
one request, not persisted).

**Numista endpoints actually confirmed** (via the third-party SDK's
source, cross-referenced against our own real logged responses where
possible):
- `GET /types` (search) - `q`, `issuer`, `category`, `page`, `count`,
  `lang` (default `en` - ruling out an earlier locale hypothesis about
  country-name mismatches). Our own real log bodies already confirm the
  response shape (`{"count", "types":[{"id","title","issuer":{"code","name"},"min_year","max_year",...}]}`).
  **Not used yet**: the `issuer` param (issuer code) would let us filter
  search by country precisely instead of relying on free-text ranking -
  deliberately deferred (see below), not forgotten.
- `GET /types/{id}` - full type detail (`fetch_numista_type_detail`,
  unchanged).
- `GET /types/{id}/issues` - **newly added**, confirmed to exist via the
  SDK; its exact response field names (`year` vs. a date range, mint
  field name) are **still unconfirmed against a live response** - this is
  exactly what the new `[numista] issues response`/`issues inspected` log
  lines will reveal on the next real scan that reaches this step.
- `GET /types/{id}/issues/{issue_id}/prices` - **corrected from the old,
  wrong `/types/{id}/prices`** - confirmed via the SDK; the `prices` array
  shape (`grade`/`price` fields) is carried over as a reasonable
  assumption from before, not yet confirmed live either.
- Numista's own documentation site (`en.numista.com/api/doc/...`) and
  schema endpoint (`api.numista.com/api/doc/swagger.yaml`) could **not**
  be fetched directly in this session (Cloudflare block / requires an API
  key this sandbox doesn't have) - all of the above is corroborated
  through the third-party SDK's source code, not a first-party call.

**Deferred (V2) idea, not implemented**: using `searchTypes`'s `issuer`
parameter to filter search by Numista's own issuer code instead of
free-text country matching would likely fix the (A) search-ranking
problem more directly than a wider `count`. Not done here because it
requires either a maintained country-name -> Numista-issuer-code mapping
(risk of a wrong guess *silently* returning zero results, since `issuer`
is a strict filter) or an extra live `/issuers` lookup call per scan -
both real design decisions better made with a live key in hand, and out
of scope for "smallest robust V1."

**Tests added** (`server/tests/test_numista.py`, new file, 17 tests):
scoring-breakdown correctness (including the real Australian-"1 Dollar"
false-country-credit scenario), `_issue_matches_year`/`_select_issue_for_year`
(exact year, range, no match, mint-mark disambiguation, mint-unspecified
fallback), and - the core regression guard -
`test_prefers_issue_confirmed_candidate_over_a_higher_scored_wrong_one`,
which constructs a wrong-era candidate that deliberately outscores the
correct one (mirroring the real title-omits-the-leading-"1" scoring gap
hypothesized above) and asserts the issue check still picks correctly;
plus a candidate-cap bound test, the corrected price-URL test, and two
`lookup_numista` integration tests.

**Tests**: 58/58 Python passing (41 -> 58), 25/25 JS passing (unaffected -
no JS files touched).

**Housekeeping note**: this commit (`1d07df6`) was staged with a plain
`git add server/app.py`, which - unlike earlier commits in this session -
did **not** carve out the pre-existing, unrelated `DAILY_SCAN_LIMIT`
5→20 default-value change still sitting in the working tree since before
this session started. That line was already swept into the earlier
`5747051` commit (`max_output_tokens` fix) by the same oversight and is
already pushed. Flagging this for transparency, not because it's harmful
(it's the user's own pre-existing edit and a plausible intentional
default) - just that the "keep unrelated changes separate" discipline
slipped for that one line partway through the session.

**Exact next real coin test to perform**: scan a **common, undamaged,
well-known coin** (ideally one where the AI's country/denomination/year
are all clean) - the two coins tried so far were both somewhat
unusual/damaged (a worn/mint-error-flagged UK 20p, and whatever made the
Canadian dollar not resolve), which may itself be contributing to weak
Numista search relevance. Concretely, read the Render logs for, in order:
1. `[numista] all candidates scored: ...` - check whether the correct
   type is present at all among the (now up to 12) candidates, and if so,
   whether its score reflects a real country+denomination match. Presence
   with a low score = confirms (B); absence entirely = confirms (A).
2. `[numista] issues response ...` / `issues inspected: ... years=...` -
   confirms the real field shape of an issue record (does `year` exist as
   named, or is it a min/max range? is there a mint field, and what is it
   called?).
3. `[numista] selected type+issue: ...` - confirms resolution worked
   end-to-end.
4. `[numista] price response: type_id=... issue_id=... ... body=...` -
   the first-ever real confirmation of the issue-scoped price endpoint's
   actual response shape, since neither real scan so far has reached
   pricing.
If step 1 shows the correct type present but scoring low specifically
because its title omits a leading "1" (or similar formatting variance),
that confirms hypothesis (B) concretely and would justify a follow-up:
normalizing denomination text (e.g. also trying without a leading "1 ")
before the substring check.

---

## 18. Follow-up change: diagnostics for OpenAI 429/error responses

**Trigger**: explicit follow-up request to improve diagnostics for
upstream OpenAI non-2xx responses (429 especially), without changing
retry behavior or the user-facing API contract. Prior to this, a 429 from
OpenAI logged nothing at all beyond the generic `CoinLensError` - the
existing `[identify] OpenAI usage` log line only fires when a `usage`
field is present in the response body, and a rejected/rate-limited
request typically has no `usage` field (the request never got processed).

**Fix** (`server/app.py`, commit `41abbf9`, pushed): added
`_log_openai_error_response(upstream)`, called immediately after the
`requests.post` call whenever `not upstream.ok` - **before** the
`upstream.json()` parse step, so it still logs even for a non-JSON error
body (a plain-text gateway error, for example). Logs:
- HTTP status code.
- Only the standard OpenAI rate-limit headers that are actually present
  (`x-request-id`, `x-ratelimit-limit-requests`,
  `x-ratelimit-remaining-requests`, `x-ratelimit-reset-requests`,
  `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`,
  `x-ratelimit-reset-tokens`, `retry-after`) - never a synthesized `None`
  entry for one that wasn't sent.
- A sanitized/truncated response body (`OPENAI_LOG_BODY_CHARS = 1500`,
  matching the truncation length already used for Numista logging
  elsewhere in this file) - with a defense-in-depth regex redaction of any
  long base64-looking run (100+ base64 characters) as `<redacted-base64>`,
  in case an error body ever echoed request content back.

**Explicitly unchanged, per the brief**: the 401/402/429 ->
`key_invalid`/`quota`/`rate_limit` mapping logic, retry behavior (there is
none here, same as before), and every other part of the
`/api/identify-coin` contract. This is purely an additive diagnostic log
statement.

**Never logs**: the `Authorization` header, `OPENAI_API_KEY`, or any
request payload (front/back image data) - the logging function only ever
reads from the *response* object (`upstream.status_code`/`.headers`/
`.text`), never touches the request side at all, so there's no code path
by which a secret or an image could reach this log line.

**Tests added** (`server/tests/test_app.py`):
- `test_identify_coin_logs_openai_429_headers_and_body` - all 8 rate-limit
  headers present on a real 429 all appear in the log line, verbatim.
- `test_identify_coin_openai_error_logging_omits_absent_headers` - only
  `retry-after` sent -> only `retry-after` appears in the log; none of the
  other 7 header names appear.
- `test_identify_coin_openai_error_logging_never_leaks_secrets_or_images` -
  a distinctive API key value and a 500-character fake base64 blob (both
  intentionally set up to be present in the mocked response/environment)
  never appear in the log line verbatim; the blob shows up redacted as
  `<redacted-base64>` instead.
- Also **fixed** a latent gap in the pre-existing
  `test_identify_coin_openai_rate_limit_returns_429`: its mock `Response`
  never set `.text`/`.headers`, so accessing `.text` returned an
  auto-generated `Mock` object instead of a string - once the new logging
  code actually read `.text`, this crashed with a generic 500 instead of
  the expected 429. This was a test-mock gap, not a real code bug (a real
  `requests.Response` always has string `.text` and a real `.headers`
  dict); fixed by setting both explicitly on the mock.

**Tests**: 61/61 Python passing (58 -> 61), 25/25 JS passing (unaffected -
no JS files touched).

**Not yet done**: not verified against a real OpenAI 429 in this session
(would need to actually trigger one against the live low-tier account
again) - the next real rate-limit hit should now show a
`[identify] OpenAI error response: http_status=429 headers={...}
body=...` line in Render logs with the account's real rate-limit window
state (remaining requests/tokens, reset timers), which is the whole point
of this change.

---

## 19. Follow-up change: propagate OpenAI's real retry-after to the rate_limit UI

**Trigger**: a real OpenAI 429 came back with `retry-after: 11042` (~3
hours), but the app always said "Wait 30 seconds and try again" regardless
- a hardcoded, inaccurate wait time for `rate_limit` specifically (not
`quota_exceeded`, which is CoinLens's own separate daily limit).

**Backend error contract, before vs. after** (`server/app.py`, commit
`9bc4a87`):
```
before: {"error": {"code": "rate_limit", "message": "..."}}
after:  {"error": {"code": "rate_limit", "message": "...", "retry_after_seconds": 11042}}
```
`retry_after_seconds` is present only when OpenAI's `retry-after` header
parses to a positive integer; otherwise the field is simply absent (never
`null`, never a guessed value) and every other error's JSON is unchanged.
`CoinLensError` gained an optional `details` dict merged into the body -
unused by every other `CoinLensError` call site, so this is additive only.

**UI behavior** (`scanErrorLogic.js`/`src/api/client.js`, `rate_limit`
only; `ScanScreen.js` needed **zero changes** - its button was already
driven generically by the existing `retryable` field):
- `<=60s`: "Try again in about N seconds." + **Try Again**.
- `>60s, <3600s`: "Try again in about N minutes." + **Back to Home**
  (existing reset-and-navigate-home path, no API call, no camera reopen).
- `>=3600s`: "Try again in about N hours." + **Back to Home**.
- missing/malformed retry-after: "Wait a short time and try again." +
  **Try Again** (never claims a false specific wait time).

**Confirmed unchanged**: `quota_exceeded` behavior (still its own
Back-to-Home path, untouched), `DAILY_SCAN_LIMIT`/`api_usage`/quota
accounting (nothing here touches quota reservation or "refunds" an
attempt), OpenAI request payload/image preprocessing, auth, persistence,
Numista, PCGS, mock mode, and the existing §18 429 diagnostic
header/body logging (left fully intact - this task only adds a second,
narrower thing derived from the same response: the parsed retry-after,
returned to Expo rather than only logged server-side).

**Tests**: 67/67 Python passing (61 -> 67, 6 new: 30s/300s/11042s
propagated, missing/malformed header omits the field without crashing,
org/project id + x-request-id + raw body + token counts confirmed never
reaching Expo). 31/31 JS passing (25 -> 31, 6 new: the three time buckets,
the missing-header fallback, and explicit confirmation that
`quota_exceeded` and another normal error's behavior are unaffected).

**Not yet done**: not verified against a real OpenAI 429 in this session
(no live key here) - the next real rate-limit hit should show
`retry_after_seconds` in the JSON response and the matching bucketed UI
text/button on device.

---

## 20. Follow-up fix: Numista issuer-code search + ambiguous-match guard

**Trigger**: a real 2012 UK 20 pence scan narrowed §17's problem further.
Free-text search (`q="United Kingdom 20 pence"`) returned 12 candidates,
mostly **Isle of Man** 20 Pence types. The §17 issue-year validation
worked exactly as designed - candidates 10799/92170/92171 each only had
1982/1983 issues, none matched 2012, all correctly rejected, valuation
correctly stayed unavailable. The remaining gap: free-text search itself
wasn't giving the real UK match a fair shot at appearing as a plausible
candidate at all.

**Numista issuer endpoint/response shape found**: `GET
https://api.numista.com/api/v3/issuers` returns issuer records shaped
like `{"code": "...", "name": "..."}` (via a third-party SDK + community
sources, matching the same `{"count":..., "<key>":[...]}` wrapper
convention already empirically confirmed for `/types` search) - **not
confirmed against a live response** in this session (no key here). The
exact `/types` search `year` parameter's real name is also unconfirmed
first-party (Numista's docs are Cloudflare-blocked, no live key) - a
third-party Apify wrapper's own input schema uses `minYear`/`maxYear`
naming, which hints the real param might not be a bare `year`. Given
that risk, `year` is passed to `/types` search only as a low-risk
*hint* - if Numista ignores or mis-handles it, the existing issue-level
year check (confirmed correct, per this bug report) still catches
everything; it isn't relied on as a correctness gate.

**How issuer resolution works** (`server/app.py`):
`resolve_numista_issuer_code(country_text)` normalizes the AI's country
string (lowercase), applies a tiny alias map (`uk`→`united kingdom`,
`usa`/`us`→`united states`), then looks it up in a name→code index built
from `fetch_numista_issuers()` - **never a hardcoded issuer code**. The
index is cached in-process for 24h (`_numista_issuer_name_index`, module
globals, no DB table) so a scan doesn't refetch the full issuer list
every time. Any failure (fetch error, no match) returns `None` and is
treated as "use the fallback search," never a fatal error for the scan.

**Primary (structured) search params**: `q=<denomination>`,
`issuer=<resolved code>`, `year=<int>` (only if numeric), `category=coin`,
`count=12` - country name deliberately **not** duplicated in `q` once an
issuer code is supplied.

**Fallback search params** (used when issuer resolution fails, or the
structured search errors/returns zero candidates - logged either way with
why): `q=<denomination>`, `year=<int>` (if available), `category=coin` -
still no free-text country, so it can't reintroduce the original
wrong-country-ranking problem; both paths feed the same unchanged
scoring → shortlist → per-candidate `/issues` → require-a-year-match
pipeline from §17.

**New safety net**: `resolve_numista_type_and_issue` now inspects *every*
shortlisted candidate's issues (not just the first hit) before deciding -
if more than one has a real matching issue for the identified year, it
returns unavailable rather than picking by score. "Confident" now means
*exactly one* candidate survives the factual check.

**Files changed**: `server/app.py` (issuer cache/resolution, rewritten
`search_numista_types`, ambiguity check in `resolve_numista_type_and_issue`,
`_numista_result_list` now also unwraps an `"issuers"` key),
`server/tests/test_numista.py` (13 new tests).

**Not changed** (confirmed): OpenAI identification, quota/rate-limit
handling, the §19 retry-after work, Supabase persistence, auth, badges,
leaderboard, PCGS, scan schema, mock mode (explicitly tested unaffected).

**Tests**: 80/80 Python passing (67 → 80), 31/31 JS passing (unaffected,
no JS touched). Commit `fa2f3bc`, pushed.

**Exact next real scan to run**: the same 2012 UK 20 pence coin again (or
any UK coin), and read Render logs in order: `[numista] issuer
resolution: AI country='United Kingdom' resolved issuer code=...` (does a
real code resolve, and is it right?), `[numista] search params: ...`
(structured attempt), `[numista] candidate count=... (structured
search)` (did issuer-scoped search actually surface the real UK 20p type
this time, instead of Isle of Man?), then the existing `[numista] all
candidates scored`/`issues inspected`/`selected type+issue` lines through
to a price lookup - the first real end-to-end confirmation of the whole
pipeline, including the still-unverified `/types/{id}/issues/{issue_id}/prices`
response shape from §17.

---

## 21. Two small fixes: doubled grade disclaimer + redundant log-scan call

**Trigger**: the user reported two issues from the same real UK 20p scan
session: (1) the result summary showed the grade disclaimer twice back to
back, e.g. "Estimated grade: VF-25 (visual estimate; not professionally
certified) (AI visual estimate, not a professional certified grade)."; (2)
`/api/log-scan` was still being called client-side after
`/api/identify-coin` had already persisted the authoritative scan to
Supabase - flagged as "legacy behavior worth auditing later... not
blocking Numista testing," but grouped under "also fix these."

**Fix 1 - doubled disclaimer** (`server/app.py`, `build_coin_summary`):
`IDENTIFICATION_PROMPT` already instructs the AI to embed its own "visual
estimate, not a professional certified grade" wording directly inside
`estimated_grade` (confirmed - every real scan this session shows the AI
doing exactly that, e.g. "VF-30 (visual estimate; not professionally
certified)", "VF-20 (visual estimate; affected by heavy wear and
damage)"). `build_coin_summary` was *also* appending its own hardcoded
"(AI visual estimate, not a professional certified grade)" after the
grade - stacking a second disclaimer on top of the AI's own. Now just
emits `f"Estimated grade: {grade}."`, trusting the AI's own wording (which
the prompt already requires). Mock mode is unaffected - it uses a
separate hardcoded `MOCK_SUMMARY` constant, not `build_coin_summary` at
all.

**Fix 2 - redundant log-scan call** (`src/screens/scan/ScanScreen.js`):
removed both `logScanToSheet(coinData, user?.name)` call sites (camera and
gallery flows) and the now-unused `logScanToSheet` import from
`../../api/client`. This was a pre-Supabase-migration write to a
SheetDB-backed sheet (`POST /api/log-scan`), redundant since
`/api/identify-coin`'s response already reflects the authoritative
Supabase-persisted row (`scan_row` returned in the body, `onScanSaved?.()`
already triggers the Supabase-backed `refreshScans()` in `Root.js`).

**Side effect flagged, not fixed (out of scope)**: `AdminScreen.js` still
does `GET /api/scans`, which reads the *same* SheetDB sheet `log-scan` used
to write to - its "Total Scans"/per-user breakdown will stop growing with
new scans as a result of Fix 2. This isn't a *new* inconsistency:
`AdminScreen.js` was never part of the Supabase migration described in
§1a (it still separately merges in legacy `AsyncStorage` scan history
too) and was already out of step with the rest of the app, which reads
scan history straight from Supabase (`src/api/scans.js`). A real fix would
point `AdminScreen` at Supabase like everything else - not done here,
flagged for whenever that screen gets attention. Neither the
`/api/log-scan` nor `/api/scans` Flask routes themselves were touched or
removed.

**Tests added** (`server/tests/test_app.py`): `build_coin_summary` no
longer duplicates a disclaimer the AI already included, and still shows a
bare grade cleanly when the AI didn't include one.

**Tests**: 82/82 Python passing (80 → 82), 31/31 JS passing (unaffected -
`ScanScreen.js` isn't unit-tested, same reason as always: it imports
React Native). Commit `124344c`, pushed.

**Not changed**: OpenAI identification, Numista/PCGS, quota/rate-limit
handling, retry-after work, Supabase persistence itself, auth, badges,
leaderboard, scan schema.

---

## 22. Follow-up fix: prefer standard-circulation Numista variant on a year tie

**Trigger**: the §20 issuer-resolution fix worked - a real 2012 UK 20 pence
scan's structured search returned three real candidates, all with a valid
2012 issue: a non-circulating 1/10oz fine-silver type (29106), the
standard circulation type (5628, "Royal Shield"), and a silver-proof
variant of it (208022). The §17 ambiguity guard correctly refused to guess
between them and reported unavailable - correct per its own rules, but
leaving an obvious win on the table: for an ordinary circulating coin, the
right answer among these three is usually clear from information Numista
already returns.

**Exact variant-ranking rule** (`server/app.py`):
`looks_special_or_proof(candidate)` - true when a candidate's
`object_type.name` is anything other than `"Standard circulation coins"`,
**or** its title mentions `proof` / `fine silver` / `fine gold` / `bullion`
/ `specimen` / `commemorative` / `platinum`. Deliberately does **not**
trigger on bare `"silver"`/`"gold"` in a candidate's title - plenty of
genuinely standard circulation coins are historically silver or gold
(e.g. pre-1947 British coinage), and object_type already catches the
modern non-circulating/commemorative cases those bare words were meant to
flag. `ai_indicates_special_variant(identification)` - true when the AI's
own `description`/`special_notes`/`coin_name`/`varieties`/`estimated_grade`
text mentions `proof`/`silver`/`gold`/`platinum`/`bullion`/`specimen`/
`commemorative` (the fuller word list, including bare metal names, is safe
here since a live AI describing an ordinary coin essentially never says
"silver"/"gold" unless it actually means it).

**Whether an existing helper was reused**: no - despite the task
suggesting to check for an existing `looks_special_or_proof()`, none
existed before this change; both classifier functions were built fresh,
reusing only the existing `_text_of()` string-normalization helper.

**Where it plugs in** (`resolve_numista_type_and_issue`, unchanged
ordering otherwise): after the year/issue gate produces its `matches`
list (the mandatory, untouched correctness check), if there's still a tie
**and** the AI didn't itself flag a special variant, narrow `matches` to
whichever aren't `looks_special_or_proof` - but only when at least one
non-special candidate exists; if the narrowed set has exactly one entry,
that's the answer, if it still has 2+ (two circulation-type candidates
still tied) it falls straight through to the existing ambiguous ->
unavailable path unchanged. When the AI *did* flag something special, the
narrowing step is skipped entirely (never force-selects circulation on
the AI's behalf) and the original tie stands, going to the same
ambiguous -> unavailable path.

**Regression test result for the UK 2012 20p**: passes -
`test_uk_2012_20p_regression_prefers_standard_circulation_type_5628` feeds
the exact three real candidates (ids 29106/5628/208022) with an ordinary,
non-special AI description and asserts type **5628 wins**, with issue
`iss-5628-2012`.

**Other new tests, all passing**: AI explicitly saying "silver proof"
does *not* auto-select circulation (stays ambiguous/unavailable, asserted
both as "not 5628" and as the actual `None, None` result); two standard-
circulation candidates that are themselves still tied stay unavailable
(no false narrowing to a single winner); the standard-circulation type
itself lacking a 2012 issue (only the proof variant has one) still
correctly selects the proof one - proves the year/issue gate still wins
over "prefer the ordinary one" when there's no ordinary match to prefer;
plus direct unit tests for both classifier functions.

**Files changed**: `server/app.py` (two new module-level keyword tuples +
two new functions + the narrowing step inserted into
`resolve_numista_type_and_issue`), `server/tests/test_numista.py` (7 new
tests, one new `VariantDisambiguationTests` class).

**Not changed** (confirmed by re-running the full suite unmodified):
OpenAI prompt/schema, issuer lookup (§20), structured search (§20), issue
fetching (§17), auth, quota/rate-limit handling (§18/§19), persistence,
badges/leaderboard, PCGS, scan schema.

**All test results**: 89/89 Python passing (82 → 89, 7 new). 31/31 JS
passing (unaffected - no JS files touched). Commit `3c2a4f3`, pushed.

**Exact next live scan to perform**: the same 2012 UK 20 pence coin (or
any other UK coin) again. Render logs should now show, after the usual
`[numista] all candidates scored`/`issues inspected` lines, a new
`[numista] variant disambiguation: preferring 1 standard-circulation
candidate(s), deprioritizing special-variant match(es): [...]` line
naming the fine-silver and silver-proof candidates as deprioritized,
followed by `[numista] selected type+issue: type_id=5628 ...` and -
finally, for the first time across every real scan so far this session -
an actual `[numista] price response: type_id=5628 issue_id=...` line,
giving the first real confirmation of the still-unverified
`/types/{id}/issues/{issue_id}/prices` response shape from §17.

---

## 23. Follow-up fix: canonical denomination matching + issue-level variant preference

**Trigger**: the §22 fix worked (type 5628 selected correctly for one real
scan), and the very next real UK 2012 20p scan narrowed the problem
further. OpenAI returned denomination `"Twenty pence"` (word form, not
`"20 pence"`). The scorer's denomination check was a raw substring match,
so `"twenty pence"` never matched any Numista title text at all - not
"20 Pence", not "2 Pence", not "50 Pence" - meaning all three scored
identically on country+year alone, and the correct type 5628 stayed
ambiguous with an unrelated type 4039 ("2 Pence"). Separately, once 5628
itself resolves, it has *three* 2012 issues (144284 ordinary, 520198 "BU",
180337 "Proof") that also needed disambiguating.

**Denomination normalization rule** (`server/app.py`):
`normalize_numista_denomination(text)` canonicalizes to `"<digits>
<unit>"` - a small number-word map (one..ninety, hundred, plus simple
compounds like "twenty five") converts word numbers to digits, and a
narrow currency-unit alias map collapses only semantically-safe
singular/plural pairs (`penny`/`pence` -> `pence`, `cent`/`cents` ->
`cent`, `dollar`/`dollars` -> `dollar`, etc.) - deliberately not a general
NLP normalizer, and deliberately **exact-match, never fuzzy**: "2
pence"/"20 pence"/"50 pence" always canonicalize to different strings.
`_numista_title_denomination(title)` extracts a candidate's own
denomination using Numista's `"<denomination> - <series>"` title
convention (the part before the first `" - "`). The existing
`denomination_in_title` scoring key (name kept for compatibility) now
computes via canonical equality instead of a raw substring check.

**Where it plugs in**: `resolve_numista_type_and_issue` gained a new
narrowing step - inserted **before** the existing object_type-based
variant narrowing from §22 - that, when `matches` are still tied after
the year/issue gate, narrows to whichever have the exact canonical
denomination the AI identified. This is what actually lets 5628 "outrank"
4039: the score alone doesn't gate which candidates enter `matches` (only
the coarse `NUMISTA_MATCH_MIN_SCORE`/top-3 cap does), so an explicit
denomination-equality filter was needed, not just a corrected score.
Mirrors the same "narrow by an exact categorical property, never by raw
score" pattern already used for object_type.

**Issue-level variant rule**: `_select_issue_for_year` now prefers,
among same-year issues, whichever has no special `comment`/`finish`/
`description` text (checked via `_looks_special_issue`, matching whole
words only - `{"proof","bu","specimen","pattern","prooflike","matte"}` -
so short keywords like "bu" can't false-positive inside unrelated words
like "about"). Reuses the *same* `ai_indicates_special_variant()` check
from §22's type-level logic: if the AI itself said proof/BU/special, the
ordinary-preference narrowing is skipped entirely (never force-selects
the ordinary issue on the AI's behalf). If narrowing still leaves more
than one ordinary issue (or, when AI-indicated-special, more than one
issue overall), returns `None` - which correctly makes that *type*
register as "no matching issue" one level up, same effect as
type-level ambiguity.

**A pre-existing test's expectation was itself the bug being fixed**:
`test_select_issue_falls_back_to_first_year_match_when_mint_unspecified`
asserted that two indistinguishable issues (different mints, no mint info
available) resolved by blindly picking the first one in list order -
exactly the kind of silent guess this whole matching pipeline has been
built to eliminate. Renamed and changed to assert `None` (ambiguous)
instead, since that's now the correct, honest behavior.

**UK 2012 20p regression result**: passes, at both levels -
`test_uk_2012_20p_regression_with_ai_wording_twenty_pence_outranks_2_pence`
confirms the score comparison (20 Pence scores 5, both 2 Pence and 50
Pence score 3) *and* that `resolve_numista_type_and_issue` now resolves
to type 5628 end-to-end from AI wording `"Twenty pence"`;
`test_ordinary_grade_prefers_the_plain_circulation_issue_over_bu_and_proof`
confirms issue 144284 wins over 520198 (BU) and 180337 (Proof) for an
ordinary VF-25 identification.

**Test totals**: 101/101 Python passing (89 → 101, 12 new). 31/31 JS
passing (unaffected - no JS touched). Commit `55bc51e`, pushed.

**Not changed** (confirmed): OpenAI prompt/schema, issuer lookup/cache,
structured Numista search, candidate count, type-level special-variant
filtering (§22, untouched logic, just reused its AI-intent check), auth,
quota/rate-limit/retry-after logic (§18/§19), persistence,
badges/leaderboard, PCGS, DB schema.

**Exact next live scan expected path**: the same 2012 UK 20 pence coin (or
any UK coin whose AI-reported denomination uses word form, e.g. "Twenty
pence"/"Fifty pence") again. Render logs should now show, in order:
`[numista] all candidates scored: ...` (2 Pence/20 Pence/50 Pence-style
candidates with *different* scores this time, 20 Pence higher) ->
`[numista] denomination disambiguation: narrowing to 1 candidate(s)
matching denomination='20 pence', dropping: [...]` -> the existing
`[numista] selected type+issue: type_id=5628 ...` -> and, if that type has
multiple 2012 issues in real Numista data, a clean resolution to the
ordinary one without an explicit new log line (the choice happens inside
`_select_issue_for_year`, not separately logged at the level `resolve_numista_type_and_issue`
logs at) -> finally, for the first time this session, a real
`[numista] price response: type_id=5628 issue_id=...` line, confirming
the still-unverified issue-price endpoint's actual response shape (open
since §17).

---

## 24. Investigation: live UK 2012 20p regression could not be reproduced

**Trigger**: the user reported a live scan where type 5628 (the correct UK
20p type, per §23's fix) was rejected with `"no issue matches
year='2012'"` even though Numista returned three real 2012 issues for it
(144284 ordinary, 520198 "BU", 180337 "Proof") - apparently contradicting
the §23 unit tests, which claimed this exact scenario resolves correctly.

**What was done**: per explicit instruction to trace the exact predicate
before guessing a fix, reproduced the live evidence *verbatim* - the
exact issue dicts (including `is_dated`/`gregorian_year`/`mintage` fields
the existing simplified test fixtures didn't include) and the exact AI
identification (`country="United Kingdom"`, `denomination="20 pence"`,
`year="2012"`, `grade="VF-20"`, `description="ordinary circulating coin,
normal wear/scratches"`) - first via a standalone script calling
`_select_issue_for_year` directly, then via the full
`resolve_numista_type_and_issue` end-to-end with all three real
candidates (29106 Fine Silver, 5628 standard circulation, 208022 Silver
Proof). **Both reproductions correctly selected type 5628 / issue 144284
with the code as it stood at commit `55bc51e`** - the failure described
could not be made to happen with the exact data given. Traced through
every predicate the task asked about (year comparison, `None`/empty-string
mint-mark handling, missing-`comment` handling, whether the issue-level
helper requires a field to exist) and each behaves correctly; none
explain the reported live behavior.

**Most likely explanation, not provable from here**: either (a) the live
scan ran against a Render deployment that hadn't yet picked up the §23
push (the fix landed the same session, and Render deploys are not
instant), or (b) the real AI `description`/`special_notes` text contained
something not captured in the user's paraphrase - e.g. a *negated* mention
of a special keyword (a live AI often phrases things like "not a proof
strike" or "no evidence of a proof/specimen finish" when explicitly ruling
a special variant *out*), which `ai_indicates_special_variant`'s naive
substring keyword check would misread as a *positive* signal, since it
has no negation handling. That function is shared with the §22 type-level
logic and explicitly off-limits for this task ("do not touch... type-level
variant rules"), so even if (b) is the real cause, it could not be fixed
here without violating that scope boundary - flagged for a possible
future task explicitly scoped to include that shared function.

**Fix made regardless, per the explicit task requirements** (`server/app.py`,
commit `c62706a`):
- `_select_issue_for_year` now returns `(selected_issue, reason)` instead
  of just the issue. `reason` is `None` on success or a specific string:
  `"no issue matches year"`, `"year matched but multiple ordinary issues
  remain indistinguishable"`, `"year matched but AI indicated a special
  issue and multiple candidates remain ambiguous"`, or `"year matched but
  no compatible ordinary/mint variant remained"`. `resolve_numista_type_and_issue`
  now logs the *real* reason instead of the old single generic message,
  which the task correctly identified as misleading whenever a year
  match existed but was filtered out for an unrelated reason.
- New per-issue diagnostic logging (kept permanently, not temporary - one
  concise line per year-matching issue): `[numista] issue evaluation:
  type_id=... issue_id=... year_match=true mint_match=... special=...
  comment='...' decision=accepted|rejected (...)`. This is what will
  give ground truth on the very next live scan if the bug is real and
  environment-specific.
- `_select_issue_for_year` gained an optional `type_id` param (for the
  new logging only) - all 6 existing direct-call test sites needed
  updating to unpack the new `(issue, reason)` return value.

**New regression test** (`server/tests/test_numista.py`): uses the exact
live issue response shape (including `is_dated`/`gregorian_year`/
`mintage`) with the exact live identification fields, asserting issue_id
144284 wins - passes against current code, serving as a permanent guard
against this exact real shape (as opposed to the simplified dicts used by
older tests in this file).

**Tests**: 102/102 Python passing (101 → 102). 31/31 JS passing
(unaffected - no JS touched). Confirmed unchanged (re-ran the full suite
unmodified): OpenAI, Numista structured search, issuer cache, denomination
scoring, type-level variant disambiguation (§22), price parsing, auth,
quota/rate-limit, persistence, frontend, database.

**Confirmed next expected live path**: type 5628 → issue 144284 → price
endpoint - **assuming this was a deployment-timing artifact**, which is
the best-supported explanation given the reproduction attempts. If the
*next* live scan still rejects 5628, the new `[numista] issue evaluation`
log lines will show the exact `mint_match`/`special`/`comment` values Numista
actually returned for each issue, and the rejection log will name the
precise reason - enough to pinpoint hypothesis (b) (or something else
entirely) conclusively, without further guessing.

---

## 25. Follow-up fix: Sheldon-scale grade normalization for Numista pricing

**Trigger**: the type/issue matching pipeline finally worked end-to-end
for real on a live UK 2012 20p scan (type 5628 -> issue 144284, per §24) -
and that same successful scan surfaced the next bug, in pricing. The AI's
`estimated_grade` was `"F-12 (visual estimate)"`; Numista's real price
list for that issue was `g/vg=0.266846, f/vf=0.280911, xf=0.359662,
au=0.406070, unc=1.160200`. The log showed `"no exact grade match, using
nearest available: requested_grade='F-12 (visual estimate)'
used_grade='vf'"` - wrong (should be `f`), silently masked because `f`
and `vf` happened to be priced identically on this particular coin.

**Root cause**: `fetch_numista_price`'s exact-grade-match loop compared
the AI's raw grade string against Numista's short grade codes
(`g`/`vg`/`f`/`vf`/`xf`/`au`/`unc`) via plain lowercase/strip equality -
no normalization existed at all, so `"f-12 (visual estimate)"` could
never equal `"f"`, and every real scan fell through to the crude
"nearest available" fallback (literally `priced[len(priced)//2]`, the
middle-indexed priced entry - not even a real nearest-by-grade-order
heuristic).

**Fix** (`server/app.py`, commit `3378126`): `normalize_numista_grade(grade)`
strips explanatory parenthetical suffixes (`"(visual estimate)"`,
`"(visual estimate; not professionally certified)"`), then maps to
Numista's short code primarily via the **Sheldon-scale number** when
present - numeric bands `1-3 ag, 4-7 g, 8-11 vg, 12-19 f, 20-39 vf,
40-49 xf, 50-59 au, 60-70 unc` - since the number is the authoritative
signal (this is *why* `XF-40` and `EF-40`, different letter prefixes for
the same band, both correctly resolve to `xf` without hardcoding every
combination). Falls back to a small letter-only alias map
(`{"ag","g","vg","f","vf","xf","ef":"xf","au","unc","ms":"unc","bu":"unc"}`)
for numberless grades like bare `"UNC"`. Applying it to an
already-short code (e.g. `"vf"`) is a safe no-op, so `fetch_numista_price`
now normalizes **both** the requested grade and each price entry's own
grade before comparing - guaranteeing the exact-match branch is tried,
and wins when present, before ever falling back to the nearest-available
heuristic.

**Normalization mapping** (exactly as specified): `G-4→g, VG-8→vg,
F-12→f, F-15→f, VF-20/25/30/35→vf, XF-40/45→xf, EF-40/45→xf, AU-50/53/
55/58→au, MS-60+→unc, UNC→unc, MS-63→unc`.

**Tests added** (`server/tests/test_numista.py`, 6 new): the full
task-specified grade-form table in one parametrized test; parenthetical-
suffix stripping specifically; already-short codes as a no-op; blank/`None`
handling; and - using the real live UK 20p price list verbatim - the
exact F-12 regression (now correctly selects `"f"` at `0.280911`, not the
`"vf"` fallback) plus a second grade (`AU-55`) confirming exact-match
wins generally, not just for this one coin's coincidental price tie.

**Tests**: 108/108 Python passing (102 → 108), 31/31 JS passing
(unaffected - no JS touched).

**Not changed** (confirmed): Numista search, issuer resolution,
type/issue matching (§17/§24), variant disambiguation (§22/§23), the
price endpoint URL itself, OpenAI prompt, auth, quota/rate-limit,
persistence, frontend.

**Confirms the UK F-12 case now selects Numista `f`**: yes, directly
verified both via a standalone normalization check across all 19
task-specified grade forms and via `fetch_numista_price` against the
real live UK 20p price list, returning `{"grade": "f", "value":
0.280911, "exact_grade_match": True}` for `"F-12 (visual estimate)"`.

**What this means for the pipeline overall**: with §24's type/issue
matching confirmed working live, and this grade-normalization fix now
in place, the full pipeline (search → score → issue match → variant
disambiguation → **correct grade-matched price**) should be complete for
a coin like this. The next live UK 20p scan (or similar) should be the
first to show a real `estimated_value` in the app, not "unavailable."

---

## 26. Follow-up fix: explicit low reasoning effort + a distinct ai_incomplete error

**Trigger**: an intermittent real-scan failure, independent of §25's price
fix. `input_tokens=4584, output_tokens=2000, reasoning_tokens=2000,
total_tokens=6584, response_status=incomplete, http_status=200,
incomplete_details={"reason":"max_output_tokens"}` - the model's default
reasoning effort consumed the *entire* `max_output_tokens` budget with
nothing left for visible JSON. The image was clear; this was never a
"can't recognize this coin" situation, but the server reported it
identically to one (`identification_failure` -> "Coin Not Recognized, try
better lighting"), actively misleading the user about what went wrong.

**Previous reasoning configuration**: absent entirely - the Responses API
payload in `identify_coin_with_ai` had no `"reasoning"` key at all, so the
model's default effort applied, whatever that happened to be.

**Exact new OpenAI request field** (`server/app.py`, commit `88bd7b0`):
```json
"reasoning": {"effort": "low"}
```
added alongside the existing `"max_output_tokens": 2000` (left unchanged,
deliberately - low reasoning effort is being tested in isolation first,
before considering raising the cap further).

**Backend error contract for incomplete/max_output_tokens**: a response
with `status == "incomplete"` and `incomplete_details.reason ==
"max_output_tokens"` is now detected **before** the generic
empty-output-text fallback and raises a new, distinct
`CoinLensError("ai_incomplete", "The AI service couldn't finish
processing this scan.", 503)` - retryable, never
`identification_failure`/`unidentifiable`. Any *other* incomplete reason
(e.g. a hypothetical `content_filter`) still falls through to the
existing generic handling unchanged - the new branch is scoped
specifically to the `max_output_tokens` reason this real failure showed,
not incomplete responses in general. The existing usage log (input/
output/reasoning tokens, `response_status`, `http_status`,
`incomplete_details`) is completely untouched, so the real numbers for
low-reasoning-effort scans stay visible in Render logs going forward -
this is what will let a future session verify whether low effort actually
reduced real-world `reasoning_tokens` usage.

**Expo UX for `ai_incomplete`** (`scanErrorLogic.js`): title "AI
Processing Interrupted", body "The AI service couldn't finish processing
this scan." (the server's own message, via the existing generic
`body: e.message` path - no special-case override needed), no tip box,
automatically retryable (`isRetryableErrorCode` already treats every code
except `quota_exceeded` as retryable) -> renders "Try Again".
`ScanScreen.js` needed **zero changes**: button rendering was already
generic on the existing `retryable` field, exactly as it was for §19's
`rate_limit` buckets and §11's `quota_exceeded`.

**Genuine unidentifiable behavior preserved**: `normalize_identification`'s
status/confidence logic and the 422/`unidentifiable`
"Coin Not Recognized" flow for a real `completed` response with
`status: "uncertain"` are completely untouched, and now have an explicit
test (`test_identify_coin_genuine_uncertain_identification_unchanged`)
asserting they stay distinct from the new `ai_incomplete` path.

**Tests**: 111/111 Python passing (108 → 111: 1 existing test updated to
assert the corrected `ai_incomplete`/503 behavior instead of the old
`identification_failure`/422 it used to encode - that test's prior
expectation *was* this exact bug - plus 2 more new backend tests). 34/34
JS passing (31 → 34: the AI-processing-interrupted message + retryable,
no lighting/image/recognition language, and distinct from
`identification_failure`).

**Confirmed untouched** (re-ran full suites unmodified): model, image
resolution/preprocessing, structured output schema, identification prompt
semantics, confidence threshold, Numista (§17/§20/§22-24), grade
normalization (§25), persistence, quota accounting, auth.

**Not yet done**: not verified against a real OpenAI call in this session
(no live key here) - the next real scan's Render logs should show whether
`reasoning_tokens` actually drops with explicit low effort, and, if the
exhaustion still happens occasionally, the app should now correctly show
"AI Processing Interrupted" + Try Again instead of the misleading "Coin
Not Recognized" message.

---

## 27. Follow-up fix: issue-classifier keyword gap ("uncirculated" missing)

**Trigger**: §26's low-reasoning-effort fix worked live -
`reasoning_tokens=135/241`, `response_status=completed` on two real scans
(a 2016 Canada 5 cents and, per the earlier §26 confirmation report, a
successful UK 20p scan) - OpenAI is healthy, not touched here. But the
2016 Canada 5-cent scan then hit the *exact same failure shape* as the
UK 20p bug (§24/§25): the correct type (395, "5 Cents - Elizabeth II
(4th portrait; magnetic with RCM logo)", `Standard circulation coins`)
was rejected with `"year matched but multiple ordinary issues remain
indistinguishable"`, even though only **one** of its four 2016 issues
(284842, blank comment) was genuinely ordinary - issue 853959 (`comment:
"Uncirculated"`) was incorrectly classified `special=False` and tied
with it.

**Whether the intended fix was missing, undeployed, or logically
broken**: none of the first two - confirmed **logically broken**. Per
explicit instruction, verified deployment state first: `git log`/`git
status` showed local HEAD == `origin/seperate` HEAD (`17bf7de`) with a
clean working tree - nothing uncommitted, nothing undeployed. The Render
log itself was further proof: it showed *every* prior fix firing
correctly in sequence (`issuer resolution`, `structured search response`,
`denomination disambiguation`, the `issue evaluation` diagnostic lines
from §24) - this was live, current code running exactly as committed.
The bug was a straightforward gap in the §23 issue-level keyword set
itself.

**Exact predicate causing `"uncirculated" -> special=False`**:
`ISSUE_SPECIAL_KEYWORDS` (added in §23) was
`{"proof", "bu", "specimen", "pattern", "prooflike", "matte"}` - it never
included `"uncirculated"` or `"brilliant"` at all. `_looks_special_issue`
tokenizes an issue's comment into whole words and checks set
intersection; `"uncirculated"` tokenized to `{"uncirculated"}` has no
overlap with that set, so it fell through to `special=False` every time,
regardless of casing.

**Exact fix** (`server/app.py`, commit `a36d38a`): added `"uncirculated"`,
`"brilliant"`, and a literal `"prooflike"` (previously only reachable
incidentally via the "proof" token inside "proof-like") to
`ISSUE_SPECIAL_KEYWORDS`; added a new `ISSUE_SPECIAL_PHRASES =
("special edition", "mint set", "proof set")` checked as whole-string
substrings (not individual tokens, since "edition"/"set" alone are too
generic to trust as single-word signals) for the two-word markers the
task required. Documented explicitly in-code: a Numista issue's own
`"Uncirculated"` **comment** is a distinct mint/collector-product concept
from the AI's own `"AU"` (About Uncirculated) **condition grade** -
`ai_indicates_special_variant` (type-level, §22) only ever reads the AI's
identification text and was never at risk of conflating the two; this was
purely a keyword-coverage gap in the issue-level classifier, not a
design/architecture problem.

**One outdated test fixed in the process**:
`test_looks_special_issue_matches_whole_words_only` asserted
`{"comment": "About uncirculated"}` -> `special=False` - that assertion
was itself encoding the same misunderstanding this bug came from (treating
an issue-level "Uncirculated" comment as if it were an AU-grade phrase);
updated to expect `special=True`, since a Numista issue comment saying
"Uncirculated" is always the special-product marker, "About" or not.

**Deployed/current commit**: `a36d38a` (pushed to `origin/seperate`,
confirmed via `git log`/`git status` before making any change, per the
task's explicit "verify first" instruction).

**Tests**: 113/113 Python passing (111 → 113: the exact live 2016 Canada
5-cent issue set with an AU-55/"standard circulation design" AI result
now selects issue 284842 via `_select_issue_for_year`; the full required
keyword table - Proof, Prooflike, Proof-like, Specimen, Uncirculated,
Brilliant Uncirculated, BU, Special Edition, Mint Set, Proof Set, blank ->
ordinary - directly unit-tested). 34/34 JS passing (unaffected, no JS
touched).

**Confirmed untouched** (re-ran both full suites unmodified): structured
Numista search, issuer resolution, denomination normalization, type
scoring, type-level variant filtering (§22), grade normalization (§25),
price endpoint/parsing, OpenAI reasoning settings (§26), auth,
quota/rate-limit, persistence, frontend.

**Confirmed expected live path**: type 395 -> issue 284842 -> Numista
prices - the same 2016 Canada 5-cent coin (or any similar coin whose
correct issue has a blank comment while a same-year sibling issue is
marked "Uncirculated"/"BU"/"Proof"/etc.) should now resolve to the
ordinary issue and reach a real price lookup instead of "unavailable."

---

## 28. Follow-up fix: trailing-parenthetical denomination titles (Hong Kong $2)

**Trigger**: a live Hong Kong $2 scan (`country=Hong Kong,
denomination="2 dollars", year=1997`) - the *first* real scan this
session to actually reach a confident selection - exposed one more small
denomination-matching gap. Structured search correctly returned three
candidates (5276 "20 Cents (Special Administration Region)", 1582 "2
Dollars", 5280 "2 Dollars (Special Administration Region)"); denomination
disambiguation correctly kept 1582 but **also incorrectly dropped 5280**,
even though 5280 is genuinely a "2 dollars" coin (a circulating
commemorative variant of the same denomination).

**Exact reason the parenthetical title previously failed**:
`_numista_title_denomination` only ever stripped text after a `" - "`
series separator. Candidate 5280's title has **no dash at all** - just a
denomination followed directly by a parenthetical qualifier. With
nothing to strip, the *whole* title (including the qualifier's own words
"special"/"administration"/"region") was fed into
`normalize_numista_denomination`, whose tokenizer folded all of those
words into the "unit" portion of the canonical string - producing `"2
dollar special administration region"` instead of `"2 dollar"`, which
then never equaled the AI's plain `"2 dollar"`.

**Exact normalization/parsing change** (`server/app.py`,
`_numista_title_denomination`, commit `e8feda0`): after the existing `"
- "` split, added one line stripping a **trailing** parenthetical (only
when it ends the string) via `re.sub(r"\s*\([^()]*\)\s*$", "", prefix)`,
before handing the result to the unchanged `normalize_numista_denomination`.
Nothing about denomination *equality* itself (the number+unit comparison
logic) was touched - only what text reaches it.

**Result for `"2 Dollars (Special Administration Region)"`**: now
normalizes to `"2 dollar"`, matching the AI's `"2 dollars"` -> `"2
dollar"`. **Confirmed**: `"20 Cents (Special Administration Region)"`
still normalizes to `"20 cent"` and does **not** match `"2 dollar"` -
verified directly, plus `"20 Dollars"` still correctly does not match `"2
dollar"` (a wrong digit is never normalized away, exactly as before).

**Confirmed the existing Hong Kong $2 regression still selects the
correct standard-circulation type**: a new end-to-end test feeds the
exact three real candidates into `resolve_numista_type_and_issue` - both
1582 ("Standard circulation coins") and 5280 ("Circulating commemorative
coins") now correctly survive the denomination check together (as
required - denomination matching must not itself judge
circulation-vs-commemorative), and the **already-existing, untouched**
type-level variant step then correctly prefers 1582 over the
commemorative 5280 for an ordinary AI description, landing on type_id
1582 exactly as it should.

**Tests**: 119/119 Python passing (113 → 119: the exact task-specified
match/no-match table, plus the full three-candidate end-to-end regression
using the real Hong Kong candidates). 34/34 JS passing (unaffected - no
JS touched).

**Not changed** (confirmed by re-running both full suites unmodified):
OpenAI, issuer resolution, structured Numista search, issue/year
validation, type-level variant classification (§22), issue-level variant
classification (§27), grade normalization (§25), price lookup, auth,
quota/rate-limit handling, persistence, frontend, database schema.

**Significance**: per the user's own framing, this Hong Kong $2 scan was
already a *successful* live scan end to end - the core matching pipeline
(search -> scoring -> denomination -> issue/year -> variant
disambiguation -> price) is validated. This bug happened not to change
the final outcome for this particular scan (1582 was correctly selected
either way, since narrowing to "1 candidate" trivially wins regardless of
whether 5280 was wrongly dropped along the way) - it's exactly the kind
of latent correctness bug that could silently misfire on a *future* scan
where the wrongly-dropped candidate would have mattered (e.g., a
different coin where the commemorative variant, not the standard one,
was actually the correct answer). Fixed as pure cleanup, not a pipeline
redesign, per explicit instruction.

---

## 29. Investigation: leaderboard badge mismatch + fix: `canonicalize_denomination` "penny" bug

### 29a. Investigation (no code changed for this part): why lizard shows 5 badges as herself but 2 as viewed by bro

**Exact cause** - `src/screens/leaderboard/LeaderboardScreen.js:94,99`:
```js
const myBadgeCount = BADGES.filter(b => b.check(userScans || [], user)).length;
...
badges: row.isMe ? myBadgeCount : tierBadgeCount(row),
```
The **viewer's own row** runs the real `BADGES[].check()` predicates (`src/badges/badges.js`) against their real scans (`fetchMyScans()`, RLS-safe) -> exact. **Every other row** uses `tierBadgeCount(row)` (`src/badges/badges.js`), a deliberate approximation from only `scan_count`/`total_value`/`member_since` (the only fields the `leaderboard()` RPC returns per `supabase/migrations/0001_...sql`) - the same fields used regardless of who's asking. So lizard-viewed-by-bro and lizard-viewed-by-herself differ *only* in which code path runs, not in any data corruption.

**Why the approximation lands on 2, not 5**: `tierBadgeCount` only sums Scanning/Net Worth/Member tier thresholds - it is structurally blind to the Seasonal, Variety, and Coin Types categories entirely (no aggregate field exists to reconstruct them). Lizard's real 5 almost certainly includes real Coin Types badges (`type_foreign`, `type_dollar` from the HK $2, possibly `type_penny` from the Canada 5c - see 29b) that no aggregate-only formula can ever see.

**Is the leaderboard badge count approximate today?** Yes, for every user except the viewer, by design (the function's own comment says so) - not a data bug.

**Recommended V1 architecture**: **Option B** - persist an authoritative `badge_count` (or unlocked-badges record) computed server-side (a Python port of `badges.js`, reusing the same ~57 rules unchanged) whenever a scan is persisted, using `supabase_admin`'s already-trusted server-to-server access (RLS never touched, no client-supplied count ever trusted) - then have `leaderboard()` expose only the count. Option A (reimplement all rules in SQL) was rejected as excessive/fragile for streak and seasonal-date logic; Option C (more aggregates) was rejected as structurally incapable of exactness for Coin Types/Variety/Seasonal badges. Requires one small DB migration (a `badge_count` column or small table) and updating `leaderboard()` to expose it; badge *definitions* themselves stay unchanged. **Not implemented yet** - reported per explicit "before changing anything" instruction; a separate task should build this.

### 29b. Fixed: `canonicalize_denomination` "penny" bug (commit `f03a54d`, pushed)

**Root cause**: `"cent" in text` is a substring check - `"cent"` is literally contained in `"cents"` - so *any* "N cents" denomination (Canada/Australia 5c/10c/25c, etc.) matched this check and returned `"penny"` before the more specific `nickel`/`dime`/`quarter` checks below it ever ran. A real "Canada 5 cents" scan persisted `denom_canonical="penny"`, which could falsely award `type_penny`/`var_penny_streak`.

**Fix**: the penny branch now only matches the literal word `"penny"`, or an explicit numeric value of 1 (`\b(?:1|one)\s+cents?\b` - "1 cent"/"one cent", the actual US penny). Bare "N cents" (N != 1) with no explicit `"nickel"`/`"dime"`/`"quarter"` (or the pre-existing, untouched spelled-out `"five cent"`/`"ten cent"`/`"twenty-five cent"` signals) now falls through to the generic slug fallback - matching the architecture's own documented intent (§1a: a foreign denomination that doesn't explicitly match a US coin term should slug-fallback, not get force-mapped). Deliberately did **not** add bare "5 cents" to the nickel branch - the existing taxonomy only ever recognized nickel via the literal word or the spelled-out number, and the task explicitly said not to introduce a new global mapping unless that was already the documented intent (it isn't). `"2 dollars"` -> `"dollar"` (Hong Kong) is the untouched `dollar` branch and remains correct/expected, confirmed unchanged.

**Tests**: 8 new (`server/tests/test_app.py`, `CanonicalizeDenominationTests` - no direct tests existed for this function before). 127/127 Python passing (119 -> 127), 34/34 JS passing (unaffected, no JS touched).

**Not changed** (confirmed): Numista denomination matching, OpenAI identification, valuation, auth, scan persistence structure, leaderboard, badge definitions themselves.

**Existing bad data - not touched, per explicit instruction**. Recommended (not executed):

Identify affected rows (safe, read-only):
```sql
select id, user_id, country, denomination, coin_name, denom_canonical, scanned_at
from public.scans
where denom_canonical = 'penny'
  and lower(coalesce(denomination, '') || ' ' || coalesce(coin_name, '')) not like '%penny%'
  and lower(coalesce(denomination, '') || ' ' || coalesce(coin_name, ''))
      !~ '\y(1|one)\s+cents?\y'
order by scanned_at desc;
```
(Any row `denom_canonical='penny'` this query still returns has neither the literal word "penny" nor an explicit "1 cent"/"one cent" in its source text - i.e. it can only be a bug victim, since those were the only two ways to land in "penny" pre-fix.)

Recommended backfill (review the SELECT above first; take a snapshot; run inside a transaction and inspect before committing - do **not** run unreviewed):
```sql
begin;
with affected as (
  select id, lower(coalesce(denomination, '') || ' ' || coalesce(coin_name, '')) as text
  from public.scans
  where denom_canonical = 'penny'
    and lower(coalesce(denomination, '') || ' ' || coalesce(coin_name, '')) not like '%penny%'
    and lower(coalesce(denomination, '') || ' ' || coalesce(coin_name, ''))
        !~ '\y(1|one)\s+cents?\y'
)
update public.scans s
set denom_canonical = case
  when a.text like '%nickel%' or a.text like '%five cent%' then 'nickel'
  when a.text like '%dime%' or a.text like '%ten cent%' then 'dime'
  when a.text like '%quarter%' or a.text like '%twenty-five cent%' or a.text like '%twenty five cent%' then 'quarter'
  when a.text like '%half dollar%' or a.text like '%half-dollar%' then 'half-dollar'
  when a.text like '%dollar%' then 'dollar'
  else nullif(regexp_replace(lower(s.denomination), '[^a-z0-9]+', '-', 'g'), '')
end
from affected a
where s.id = a.id;
-- review before committing:
-- select s.id, s.denomination, s.coin_name, s.denom_canonical from public.scans s join affected a on a.id = s.id;
commit; -- or rollback;
```
Caveat: this `CASE` is a second, hand-written mirror of the Python branches and could drift from it over time. The more drift-proof alternative is a one-off script that imports the real `canonicalize_denomination()` and recomputes each affected row's value in Python before issuing per-row updates via `supabase_admin` - worth considering instead of/alongside the SQL above, especially if this needs to be re-run after any future change to the function.

---

## 30. Follow-up fix: digit-vs-word denomination consistency (found before backfill/authoritative badges, as intended)

**Trigger**: found during the pre-backfill/pre-authoritative-badges review
§29b itself called for. §29b's fix left one remaining inconsistency: `"5
cents"` fell through to the generic slug fallback, but spelled-out `"five
cents"` still matched a *parallel* word-based check in the nickel branch
(`"five cent" in text`) and became `"nickel"`. The same foreign coin could
land in a different, US-specific badge category purely depending on
whether OpenAI phrased the face value as a digit or a word - unsafe to
backfill or build authoritative badges on top of.

**Exact prior inconsistency**: the nickel/dime/quarter checks matched
spelled-out face value (`"five cent"`, `"ten cent"`, `"twenty-five
cent"`) as if it were an explicit coin-type signal, while the digit form
had no equivalent check and fell through to the slug fallback - two
parallel, inconsistent code paths carrying the same information.

**Fix** (`server/app.py`, commit `895ee7b`):
1. `_normalize_denomination_numbers()` converts spelled-out face-value
   numbers to digits (longest phrases first, so `"twenty-five"`/`"twenty
   five"` convert before the `"five"` inside them would) **before any
   check runs** - `"five cents"` and `"5 cents"` become the identical
   string, so every later check (including the slug fallback) treats them
   identically.
2. `nickel`/`dime`/`quarter` are now recognized **only** by their
   explicit coin-name word - never by face value, digit or spelled-out,
   at all. `"1 cent"`/`"one cent"` remains the one explicit numeric
   exception (unchanged in effect) since that value has no separate US
   coin name of its own - "penny" is both its name and its value.

**Did country/context have to be added to the function?** No. Removing
face-value-based inference entirely made the result already
country-agnostic - a foreign and a US coin at the same face value now
canonicalize identically unless a coin name is actually given. A genuine
US nickel/dime is still correctly recognized because real identifications
name the coin explicitly (`"Jefferson Nickel"`, `"Roosevelt Dime"`),
confirmed with a direct test. No signature or call-site change was
needed.

**Canonical results** (digit and word forms, confirmed identical):
`1 cent`/`one cent` → `penny` (unchanged); `5 cents`/`five cents` →
`"5-cents"` (both - previously inconsistent); `10 cents`/`ten cents` →
`"10-cents"`; `25 cents`/`twenty-five cents`/`twenty five cents` →
`"25-cents"`; explicit `nickel`/`dime`/`quarter`/`penny` → themselves,
unchanged; `2 dollars` → `dollar`, unchanged.

**Tests**: 131/131 Python passing (127 → 131: one now-outdated test from
§29b that itself asserted the exact inconsistency being fixed here was
replaced). 34/34 JS passing (unaffected, no JS touched).

**Not changed** (confirmed): Numista denomination matching, valuation,
OpenAI prompt, leaderboard architecture, badge thresholds/rules, RLS,
persistence schema.

**Revised safe backfill recommendation - supersedes §29b's SQL-only
plan**: with two successive rounds of fixes to this function now in one
session, a third hand-written SQL mirror of its logic would itself be a
real drift risk (exactly the caveat §29b already flagged, now doubly
true). **Recommended approach**: export candidates with a narrow,
safe, read-only query -
```sql
-- Only these four buckets could have been affected by either historical
-- bug; dollar/half-dollar/wheat-penny/slug rows were never wrong.
select id, user_id, denomination, coin_name, denom_canonical, scanned_at
from public.scans
where denom_canonical in ('penny', 'nickel', 'dime', 'quarter')
order by scanned_at desc;
```
then, for each exported row, recompute `canonicalize_denomination(denomination,
coin_name)` using the **current, real Python function** (not a SQL
re-implementation) and compare to the stored `denom_canonical`; only rows
where they differ get updated, via a small script issuing per-row (or
batched, values-list-driven) `UPDATE`s built entirely from the script's
computed results - never a hand-written SQL `CASE`. This is the more
drift-proof option §29b already flagged as an alternative; it's now the
primary recommendation rather than a caveat, given the fix has changed
twice.

---

## 31. Follow-up implementation: exact leaderboard badge counts via a trusted backend evaluator (commit `f7ff5dd`)

**Trigger**: direct follow-up to §29a's audit/recommendation. Before this, badges
were derived-current-state, every category monotonic, no scan delete/edit
capability existed anywhere, and the recommended architecture was "Option 3"
(compute exact badge_count live on leaderboard read, via a trusted backend,
with no persistence) - this section implements exactly that, superseding
§29a's "Option B" (persisted `badge_count` column) recommendation, which
would have needed a migration this approach avoids entirely.

**Authoritative badge evaluator - `server/badges.py` (new file)**: a 1:1 port
of all ~57 rules from `src/badges/badges.js` (same ids, thresholds,
categories - scan-count, net-worth, membership-age, denomination/type,
streak, seasonal/date, time-of-day, rapid-scan). `evaluate_badges(scans,
member_created_at)` returns `(badge_count, earned_badge_ids)`. Confirmed by
script: badge ids and their order are identical between `badges.py` and
`badges.js` (57/57, zero diff either direction). The one porting subtlety:
JS `Date.getDay()` (Sun=0…Sat=6) vs Python `date.weekday()` (Mon=0…Sun=6) -
handled correctly (`weekday()==4` for Friday the 13th, `weekday()==3` for
Thanksgiving Thursday), verified against real calendar dates
(`2024-09-13` = a real Friday the 13th, `2026-11-26` = the actual 4th
Thursday of November 2026).

**New endpoints (`server/app.py`), both behind `@require_auth` (JWT-only
identity, `g.user_id`; a client can never supply or spoof another user's
id)**:
- `GET /api/badges/me` - fetches the caller's own scans
  (`fetch_scans_for_user`) and real profile `created_at`
  (`fetch_profile_created_at`) via the service-role client, runs
  `evaluate_badges`, returns `{"badge_count": N, "earned_badge_ids": [...]}`.
  A `?user_id=` query param, if present, is silently ignored - identity comes
  only from the token.
- `GET /api/leaderboard` - calls the existing `leaderboard()` RPC
  (unchanged) via `fetch_leaderboard_rows`, collects every row's `user_id`,
  fetches all of their scans in **one batched query**
  (`fetch_scans_for_users`, `user_id=in.(...)`) rather than one query per
  user, groups by `user_id`, and runs `evaluate_badges` per user using that
  row's own `member_since` as the trusted membership date. Returns the
  existing fields (`user_id`, `display_name`, `scan_count`, `total_value`,
  `avg_value`, `member_since`) plus a new `badge_count` - never the raw scan
  rows themselves. New `supabase_admin.py` helper functions
  (`fetch_scans_for_user`, `fetch_scans_for_users`,
  `fetch_profile_created_at`, `fetch_leaderboard_rows`) all reuse the
  existing `_request_with_gateway_retry`/`SupabaseAdminError` patterns; both
  routes return 503 `*_fetch_failed` on any Supabase error rather than a raw
  500.

**Retained-profile / zero-scans-after-reset scenario handled correctly**:
`evaluate_badges([], member_created_at)` still awards membership badges from
the real, unchanged `profiles.created_at` even with an empty scan list -
covered directly by
`test_zero_scans_can_still_have_membership_badges` (`server/tests/test_badges.py`).
This is exactly the behavior the task warned an account with zero scans is
*not* guaranteed to have zero badges after the planned `scans`/`api_usage`
reset.

**Frontend**:
- `src/api/scans.js`'s `fetchLeaderboard()` now calls `apiFetch("/api/leaderboard")`
  instead of `supabase.rpc("leaderboard")` directly.
- `src/api/client.js` gained `fetchMyBadges()`, calling `GET /api/badges/me`.
- `src/screens/leaderboard/LeaderboardScreen.js`: removed the `BADGES`/
  `tierBadgeCount` import and the `row.isMe ? myBadgeCount : tierBadgeCount(row)`
  branch entirely (this was the exact root cause §29a diagnosed for the
  lizard-sees-5/bro-sees-2 mismatch) - every row, viewer's own included, now
  just reads `row.badge_count` straight from the endpoint.
- `src/badges/BadgesScreen.js`: now fetches `earned_badge_ids`/`badge_count`
  from `fetchMyBadges()` on mount instead of running
  `BADGES.filter(b => b.check(userScans, user))` locally.
- `src/badges/badges.js`: stripped down to **display metadata only**
  (`id`/`icon`/`name`/`desc`/`category` per badge, plus `BADGE_CATEGORIES`) -
  all `check()` predicates and `tierBadgeCount` were deleted. This was a
  deliberate choice per the task's own guidance ("JS may retain display
  metadata but should avoid maintaining independent eligibility logic
  long-term"): keeping a second, unused copy of ~57 predicates around would
  have been exactly the kind of latent drift risk this session has hit
  repeatedly elsewhere (denomination canonicalization, issue-keyword
  matching). `server/badges.py` is now the only place eligibility is
  decided, in either direction.

**Security properties verified by test** (`server/tests/test_app.py`):
`/api/badges/me` derives identity only from the JWT (`test_badges_me_requires_auth`,
`test_badges_me_ignores_a_client_supplied_user_id`); `/api/leaderboard`
requires auth and never returns raw scan fields
(`test_leaderboard_never_returns_raw_scan_fields` asserts the response text
contains none of `denom_canonical`/`estimated_value`/`is_foreign`/
`local_hour`/`local_date`); the batched (not per-user) scan fetch is
asserted via a mock call-count check
(`test_leaderboard_preserves_existing_fields_and_adds_badge_count`); and the
core regression requirement - **badge_count for a given user is identical
regardless of which authenticated user is viewing the leaderboard** - is
directly tested by `test_leaderboard_badge_count_is_independent_of_the_viewer`
(calls `/api/leaderboard` as two different authenticated users, asserts an
identical JSON response). Scan RLS is untouched; service-role credentials
remain backend-only (`supabase_admin.py`, unchanged pattern); no DB
migration of any kind was needed or made.

**Tests**: 177 Python passing (131 → 177: 37 new direct
`server/tests/test_badges.py` unit tests across every badge category, 9 new
`server/tests/test_app.py` endpoint tests). 28 JS passing (`__tests__/badges.test.js`
rewritten from predicate-behavior tests to metadata-shape tests, since the
predicates it tested no longer exist client-side).

**Not changed** (confirmed): the `leaderboard()` SQL RPC itself, scan RLS
policies, `canonicalize_denomination`/Numista/OpenAI pipeline, badge
id/threshold/category definitions (byte-for-byte preserved, just relocated),
`require_auth`/`require_user`, service-role credential handling.

**Note - test data reset**: the user plans to delete all rows from
`public.scans` and `public.api_usage` (keeping `auth.users`/`public.profiles`)
to validate this end-to-end against fresh data. No code or migration in this
section depends on or requires that reset; it's a manual validation step,
not implemented here.

---

## 32. Pending external actions

1. ~~Run this in the Supabase SQL editor~~ — **now believed applied**: the
   real scan in §14 ran with `MOCK_MODE` off and reached
   `check_and_reserve_quota`/`insert_api_usage` without a
   `quota_check_failed` error, which only succeeds if the `service_role`
   grant on `public.api_usage` is in place. Still worth a positive
   confirmation (e.g. re-check via the Supabase SQL editor) rather than
   relying solely on one successful request, but this is no longer an
   open question mark the way it was:
   ```sql
   grant select, insert, update on public.api_usage to service_role;
   ```
   (Equivalently: `supabase/migrations/0002_grant_api_usage_service_role.sql`.)

2. ~~Numista type-detail/pricing endpoint assumptions~~ — **superseded by
   §17**: the `/types/{id}/prices` assumption was wrong (confirmed via a
   third-party SDK to actually be `/types/{id}/issues/{issue_id}/prices`)
   and is now fixed, but still **unconfirmed against a live response** -
   see §17's "exact next real coin test to perform" for what to check.

2b. See §17 for the full matching-algorithm investigation and fix
   (search-vs-scoring-vs-type/issue root cause, before/after algorithm,
   and the specific next real-scan test to run).

3. Also check whether the illegible-year case (§8) now comes back with a
   confidence that actually reads as low/uncertain rather than a high
   number next to "uncertain" - the prompt fix is unverified against a
   live model. (The §14 scan was a fully-legible coin, confidence 96, so
   it didn't exercise this case either.)

4. ~~Test the §13 camera focus change on a real device~~ — **confirmed**:
   the user reported "the zoom change worked" before reporting the §14
   scan-save bug, so `zoom={0.3}` fixed the blur. `BOX_SIZE` 260→230 wasn't
   separately called out, so treat it as fine unless the user says
   otherwise.

5. Watch Render logs for the next `scan_insert_failed` (or a
   `WARNING:supabase_admin:supabase request got a transient ..., retrying`
   line that *doesn't* end in success) to confirm the §14 retry actually
   resolves real-world Supabase gateway blips rather than just passing its
   unit tests.

6. ~~Watch Render logs for the next `[identify] OpenAI usage: ...` line~~ —
   **partially confirmed**: the very next real scan showed
   `input_tokens=4584` (down from ~17.4K) and no `Rate Limit Hit` - §15's
   fix worked for the rate-limit problem specifically. That same scan then
   hit a *different* bug (§16: truncated/empty response from
   `max_output_tokens` being too low), now also fixed but unverified.

7. ~~Watch Render logs for the next `[identify] OpenAI usage: ...` line
   (§16) for a `reasoning=` value~~ — **confirmed fixed**: the very next
   real scan (2012 UK 20 pence) completed successfully:
   `output_tokens=947 (reasoning=720) total_tokens=5531
   response_status=completed`. This is a direct confirmation of the §16
   theory - reasoning spent 720 of the 947 output tokens, leaving 227 for
   the actual JSON answer, comfortably inside the new 2000 cap (vs. the
   old 1000 cap, which the reasoning tokens alone would have blown through
   on their own). Identification, Numista lookup (no confident match, so
   correctly "unavailable"), and scan persistence all completed normally
   end-to-end with no errors.

8. See §17 for the Numista type-vs-issue matching + pricing investigation
   and fix (the "estimated value not available" question) and its "exact
   next real coin test to perform" section.

9. Watch Render logs for the next real OpenAI 429 for the new
   `[identify] OpenAI error response: ...` line (§18) - confirms the
   header/body diagnostics actually surface the account's real rate-limit
   window state (remaining requests/tokens, reset timers) rather than just
   passing its unit tests.

10. See §19 for the `retry_after_seconds`/rate_limit-UI change - watch
    Render logs and the app for the next real OpenAI 429 to confirm the
    bucketed wait text and Try Again/Back to Home split actually appear
    correctly on device.

11. See §20 for the Numista issuer-code/structured-search fix - run the
    "exact next real scan to run" there (a UK coin) to confirm structured
    search actually surfaces the real match instead of Isle of Man
    candidates, and to get the first real confirmation of the issue-price
    endpoint's response shape.

12. See §21 for the doubled-disclaimer and redundant-log-scan fixes - next
    real scan's summary text should show the grade disclaimer once, and
    Render logs should no longer show a `POST /api/log-scan` call
    immediately after a successful `/api/identify-coin`. Separately, if
    `AdminScreen.js` ever needs attention, it should be pointed at Supabase
    like the rest of the app instead of SheetDB/AsyncStorage.

13. See §22 for the variant-disambiguation fix - run the "exact next live
    scan to perform" there (the same UK 2012 20p) to confirm it now
    resolves to type 5628 and to get the first real confirmation of the
    issue-price endpoint's response shape.

14. See §23 for the denomination-normalization + issue-level variant fix -
    run its "exact next live scan expected path" (the same UK 20p) to
    finally confirm an end-to-end confident valuation, including the
    still-unverified issue-price endpoint response shape.

15. See §24 - a live scan reported type 5628 being incorrectly rejected
    despite three real 2012 issues; could not be reproduced with the
    exact data given (may be a deployment-timing artifact from §23
    landing the same session). Watch the next live scan's new
    `[numista] issue evaluation: ...` log lines and the rejection
    reason string either way - if it still fails, those lines will show
    the actual predicate values Numista returned, likely pointing at a
    negation in the AI's description tripping `ai_indicates_special_variant`
    (a shared, currently off-limits function - would need a follow-up
    task scoped to include it).

16. See §25 - grade normalization is now fixed and unit-verified against
    the real live UK 20p price list, but not yet confirmed by an actual
    live scan showing a real `estimated_value` in the app (every real
    scan so far this session has stopped at "unavailable" for one reason
    or another - this may be the one that finally gets all the way
    through).

17. See §26 - watch the next real scan's `[identify] OpenAI usage: ...`
    log line for whether `reasoning=` actually drops with explicit low
    effort, and whether the intermittent `max_output_tokens` exhaustion
    stops recurring. If it still happens occasionally, confirm the app
    now shows "AI Processing Interrupted" + Try Again, not "Coin Not
    Recognized".

Everything through §26 (code, tests, all commits through `88bd7b0`) is
18. See §27 - watch the next live scan (2016 Canada 5 cents, or the UK
    20p from §24/§25) for type 395 -> issue 284842 -> an actual Numista
    price, which would be the *first* real scan this entire session to
    show a confident `estimated_value` end-to-end rather than
    "unavailable" for one reason or another.

19. See §28 - a real Hong Kong $2 scan already succeeded end-to-end
    (per the user's own report) despite this latent bug, since the final
    winning type happened to be unaffected. Nothing further to verify
    live for this specific fix; watch future scans of coins with a
    circulating-commemorative sibling for any similar title-parsing edge
    case.

20. ~~See §29a - leaderboard badge counts for other users are an
    intentional-but-approximate placeholder~~ - **implemented, see §31**:
    `server/badges.py` now computes an exact `badge_count` for every
    leaderboard row live on read, with no persistence and no migration
    (Option 3, not §29a's originally-recommended Option B). Still to
    validate: the user's planned `scans`/`api_usage` reset, then confirm a
    real multi-user leaderboard shows identical `badge_count` for the same
    user regardless of viewer (the unit tests already prove this in
    isolation; a live confirmation is the next real check).

21. See §30 (supersedes §29b's plan) - `canonicalize_denomination` is now
    fixed and self-consistent in code (new scans persist correctly going
    forward), but **existing bad rows in Supabase have not been
    touched**. Run §30's export query first, recompute each row with the
    current real Python function, and only then backfill genuine
    mismatches - do not use §29b's now-superseded SQL `CASE` mirror. The
    user's planned `scans`/`api_usage` table reset (§31) makes this
    backfill moot for any rows that get deleted; only relevant if some
    old rows are kept.

22. See §31 - the exact-badge-count implementation is code-complete,
    tested (177 Python / 28 JS), and committed, but not yet confirmed
    against real post-reset data. Next real check: after the user deletes
    all `scans`/`api_usage` rows, confirm (a) a brand-new scan still
    computes badges correctly from a zero-scan baseline, (b) an account
    with retained membership age still shows its membership badges with
    zero scans, and (c) the same user's `badge_count` on `/api/leaderboard`
    matches regardless of which signed-in user is viewing it.

Everything through §30 (code, tests, all commits through `895ee7b`) was
previously committed and pushed to `origin/seperate`; §31 (exact
leaderboard badge counts, commit `f7ff5dd`) is implemented, tested, and
committed - see the header for whether it has been pushed yet. §15 (rate
limit) + §16 (truncated response) are confirmed fixed by real, non-mock
scans; §17-§20 (Numista matching/pricing, 429 diagnostics,
retry_after_seconds, issuer resolution), §21 (summary/log-scan fixes), §22
(type-level variant disambiguation), §23 (denomination normalization +
issue-level variant preference), §24 (diagnostic logging + accurate
rejection reasons), §25 (grade normalization), §26 (low reasoning effort +
ai_incomplete), §27 (issue-classifier keyword gap), §28
(trailing-parenthetical denomination titles), §29b
(`canonicalize_denomination` penny-bug fix, superseded by §30's further
correction), §30 (digit/word denomination consistency), and §31 (exact,
live-computed leaderboard badge counts via `server/badges.py`, no
persistence/migration) are all implemented, tested, and committed.
`canonicalize_denomination` is now believed self-consistent enough to
safely proceed with the existing-row backfill (§30) once/if the user
decides not to simply delete those rows in the planned reset. The core
Numista matching pipeline is validated by at least one fully successful
real, live scan (Hong Kong $2) - remaining Numista work is cleanup on edge
cases, not pipeline-blocking bugs. The badge/leaderboard architecture
question raised in §29a is now closed: §31 implements the audit's
recommended "Option 3" (exact, live, unpersisted) end to end; what remains
is real-data validation against the user's planned test reset, not further
design or implementation work.
