# Services and configuration

How each outside service has to be set up for CoinLens to run. Use this to rebuild a piece from scratch or to work out why one is misbehaving.

No real addresses, keys or account names belong in this file or anywhere else in the repo. For what to build next, see `HANDOFF.md`.

| Service | Job | Secrets it holds |
|---|---|---|
| Expo | Builds and runs the phone app | None. Three public values |
| Render | Runs the Flask server | All of them, as environment variables |
| Supabase | Sign-in and database | Its own keys |
| OpenAI | Reads the coin photos | API key, paid per scan |
| Numista | Coin catalog and prices | API key |
| Mail service | Sends sign-up emails through Supabase | SMTP key, stored in Supabase |
| Apple | TestFlight and the App Store | The account owner's sign-in |

## The app (Expo)

A file named `.env.local` in the repo folder, not stored in Git:

```text
EXPO_PUBLIC_API_BASE_URL=<server address, no slash at the end>
EXPO_PUBLIC_SUPABASE_URL=<Supabase project URL>
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<Supabase publishable key>
```

- Anything starting with `EXPO_PUBLIC_` is built into the app and readable by anyone who has it. Never put a secret there.
- After changing the file, restart with `npx expo start -c`.
- `.env.local` wins over `.env`. If a value seems stuck, check both files.
- A store build does not see `.env.local`. The same three values have to be given to EAS (HANDOFF task 1).

## The server (Render)

Service settings that worked on the test deployment:

