# CoinLens

## Expo Backend URL

For local Expo runs, copy `.env.example` to `.env.local` and set the backend URL:

```env
EXPO_PUBLIC_API_BASE_URL=https://YOUR-SERVICE.onrender.com
```

Then restart Expo with a clean cache:

```sh
npx expo start -c
```

For EAS builds, set `EXPO_PUBLIC_API_BASE_URL` in the EAS environment for the build profile. `app.json` also has `expo.extra.apiBaseUrl` as a fallback, but environment variables are preferred so the deployed Flask URL is not hardcoded into source.

## Authenticated Expo scans

The real camera and gallery handlers call `identifyCoin`, which uses the shared
`authenticatedRequest` helper. It reads the current persisted Supabase session,
requires an access token, and sends it to Flask as a Bearer token. Missing or
unreadable sessions stop the request before network access. The listing request
uses the same helper.

Scan bodies contain `front_image`, optional `back_image`, `source` (`camera` or
`gallery`), and `tz_offset_minutes` from `new Date().getTimezoneOffset()`.
They do not contain a user ID. Flask must derive ownership from the verified JWT.
Supabase sign-in/sign-up remain direct client requests.

Public client configuration (placeholders only):

```env
EXPO_PUBLIC_API_BASE_URL=https://YOUR-SERVICE.onrender.com
EXPO_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=YOUR-PUBLISHABLE-KEY
```

Only public configuration belongs in Expo. Set these in the build environment
and restart/rebuild the app after changes. The existing
`expo.extra.apiBaseUrl` fallback remains supported; the final localhost fallback
is for development and is not a usable backend address on a physical phone.

## Render settings for the instructor

Use a Python web service with:

- Root directory: `server`
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --timeout 180 app:app`
- Health check path: `/api/health`
- Required environment names in this checkout: `SUPABASE_URL`, `SUPABASE_ANON_KEY`
- For real AI identification: `OPENAI_API_KEY`; leave `MOCK_MODE` and
  `USE_MOCK_COIN_RESPONSE` false
- Optional feature environment names: `NUMISTA_API_KEY`, `PCGS_BEARER_TOKEN`,
  `SHEETDB_URL`, `ADMIN_CODE`, `LOG_LEVEL`

Render supplies `PORT`. Set backend variables in Render before startup:
the auth modules read configuration during import. The longer worker timeout
accommodates the existing sequence of upstream requests; it is not a guarantee
that every upstream call will finish within that time.

This checkout's identify endpoint verifies auth and returns identification data
but does not persist scans. Student A's merge must supply trusted writes and
the `public.scans` table/RLS policies. Confirm any additional backend environment
names against that merged implementation. No deployment is performed by this task.

## Render Mock Mode

In Render, set `MOCK_MODE=true` for a keyless mock deployment. With mock mode on, the Flask API returns deterministic canned data containing `MOCK RESPONSE FROM RENDER FLASK SERVER` and does not call OpenAI, Numista, PCGS, or SheetDB.

## Saved scan history

Open Account > Detailed Stats to read saved scans directly from Supabase.
The screen calls `fetchMyScans()` on mount and supports pull-to-refresh and
a Refresh scans button. It remounts when the signed-in account ID changes,
and ignores requests that finish after unmount or after a newer refresh.

The helper uses the existing authenticated Supabase client to SELECT from
`public.scans`, ordered by `scanned_at DESC NULLS LAST` then `created_at DESC`.
There is no client user-ID filter and no client scan INSERT, UPDATE, or DELETE.
Ownership depends on Student A's SELECT RLS policy. The display uses
`coin_name`, `scanned_at` (falling back to `created_at`), and
`estimated_value`. Unavailable values remain null and are excluded from
averages; a real zero is included.

This is Option B: legacy AsyncStorage writes and the account/badge/leaderboard
consumers remain temporarily unchanged. Detailed Stats is the Supabase history
surface. Its summary covers the rows returned by Supabase's configured response
limit; pagination is not added in this task.

## Manual integration after Student A's merge

1. Apply Student A's schema and RLS through the instructor's process. Confirm
   that Flask verifies the JWT and writes the scan using its subject as owner.
2. Configure the public Expo variables above and the merged backend's environment.
   Confirm the backend health endpoint responds, then restart Expo.
3. Sign in as user A. Select a gallery image, tap Start Scan, and check the normal
   result UI. Confirm the request includes `source: "gallery"` and the phone's
   timezone offset, with no user ID. Inspect authorization presence without
   copying, logging, or sharing the JWT.
4. Capture the front and back through Take Photo. Confirm the same real endpoint
   receives both images and `source: "camera"`.
5. Open Account > Detailed Stats. Confirm both saved rows appear newest-first.
   Refresh and confirm NULL estimates show Value unavailable and do not lower
   the average. Check an account with no saved scans.
6. Sign out and sign in as user B. Confirm Detailed Stats does not expose user A's
   rows. This is the live ownership/RLS check; unit tests cannot prove policies.
7. Disable network access and refresh: confirm a readable error and retry path.
   Restore connectivity and refresh again.
8. Without a session, attempting a scan must show a sign-in error before calling
   Flask. Existing guest entry remains, but authenticated identification requires
   signing in.

Run `npm test` for the JS tests. No backend changes, migration, push, or deployment
are part of this client task.
