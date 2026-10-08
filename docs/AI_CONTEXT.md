# CoinLens AI context

Give this file to an AI coding tool before asking it to change CoinLens. People new to the code should read it too.

It describes branch `main` at commit `9b95f30` (October 6, 2026). It was written from code audits made on September 28 and October 5 and the changes merged on October 6, not from a fresh read of every file. A later commit, `e1b9719`, changed 13 app files, including the scan, badges, leaderboard, home and auth screens, `Root.js`, `src/api/client.js`, `app.json` and a new `src/ErrorBoundary.js`. It is not described here. Server code has not changed since `9b95f30`. **If the code and this file disagree, the code is right.** Fix this file in the same change.

`CONTEXT_EXPORT.md` and `PROTOTYPE_PLAN.md` in the repo are history from September. Parts of them describe designs that were later replaced. Do not treat them as current.

## What the app does

A signed-in user photographs both sides of a coin. The server identifies the coin from the photos, looks it up in the Numista catalog, estimates a value and saves the scan. The app shows history, stats, badges and a leaderboard.

## Architecture

```text
Expo app (React Native)
  -> Supabase Auth: sign up, sign in, session        (publishable key only)
  -> Flask server: POST /api/identify-coin           (Bearer access token + photos)
  -> Supabase database: read own profile and scans   (row level security)
  -> Flask server: GET /api/badges/me, GET /api/leaderboard

Flask server (Render)
  -> verifies the Supabase token, takes the user id from it
  -> reserves one scan from the user's daily limit
  -> OpenAI Responses API: one call, structured output, observations first
  -> evidence gate: deterministic check of what was actually read off the coin
  -> Numista: issuer, type, issue, variant, then price for that issue and grade
  -> optional PCGS price, only if Numista has none
  -> saves the scan with the Supabase service role
```

Stack: Expo SDK 57, React Native 0.86, React 19. Flask 3 with gunicorn. Supabase Auth and Postgres. OpenAI and Numista are called with plain `requests`, not SDKs.

## Rules that must not change

These are the trust boundaries. Do not redesign them as a side effect of another task.

1. **Identity comes only from the verified token.** `server/auth.py` `require_auth` verifies the Supabase JWT and sets `g.user_id` from its `sub`. A `user_id` in a request body or query string is ignored. Tests enforce this.
2. **Secrets stay on the server.** The OpenAI key, Numista key, Supabase service-role key and any mail key exist only as server environment variables. The app gets three public values: `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
3. **Only the server writes scans.** The app has no insert, update or delete path for `scans`, and the database gives it none. The server decides `user_id`, `estimated_value`, `denom_canonical`, `is_foreign`, `local_date` and `local_hour`.
4. **The app reads only its own rows.** `src/api/scans.js` queries `scans` with no `user_id` filter and relies on row level security. Anything that spans users goes through the server.
5. **Other users' raw scans never leave the server.** `/api/leaderboard` returns totals and a badge count per user, nothing else.
6. **Badge rules live in one place:** `server/badges.py`. `src/badges/badges.js` is names, icons and descriptions only. A test checks that it has no eligibility logic.
7. **The evidence gate is final.** If the evidence gate fails, the response is 422, Numista is not called and nothing is saved. A high confidence number never overrides the gate. A catalog match never rescues a failed gate.
8. **Never guess a price.** If the gate passes but Numista has no match, more than one plausible match, a physical contradiction or no price, the identification stands and the scan is saved with `estimated_value = NULL`.
9. **Reserve before spending.** The daily-limit row is written before the OpenAI call, and every attempt counts.
10. **Never log photos.** Logs carry byte counts, image type and a short hash prefix, never base64 or image content.
11. **Authorization never comes from `user_metadata`.** Users can edit their own metadata. See "Admin" below.

## One scan, step by step

`POST /api/identify-coin`, sign-in required. JSON body: `front_image` (base64), `back_image` (base64, optional), `source` (`camera` or `gallery`), `tz_offset_minutes`.

1. Check `source`. Anything else is 400 `invalid_source`.
2. Decode the images. Too large is 413. Only JPEG, PNG, WebP and GIF are accepted, anything else is 415.
3. Log a fingerprint of each image. Log a warning if front and back are the same bytes. This only logs, it does not reject.
4. Count the user's `api_usage` rows since midnight UTC. At or over `DAILY_SCAN_LIMIT` is 429 `quota_exceeded`. Otherwise insert an `attempted` row. If Supabase cannot be reached this fails closed with 503 `quota_check_failed`. Skipped in mock mode.
5. Call OpenAI once. Strict JSON schema, `max_output_tokens` 2000.
6. Normalize the answer and run the evidence gate.
7. Not identifiable: 422 with `identification`, `valuation` (unavailable), `summary` and `remaining_today`. The usage row becomes `uncertain`. Nothing is saved. `identification.rejection` carries the stage (`model_uncertain`, `low_confidence` or `gate`) and the reasons.
8. Identifiable: look up Numista, check physical consistency, price it.
9. Save the scan. 200 with `identification`, `valuation`, `numista`, `pcgs`, `summary`, `scan` and `remaining_today`. If the insert fails, 500 `scan_insert_failed`.

Errors use one shape: `{"error": {"code": "...", "message": "..."}}`. OpenAI problems map to their own codes: `key_invalid`, `quota`, `rate_limit` (with `retry_after_seconds` when OpenAI sends one), `ai_incomplete` (503, the model ran out of output budget) and `malformed_ai_response` (502). The app shows different screens for these (`scanErrorLogic.js`), so keep the codes stable.

Each scan writes one summary log line starting `[identify] outcome=`. Other stages log with the tags `[identify]`, `[numista]`, `[pcgs]` and `[valuation]`.

## The evidence gate

The model must fill in `observations` first: the text it can read on each side, numerals, shape, side count, color, whether the coin is bimetallic, and for each of country, denomination and year a `basis` and the `visible_text` behind it.

`identification_evidence_failures` in `server/app.py` runs when the model says `identified` with confidence 40 or more. It rejects when any of these is true:

- There are no observations.
- Country or denomination is empty or hedged ("unknown", "possibly", "probably", "or", a question mark and similar whole words).
- Year is not exactly four digits between 1000 and next year.
- The basis for country, denomination or year is anything other than `read_on_coin` or `derived_from_visible_markings`, or its `visible_text` is empty or hedged.
- The year is marked `read_on_coin` but does not appear in the transcribed text or numerals.

This exists because the model returned confident, wrong answers on real coins (a UK 50p read as 2011, a Mexican peso as 1910, a UK pound as 2017). Each of those is a regression test.

Do not loosen the gate to make a demo coin pass. A coin whose date and face value are on different sides needs both photos.

## Numista matching and pricing

All of this is conservative on purpose. More than one surviving candidate means "unavailable", never a pick.

1. **Issuer.** The country is resolved to a Numista issuer code from the `/issuers` list (cached in memory for 24 hours). Free-text country search returned other countries' coins first.
2. **Search.** Structured search by denomination, issuer, year and category, 12 results. Falls back to a search without the issuer.
3. **Shortlist.** Candidates are scored (issuer, denomination, year) only to pick the top three worth another request. The score never decides the winner.
4. **Year.** A candidate must have a real issue for the identified year. Prices belong to an issue, not a type.
5. **Denomination.** `normalize_numista_denomination` compares exact "number unit" forms. "Twenty pence" equals "20 Pence" and does not equal "2 Pence" or "50 Pence". "£1 (one pound)" equals "1 Pound". Quoted nicknames are dropped. `$` and `¥` are not mapped to a unit because they are ambiguous.
6. **Variant.** Classes are `ordinary`, `circulating_commemorative`, `proof`, `silver_proof`, `gold_proof`, `platinum_proof`, `specimen`, `bullion`, `piedfort` and `unknown`, with a fixed compatibility table. An ordinary coin never matches a proof or bullion entry. Do not collapse these into one "special" flag.
7. **Issue.** Among issues for that year, the mint mark narrows the choice. For an ordinary coin, issues whose comment says proof, BU, uncirculated, specimen, mint set and similar are skipped.
8. **Physical check.** A definite side count or bimetallic observation that contradicts the catalog entry discards the catalog match only. The scan is still saved, without a value.
9. **Grade.** `normalize_numista_grade` maps the model's grade to Numista's codes by Sheldon number (12 to 19 is `f`, 20 to 39 is `vf`, and so on).
10. **Price.** `GET /types/{id}/issues/{issue_id}/prices` in USD. With no price for the exact grade, the middle priced entry is used and marked as not an exact grade match.

PCGS is only tried when `PCGS_BEARER_TOKEN` is set, the Numista match has a PCGS reference, and Numista gave no price. It was not set up or tested in this project.

Known weak spot: the model sometimes writes a nickname denomination such as "10 cents (one dime)" while Numista's title says "1 Dime". The denominations then do not match and the coin is priced only if year and variant leave a single candidate.

Do not rework the matcher for tidiness. Change it only for a real failing coin, and add that coin as a test.

## Routes

| Route | Sign-in | Notes |
|---|---|---|
| `GET /api/health` | No | Status and non-secret configuration. See `docs/SERVICES.md` |
| `POST /api/identify-coin` | Yes | The scan pipeline above |
| `GET /api/badges/me` | Yes | `{"badge_count": n, "earned_badge_ids": [...]}` for the caller |
| `GET /api/leaderboard` | Yes | Per user: `user_id`, `display_name`, `scan_count`, `total_value`, `avg_value`, `member_since`, `badge_count` |
| `GET /api/me` | Yes | Debug helper, not used by the app |
| `POST /api/generate-ebay-listing` | n/a | Switched off (`ENABLE_EBAY_LISTING=false`) |

Leftovers the app no longer calls, to be removed (HANDOFF task 4): `/api/test-scan`, `/api/numista-specs`, `/api/pcgs-value/<n>`, `/api/log-scan`, `/api/scans`.

Unknown routes return 404 and wrong methods 405 in the standard error shape.

## Data

Three tables in Supabase. Full detail is in `docs/SUPABASE.md`.

| Table | What it holds | Who writes | Who reads |
|---|---|---|---|
| `profiles` | `id`, `display_name`, `role`, `created_at` | A database trigger at sign-up | The user (own row), the server |
| `scans` | One row per saved scan | The server only | The user (own rows), the server |
| `api_usage` | One row per scan attempt, for the daily limit | The server only | The server only |

`scans` columns: `id`, `user_id`, `coin_name`, `country`, `denomination`, `year`, `mint_mark`, `estimated_grade`, `estimated_value`, `source`, `image_path` (unused), `created_at`, `denom_canonical`, `is_foreign`, `local_date`, `local_hour`, `scanned_at`.

`estimated_value` is the value at scan time. It is never recalculated. Photos are not stored anywhere.

## Badges and leaderboard

- 57 badges in six groups: Scanning, Net Worth, Member, Seasonal, Variety, Coin Types.
- `evaluate_badges(scans, member_created_at)` in `server/badges.py` is the only place that decides who has earned what. Badges are worked out on every read and never stored.
- `/api/leaderboard` calls the `leaderboard()` database function with the service role, reads those users' scans in one batched query and counts badges per user. The count for a user is the same no matter who is looking.
- `denom_canonical` feeds the coin-type badges. `canonicalize_denomination` treats a coin as a US nickel, dime or quarter only when the coin's name says so, never from the face value, so foreign 5, 10 and 25 cent coins do not earn US badges. "1 cent" and "penny" both count as penny.
- `local_date` and `local_hour` come from the phone's time zone offset, so the time-of-day and seasonal badges are for fun, not proof.

## Daily limit and mock mode

- The limit is per user per UTC day, stored in `api_usage`, so it survives restarts and multiple workers. Failed and rejected scans count. The code default is 20; set `DAILY_SCAN_LIMIT` on the server.
- The limit check is not atomic. Treat the limit as approximate.
- **Mock mode turns on when `MOCK_MODE` is true or when `OPENAI_API_KEY` is empty.** It skips the limit and saves a canned 1946 wheat cent through the real save path. Always check `mock_mode` in `/api/health` before believing a scan.

## Admin

`profiles.role` is `user` or `admin`. It only decides whether the app shows the Admin screen. `src/api/profile.js` reads the user's own profile row and `Root.js` applies the role. A role is changed by hand in the Supabase SQL editor. The app has no code that writes to `profiles`, and the database must not let it (`supabase/verify.sql` checks this).

The Admin screen itself is a leftover: it reads an old spreadsheet service and device storage, not Supabase.

## App notes

- `App.js` re-exports `src/Root.js`. `Root.js` holds the session and switches screens with a simple state value. There is no navigation library.
- Screens: Auth, Home, Scan, Badges, Leaderboard, Account, Stats, Admin.
- `src/api/supabase.js` creates the Supabase client (session kept in AsyncStorage). `src/api/client.js` calls the server and attaches the token; it refuses to send a scan when there is no session. `src/api/scans.js` reads own scans and the leaderboard. `src/api/imagePrep.js` shrinks photos.
- `src/screens/scan/ScanScreen.js` is the capture flow. Capture is manual, front then back. The camera uses `zoom={0.3}`; without it coins are too small in the frame to read. Photos are resized to 1280 px on the long edge before upload.
- Each scan gets an id. A late result from an abandoned scan is ignored, and a double tap on the capture button is blocked. There is no request cancel, so an abandoned scan still finishes on the server and counts toward the limit.
- Pure logic lives in plain modules with no React Native imports (`scanFlowLogic.js`, `scanErrorLogic.js` and similar) so `node --test` can load them. Put new testable logic there.
- Home shows the user's last three real scans. Stats reads history from Supabase. The leaderboard refreshes every 15 seconds.
- The server address comes from `EXPO_PUBLIC_API_BASE_URL`. If it is missing the app falls back to `http://localhost:5000`, which only works in a simulator.