| Setting | Value |
|---|---|
| Type | Web Service, Python |
| Branch | `main`. Deploys when a push changes files inside the root directory |
| Root Directory | `server` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --workers 2 --timeout 120 --access-logfile -` |

The long timeout matters. One scan waits for OpenAI and then makes several Numista requests, which is longer than gunicorn's default 30 seconds.

The free plan sleeps after 15 minutes without requests and takes about a minute to wake up.

### Environment variables

Set these on the service's Environment page. `server/.env.example` is the starting point for running the server on a laptop.

| Name | Needed | Notes |
|---|---|---|
| `SUPABASE_URL` | Yes | Same project as the app |
| `SUPABASE_ANON_KEY` | Yes | The publishable key. The server will not start without it |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | The secret key. Saving scans, the daily limit, badges and the leaderboard all need it |
| `OPENAI_API_KEY` | Yes | **If it is empty the server switches to mock mode** and saves fake scans |
| `OPENAI_MODEL` | Yes | The code default is `gpt-4o-mini`, which was never tested on real coins. Testing used `gpt-5.6-luna` |
| `OPENAI_REASONING_EFFORT` | No | `low` in testing. Left out of the request for `gpt-4` and `gpt-3.5` models, which reject it |
| `NUMISTA_API_KEY` | For prices | Without it every scan is saved with no value |
| `DAILY_SCAN_LIMIT` | No | Scans per user per UTC day. Code default 20. Failed scans count |
| `MOCK_MODE`, `USE_MOCK_COIN_RESPONSE` | No | `true` gives fake results without calling OpenAI or Numista. Useful for practice, never for real use |
| `OPENAI_TIMEOUT_SECONDS`, `NUMISTA_TIMEOUT_SECONDS`, `PCGS_TIMEOUT_SECONDS` | No | Defaults 60, 20, 20 |
| `MAX_IMAGE_BYTES`, `MAX_CONTENT_LENGTH_BYTES` | No | Defaults 8 MB per photo, 24 MB per request |
| `PCGS_BEARER_TOKEN` | No | Optional second price source. Not set up or tested |
| `ENABLE_EBAY_LISTING` | No | Leave `false`. The feature is switched off |
| `LOG_LEVEL` | No | Default `INFO` |

Render sets `RENDER_GIT_COMMIT` and `RENDER_GIT_BRANCH` itself. The health check reports them.

Delete these if they are present. The code no longer reads them: `ADMIN_CODE`, `GEMINI_API_KEY`, `MOCK_AI`. Leave `SHEETDB_URL` unset; it belongs to an old feature that HANDOFF task 4 removes.

### Health check

```bash
curl -s https://<server address>/api/health | python3 -m json.tool
```

| Field | Should be |
|---|---|
| `mock_mode` | `false` |
| `mock_reason` | Empty. Otherwise it says why mock mode is on |
| `has_openai_key`, `has_numista_key`, `has_service_role_key` | `true` |
| `supabase_host` | The same host as `EXPO_PUBLIC_SUPABASE_URL` |
| `openai_model`, `openai_reasoning_effort` | What you set |
| `daily_scan_limit` | What you set |
| `git_branch`, `git_commit` | `main` and the commit you expect |

Check this after every deploy and before every demo.

### Reading the logs

Each scan writes one line starting `[identify] outcome=` that says how it ended and at which stage. Lines tagged `[numista]` show the search, the candidates and why one was chosen or none was. Start there when a coin is rejected or has no price. Photos are never in the logs.

## Supabase

See `docs/SUPABASE.md`.

## OpenAI

- The key lives only in the server's environment variables.
- Set a monthly budget with a hard limit: Settings, Organization, Limits. With a hard limit, scans fail when the budget is used up instead of costing more.
- A new account has low per-minute limits. When they are hit the app shows a rate-limit message with a wait time.
- Changing `OPENAI_MODEL` changes how well coins are read. After any change, scan several real coins and watch the `[identify]` log lines.

## Numista

- Request an API key from Numista and set `NUMISTA_API_KEY`.
- The free plan allows 2,000 requests a month. One scan makes six or seven requests, so that is about 300 scans a month across all users.
- Numista's API terms ask apps to show the catalog number (N#) on results and to name Numista as the source (HANDOFF task 8). Read the terms, and ask Numista before adding ads or charging money. The paid plan has a 100 euro activation fee and a 100 euro monthly minimum.

Figures checked in October 2026. Check the Numista API page before relying on them.

## Sign-up email

Supabase's built-in mailer only delivers to the project's own team members and sends two messages an hour. Real sign-up confirmation needs a mail service connected through SMTP. Brevo's free plan worked in a test on another project. Any SMTP provider works.

1. An adult creates the mail account and an email address for the app.
2. In the mail service, verify the sender address and create an SMTP key.
3. In Supabase: Authentication, Emails, SMTP Settings. Turn on custom SMTP and enter the host, port, login, SMTP key and sender. For Brevo the host is `smtp-relay.brevo.com` and the port is `587`.
4. Supabase limits a new custom SMTP setup to 30 emails an hour. Raise it under Authentication, Rate Limits if needed.
5. Set where the confirmation link lands and turn "Confirm email" on (HANDOFF task 6).
6. Test with an address that has never signed up and is not a project team member.

A sender at a free mail address (Gmail, Outlook) works but cannot be authenticated, so more mail lands in spam. Once the project owns a domain: add the domain in the mail service, add the DNS records it shows (DKIM and DMARC), create a sender such as `no-reply@<your domain>`, switch the sender in Supabase, and test again.

The confirmation link opens a web page. A link that opens the app directly needs a custom URL scheme in the Expo config and a matching redirect URL in Supabase, and it cannot be tested in Expo Go. That is an optional later improvement.

## Domain

The app runs without one. A domain is useful for the mail sender, for nicer privacy and support page addresses, and later for a custom server address. Choose the app's public name first. The domain account should belong to an adult, with auto-renew and two-step sign-in turned on, and the owner written down somewhere the family can find.

## Apple and Expo builds

- The Apple Developer Program account must belong to an adult or an organization. It costs 99 US dollars a year. With an Individual account the owner's legal name is shown as the seller, and only the owner can approve app signing.
- The account owner types their own password and verification codes. Nobody else should ever be sent them.
- Apple requires apps with sign-up to offer account deletion inside the app, a privacy policy URL, and App Privacy answers. CoinLens stores email, display name and scan results. Photos go to OpenAI to be read and are not stored.
- TestFlight has a minimum age, so testing may need an adult's phone.
- Steps are in `HANDOFF.md` sections 6 and 7.

## Official pages

- Supabase custom SMTP: https://supabase.com/docs/guides/auth/auth-smtp
- Supabase redirect URLs: https://supabase.com/docs/guides/auth/redirect-urls
- Supabase JWT signing keys: https://supabase.com/blog/jwt-signing-keys
- Supabase change to table grants: https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically
- OpenAI spend limits: https://developers.openai.com/api/docs/guides/spend-limits
- Numista API plans and rules: https://en.numista.com/api/pricing.php
- Brevo domain authentication: https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC
- Expo builds: https://docs.expo.dev/build/introduction/
- Expo App Store submission: https://docs.expo.dev/submit/ios/
- Expo linking: https://docs.expo.dev/linking/into-your-app/
- Apple Developer enrollment: https://developer.apple.com/help/account/membership/program-enrollment
- Apple account deletion rule: https://developer.apple.com/support/offering-account-deletion-in-your-app
- Apple app privacy: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy
