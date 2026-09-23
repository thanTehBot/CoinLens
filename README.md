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

## Render Mock Mode

In Render, set `MOCK_MODE=true` for a keyless mock deployment. With mock mode on, the Flask API returns deterministic canned data containing `MOCK RESPONSE FROM RENDER FLASK SERVER` and does not call OpenAI, Numista, PCGS, or SheetDB.

## Merged local improvements

Sign-up includes password confirmation and show/hide controls. Camera and gallery scans, and listing requests, require a readable Supabase session before making requests. Flask verifies the token and saves identified scans under its authenticated owner.

Detailed Stats reads saved scans directly from Supabase under row-level security, with newest-first ordering, pull-to-refresh, a refresh button, and visible loading errors. Unknown estimates are excluded from averages; zero remains a valid value. Results are limited by the configured Supabase response limit. Account statistics, badges, and the leaderboard retain the MVP integration.

For a new database, apply the retained foundation migration `supabase/migrations/20260914000000_profiles_and_scans.sql` before `0001_api_usage_and_leaderboard.sql` and `0002_grant_api_usage_service_role.sql`; the MVP migrations assume profiles and scans already exist. Their filenames do not express this dependency order. No database changes are applied by merging the code.

Run `npm test` for JavaScript checks. With `server/requirements.txt` installed and test configuration for `SUPABASE_URL` and `SUPABASE_ANON_KEY`, run `python -B -m unittest discover -s server/tests`. The backend tests mock external services. Verify camera/gallery capture and history refresh on a device before release.