## Server notes

- `server/app.py`: routes, OpenAI call, evidence gate, Numista, pricing, daily limit, saving.
- `server/auth.py`: token verification through the project's JWKS. Only ES256 and RS256 are accepted. Audience `authenticated`, issuer `<SUPABASE_URL>/auth/v1`.
- `server/require_user.py`: an older check used by `/api/me` and `/api/test-scan`. It raises at import if `SUPABASE_URL` or `SUPABASE_ANON_KEY` is missing, so the server will not start without both.
- `server/supabase_admin.py`: every service-role database call. Retries 502, 503 and 504 from Supabase twice. Nothing else is retried.
- `server/badges.py`, `server/mock_openai.py`, `server/tests/`.
- `OPENAI_MODEL` defaults to `gpt-4o-mini`. `OPENAI_REASONING_EFFORT` sets the reasoning effort; it is left out of the request for `gpt-4*` and `gpt-3.5*` models, which reject it. Real-coin testing used `gpt-5.6-luna` with low effort. The default model was never tested on real coins.
- There is no `render.yaml`, Procfile or Dockerfile. The service root must be `server/` because imports are flat.

## Tests

```bash
npm test

python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
SUPABASE_URL=https://test.supabase.co SUPABASE_ANON_KEY=test OPENAI_API_KEY= NUMISTA_API_KEY= \
  python3 -m unittest discover -s server/tests
```

An audit on October 5 ran 56 JavaScript and 245 Python tests, all passing, on a trial merge that matches `9b95f30` except for a one-line camera fix. They have not been run since `e1b9719`. The Python tests need the two dummy Supabase values or five test files fail to import.

Every outside service is faked in these tests. They do not cover React components, the live database rules, or a real phone. After any change to the scan flow, scan a real coin.

## Why it is built this way

Each of these came from a real failure. Read the reason before changing any of them.

- **One OpenAI call with a strict schema.** An earlier chain of four calls included a value guessed by the AI.
- **Photos resized to 1280 px.** Full-size photos used about 17,000 input tokens a scan and hit rate limits on a new OpenAI account.
- **2000 output tokens and low reasoning effort.** The model once spent its whole budget thinking and returned nothing. That case is `ai_incomplete`, not "coin not recognized".
- **Observations first, then a deterministic gate.** Confidence numbers were high on wrong answers.
- **Issuer codes, issue-level years, exact denominations, variant classes.** Each fixed a real mismatch: other countries' coins returned first for a UK search, a 2 pence candidate tying with the real 20 pence, proof and bullion versions competing with an ordinary coin.
- **Daily limit in the database, written before the paid call.** A counter in memory resets on every restart and is not shared between workers.
- **Explicit GRANT statements for every table.** The server once got `42501 permission denied for table api_usage` although it uses the service role. Bypassing row level security does not grant table rights. See `docs/SUPABASE.md`.
- **Badges on the server.** When the app worked them out, a user saw five badges on their own screen while everyone else saw two.
- **A 5, 10 or 25 cent face value never implies a US nickel, dime or quarter.** A Canadian 5 cents was being stored as a US penny.
- **404 and 405 handled before the catch-all 500.** Harmless wrong URLs looked like crashes in the logs.
- **Health check reports configuration.** A missing key silently switches the server to mock mode, and at one point nobody could tell which code a server was running.

## Not built yet

As of `9b95f30`. `HANDOFF.md` section 6 has the tasks and prompts.

- No App Store build setup: no `eas.json`, bundle id, icon or splash. The app has only run in Expo Go.
- No account deletion, password reset or change of display name.
- No privacy or support page.
- "Use as Guest" opens the scan screen, but a scan needs sign-in.
- Photo upload sends one picture, so most coins are rejected by the gate.
- `remaining_today` is returned by the server but not shown.
- The Numista catalog number is returned by the server but not shown or stored.
- Reads of a user's scans are not paged. Badge counts could go wrong past about 1,000 scans per user.
