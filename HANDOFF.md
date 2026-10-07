# CoinLens handoff

Written October 7, 2026, after the last class of the Coding Mind individual project course.

This file is for the two students who own the project, their parents, and any instructor who picks it up later. The course instructor's work ended with the final class, so this file is meant to answer the questions the instructor would have answered. Section 9 lists the other files that go with it.

## 1. Where the project stands

CoinLens is a phone app that photographs both sides of a coin, identifies it and shows an estimated value.

- **It works end to end.** On October 6 the students demonstrated sign-up, sign-in, a real coin scan with a price, history, badges and the leaderboard, all on their own accounts.
- **It runs in Expo Go only.** It has not been built for TestFlight or the App Store.
- **It is not ready to publish.** Section 6 lists what is left.
- **Code:** branch `main`. On October 6 `main` was at commit `9b95f30`, and the server on Render reported that same commit.
- **Tests:** in an audit on October 5, 245 Python and 56 JavaScript tests passed on a trial merge that matches this code except for a one-line camera fix. They use fake services, so they do not replace testing on a real phone.

## 2. How it works

    Phone app (Expo, React Native)
      signs in with Supabase
      sends two photos to the server
    Server (Python Flask, on Render)
      checks who the user is from the Supabase sign-in token
      asks OpenAI to read the coin
      rejects the answer unless the country, value and year were read off the coin
      asks Numista for the matching coin and its price
      saves the scan in Supabase
    Phone app
      reads the user's own scans from Supabase
      asks the server for badges and the leaderboard

`docs/AI_CONTEXT.md` has the full version.

## 3. Who owns what

| Piece | What it does | Owner |
|---|---|---|
| GitHub repo | The code | The students |
| Render | Runs the server and holds the secret keys | One student's account |
| Supabase | Sign-in and the database | One student's account |
| OpenAI | Reads the coin photos. Costs money per scan | Whoever pays for the OpenAI account |
| Numista | Coin catalog and prices | Student key, free plan |
| Expo Go | Runs the app on a phone during development | Free app |

No instructor account is part of the app. Nothing needs to be transferred.

## 4. Do these now: cost and safety

The server is online and uses paid services. These steps limit what it can cost and who can use it.

1. **OpenAI hard limit.** The owner of the OpenAI account opens Settings, Organization, Limits, chooses Edit spend limit, enters a monthly amount (for example $10) and turns on "Enforce a hard limit". After that, scans fail when the limit is reached instead of running up a bill.
2. **Daily scan limit.** On Render, under Environment, set `DAILY_SCAN_LIMIT` to 10. This is scans per user per day, and failed scans count.
3. **Database check.** In Supabase, open the SQL editor and do these in order:
   1. Paste and run `supabase/verify.sql`. It only reads.
   2. Paste and run `supabase/migrations/0003_tighten_privileges.sql`.
   3. Run `supabase/verify.sql` again. Every check should say PASS. The last two rows are INFO, for you to read.
   4. Open the app and check that history, badges and the leaderboard still load.

   If a check does not say PASS, or the app stops loading something, `docs/SUPABASE.md` has the fix for each check.
4. **Do task 4 soon.** It removes leftover server routes that the app no longer uses.
5. **Sign-up email is not set up.** Task 6 sets it up and turns on "Confirm email". Until then, share the app only with people you know and keep the OpenAI limit low.
6. **Supabase pauses when unused.** A free project is paused after about a week in which the app is hardly used. Logging in to the Supabase website does not count as use. While it is paused, nobody can sign in and nothing loads. To wake it, the owner logs in to Supabase and presses Restore. Supabase emails the owner before pausing and keeps a paused project for a limited time (one year according to its help page in October 2026), so do not leave it paused for long. If the app still fails after a restore, see the note about keys in `docs/SUPABASE.md`.
7. **Taking a break?** Suspend the Render service from its Settings page. Nothing can be spent while it is suspended.
8. **Never put keys in the app or in GitHub.** The OpenAI, Numista and Supabase service-role keys live only on Render's Environment page.

## 5. Running it

On a laptop, in the repo folder:

    git pull
    npm install
    npx expo start -c

The app needs a file named `.env.local` in the repo folder with three lines. These values are public, but the file is not stored in GitHub. The Render address looks like `something.onrender.com`. Do not put a slash at the end.

    EXPO_PUBLIC_API_BASE_URL=https://<your Render address>
    EXPO_PUBLIC_SUPABASE_URL=<your Supabase project URL>
    EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<your Supabase publishable key>

Check the server at any time:

    curl -s https://<your Render address>/api/health | python3 -m json.tool

What to look for:

- `mock_mode` is false and `mock_reason` is empty. If the OpenAI key is missing, the server quietly switches to fake results (a 1946 wheat cent worth $12.34) and saves them as real scans.
- `has_openai_key`, `has_numista_key` and `has_service_role_key` are true.
- `supabase_host` matches the Supabase URL in `.env.local`. If they differ, scans fail with a sign-in error.
- `openai_model` is the model you chose. Keep `OPENAI_MODEL` set on Render. It was `gpt-5.6-luna` on October 6, and scans were never tested on the default model.
- `git_commit` shows which code the server is running.

Run the tests before pushing changes. The first time, set up Python:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r server/requirements.txt

Then, every time:

    npm test
    SUPABASE_URL=https://test.supabase.co SUPABASE_ANON_KEY=test OPENAI_API_KEY= NUMISTA_API_KEY= python3 -m unittest discover -s server/tests

Type the second command exactly as shown. Its values are made up on purpose, so the tests never touch the real services.

Good to know:

- Pushing to `main` redeploys the server on Render.
- The free Render server sleeps after 15 minutes without use and takes about a minute to wake. The first scan after a break is slow.
- After changing `.env.local`, restart Expo with `-c`.
- For a good scan: coin flat on a dark surface, no fingers on it, no glare, and use Take Photo for both sides. Uploading a single photo usually fails (task 5).
- Do not remove `zoom={0.3}` from the camera view in the scan screen. Without it coins are too small to read.
- The database setup files are in `supabase/migrations/`. If you ever rebuild the database, run them in this order: `20260914000000_profiles_and_scans.sql`, `0001_api_usage_and_leaderboard.sql`, `0002_grant_api_usage_service_role.sql`, `0003_tighten_privileges.sql`. Then run `supabase/verify.sql`.
- Every Render setting and environment variable is listed in `docs/SERVICES.md`.

## 6. Before publishing

### Decide first

- **Whether to publish at all.** The app is a finished class project as it stands.
- **A new name.** "CoinLens" is already used by other coin identifier apps on the App Store, and a parent found that "Obverse" belongs to another coin collecting app in development. Pick a name, search the App Store for it, and only then buy a domain or choose the bundle ID.
- **An Apple Developer account.** It must belong to an adult and costs $99 a year. With an Individual account, that adult's legal name is shown as the seller.
- **Numista's rules.** Their API page says apps must show Numista's catalog number (N#) on results and name Numista as the source. The free plan allows 2,000 requests a month. One scan uses six or seven, so that is about 300 scans a month for all users together. The paid plan has a 100 euro activation fee and a 100 euro monthly minimum. Read their terms, and ask them before adding ads or charging money.

### Rules for every code change

Give these to your AI coding tool along with any task below.

- Read `docs/AI_CONTEXT.md` first. If your change alters how something works, update that file in the same change.
- Work on a new branch. Run both test suites. Test on a real phone before merging to `main`.
- The server decides who the user is from the verified Supabase token. Never trust a user id sent by the app.
- Secret keys stay on the server. The app only gets the three `EXPO_PUBLIC` values.
- Only the server saves scans. Badge rules live in `server/badges.py`.
- If the country, value or year was not read off the coin, the scan is rejected and nothing is saved. A confident AI answer does not override that. If the coin is identified but no price is found, the scan is saved with no value.

### Task 1. App Store build setup

**Why:** a store build needs settings that Expo Go never used. Today a store build would crash on launch, because it cannot read `.env.local` and so does not know the server and Supabase addresses.

```text
Set this Expo app up for an App Store build. Read app.json, package.json, src/api/client.js and src/api/supabase.js first.

1. app.json: set ios.bundleIdentifier and android.package to <BUNDLE_ID> and the display name to <APP_NAME>. Add ios.buildNumber, an icon (assets/icon.png, 1024 by 1024), a splash, and ios.config.usesNonExemptEncryption set to false.
2. The app never records audio. Configure the expo-camera and expo-image-picker plugins so no microphone permission is requested. Confirm with: npx expo config --type introspect
3. Add eas.json with a production profile (autoIncrement on) and a simulator profile (ios.simulator true). The three EXPO_PUBLIC_* values must reach cloud builds, because .env.local is not uploaded. Put them in the build profile env or in EAS environment variables. They are public values.
4. Today, if those values are missing, the app crashes on launch and the API address falls back to localhost. Add a small pure function that checks the config, never falls back to localhost outside development, and show a "Configuration missing" screen instead of crashing. Add tests for it.
5. Run: npx expo install --fix, then npx expo-doctor, then npm test.

Do not change scan logic. Report the changes, the iOS permissions and bundle ID from the introspect output, and the test counts.
```

Then make a free Expo account, install the build tool with `npm install -g eas-cli`, run `eas login` and `eas init`, and build with `eas build --profile simulator --platform ios`. That build does not need an Apple account.

**Done when:** `npx expo-doctor` passes, the simulator build succeeds, and the app still runs in Expo Go.

### Task 2. Account deletion

**Why:** Apple rejects apps that have sign-up but no way to delete the account from inside the app.

First run `supabase/verify.sql` and look at check 13. It must say PASS, which means deleting a user also removes their profile, scans and usage rows. If it says WARN, fix it with the steps in `docs/SUPABASE.md` before building this.

```text
Add account deletion. Apple requires it for apps with sign-up.

Server (server/supabase_admin.py and server/app.py): add delete_auth_user(user_id), which calls DELETE {SUPABASE_URL}/auth/v1/admin/users/{id} with the service-role headers and the existing retry helper. Treat 404 as success. Add DELETE /api/account behind @require_auth. It must use only g.user_id from the verified token and ignore any id in the body or query. Return 200 {"deleted": true} on success and 503 on failure.

App (src/api/client.js and the Account screen): add a "Delete account" button with a confirmation dialog. On success, sign out on the device.

Tests: 401 without a token; a different user id in the body is ignored; 404 counts as success; an upstream 500 becomes 503.

Report the changes and the test counts.
```

**Done when:** deleting a test account from the app removes its rows from `profiles`, `scans` and `api_usage`, and that account can no longer sign in.

### Task 3. Privacy policy and support pages

**Why:** App Store Connect requires a privacy policy URL and a support URL.

```text
Add two public pages to the Flask server: GET /privacy and GET /support. No sign-in needed. Simple HTML.

The privacy page must say, in plain words:
- What is stored: email address, display name, and scan results (coin details, estimated value, date and time).
- Coin photos are sent to OpenAI to identify the coin. The app does not store them.
- Coin details are sent to Numista to find a catalog match and price.
- Accounts and data are hosted on Supabase. The server runs on Render, which keeps logs.
- Users can delete their account inside the app.
- A contact email: <CONTACT_EMAIL>.

The support page gives the contact email and three tips for a good scan.

Add a link to the privacy page on the Account screen. Add tests: both pages return 200 as HTML without a token.
```

**Done when:** both URLs open in a phone browser. Have an adult read the privacy page before it goes live, because it is a promise to your users.

### Task 4. Remove dead ends and old code

**Why:** a button that leads nowhere can get the app rejected, and server code the app no longer uses should not stay online.

```text
Clean up leftovers that would confuse a user or an App Store reviewer. Check each one first, since some may already be gone.

1. "Use as Guest": guests cannot scan, because every scan needs a signed-in user. Remove the guest button and the state that only supports it.
2. The Admin screen still reads the old SheetDB sheet and phone storage, so it shows nothing real. Remove the screen, its button and its route.
3. Server routes the app no longer calls: /api/numista-specs, /api/pcgs-value, /api/log-scan, /api/scans and /api/test-scan. Remove them and their client helpers, and replace their tests with checks that they return 404.
4. Lines marked TEMP DIAGNOSTIC in the Badges and Leaderboard screens.
5. Stop tracking server/tests/__pycache__ with: git rm --cached -r server/tests/__pycache__

Keep /api/health, /api/me, /api/identify-coin, /api/badges/me and /api/leaderboard. Leave /api/generate-ebay-listing as it is; it is switched off.

Update docs/AI_CONTEXT.md to match. Report what you removed and the test counts.
```

If you would rather keep an Admin screen, rebuild it on real Supabase data through a server route instead of removing it.

**Done when:** every button in the app leads somewhere that works, and the removed routes return 404.

### Task 5. Photo upload

**Why:** a single uploaded photo cannot pass, because most coins have the date on one side and the value on the other. Right now the upload option fails for most coins.

```text
Make photo upload work with two photos, and tell the user what to retake when a scan is rejected.

Upload (the scan screen and scanFlowLogic.js): let the user pick two photos, front then back (expo-image-picker: allowsMultipleSelection true, selectionLimit 2). Send the second one as back_image. The server already accepts it. Update the label to say "Pick a photo of each side". Update the existing test that expects a single photo.

Retake hints (scanErrorLogic.js and the scan screen): the server response for a rejected scan includes identification.rejection with a stage and reasons. Use it to show one specific hint:
- the year failed: "Make the date sharp and readable"
- the value failed: "Show the face-value text"
- only one photo was sent: "This photo shows one side. Add the other side."

Never loosen the server check. Add tests for the hint logic.
```

**Done when:** uploading the front and back of a US cent identifies it, and uploading one side shows the hint about the other side.

### Task 6. Sign-up email

**Why:** real users need a confirmation email that arrives, with a link that ends somewhere sensible.

1. An adult creates an email address for the app and a free account at a mail service that offers SMTP. SMTP is the standard way for one service to send email through another. Brevo's free plan worked in a test on another project. Verify the sender address there and create an SMTP key.
2. In Supabase, open Authentication, Emails, SMTP Settings and turn on custom SMTP. For Brevo: host `smtp-relay.brevo.com`, port `587`, username is the Brevo SMTP login, password is the SMTP key, sender is the verified address.
3. Add the landing page with this prompt:

```text
Add GET /confirmed to the Flask server. No sign-in needed. It returns a small HTML page that says the email is confirmed and to go back to the app and sign in. Add a test that it returns 200 as HTML.
```

4. In Supabase, open Authentication, URL Configuration and set Site URL to `https://<your Render address>/confirmed`.
5. In Supabase, open the Email provider settings and turn "Confirm email" on.
6. Test with an address that has never signed up and does not belong to a member of the Supabase project.

If no email arrives, look at Logs, Auth in Supabase and at the mail service's own log. Supabase limits a new SMTP setup to 30 emails an hour; raise that under Authentication, Rate Limits if you need more. Accounts made while confirmation was off were confirmed automatically and keep working. `docs/SERVICES.md` has more, including what to do once you own a domain.

**Done when:** a new user gets the email, taps the link, sees the confirmation page and can sign in.

### Task 7. The sleeping server

**Why:** the free server takes about a minute to wake, so the first scan looks frozen. A reviewer may decide the app is broken.

```text
The server sleeps when idle and takes about a minute to wake.

1. After sign-in, call GET /api/health in the background to wake the server. Ignore errors.
2. While a scan has been waiting more than 8 seconds, show "Waking up the server. This can take a minute."
3. Make sure the scan request does not give up before 90 seconds.

Do not change what the server does. Add tests for any pure logic you extract.
```

The other fix is a paid Render instance that never sleeps.

**Done when:** a scan made after 20 idle minutes shows the waiting message and then finishes.

### Task 8. Credit Numista

**Why:** Numista's API page requires apps to show their catalog number and name them as the source.

```text
On the scan result, when the server found a catalog match, show the Numista catalog number as "N# <type id>". The server already returns the type id. Add the line "Coin data: Numista" on the result and on the Account screen. Show nothing extra when there is no match.
```

Saved scans do not store the catalog number, so showing it in history would need a new database column.

### Task 9. Final check before submitting

**Why:** after many small changes, this finds anything that no longer matches the rules or the docs.

```text
Act as a release tester, not a feature developer. Read docs/AI_CONTEXT.md and HANDOFF.md first. Do not change how the app behaves.

1. Run both test suites and report the counts.
2. Check each rule under "Rules that must not change" in docs/AI_CONTEXT.md against the code. Report any that no longer hold, with file and line.
3. List every server route, whether it needs sign-in, and whether the app calls it. Flag any route the app does not call.
4. List every environment variable the code reads. Compare with server/.env.example and docs/SERVICES.md and report the differences.
5. Search the repo for anything that looks like a key, password, token, private address or personal email. Report the file and line only, never the value.
6. Confirm the app asks only for camera and photo permissions.
7. Update docs/AI_CONTEXT.md wherever it no longer matches the code.

Finish with a list ranked Must fix, Should fix, Can wait.
```

Then test by hand on the TestFlight build:

- Sign up with a brand new email, confirm it, sign in.
- Scan a common coin with both sides. It shows a value and appears in history.
- Photograph something that is not a coin. It is rejected with a useful hint.
- Upload two photos from the gallery.
- Badges and leaderboard load.
- A second account on another phone cannot see the first account's history.
- Wait 20 minutes, then scan. The waiting message appears and the scan finishes.
- The privacy and support links open.
- Delete an account from inside the app, then try to sign in with it.

**Done when:** the Must fix list is empty, every check in `supabase/verify.sql` says PASS, and every line above works.

### Worth doing later

- Password reset.
- Treat "dime" and "10 cents" as the same value, so more US coins get a price. In testing, a dime only matched because of its year.
- Show how many scans are left today. The server already returns `remaining_today`.
- Show only a simple "ok" on the public health check and move the details behind sign-in.

## 7. App Store steps, after the code is ready

1. The adult who owns the Apple Developer account signs in at developer.apple.com and App Store Connect and accepts the agreements.
2. Build and upload with `npx testflight`. When it asks for the Apple sign-in, the account owner types it themselves. Nobody else should ever be given the password or the codes. With an Individual account only the owner can create the certificates a build needs, so they need to be at the keyboard for the first build.
3. In App Store Connect, add testers under Users and Access, then TestFlight. Internal testers can install without a review. TestFlight has a minimum age, so testing may need an adult's phone.
4. Fill in the listing: screenshots, description, privacy answers, age rating, the privacy and support URLs, and review notes with a demo account the reviewer can sign in with.
5. Submit for review. A new app usually takes one to three days, and a rejection adds another round.

Useful pages:

- Apple Developer enrollment: https://developer.apple.com/programs/enroll/
- Apple's account deletion rule: https://developer.apple.com/support/offering-account-deletion-in-your-app
- Expo builds: https://docs.expo.dev/build/introduction/
- Expo TestFlight command: https://docs.expo.dev/build-reference/npx-testflight/
- Expo App Store submission: https://docs.expo.dev/submit/ios/
- OpenAI spend limits: https://developers.openai.com/api/docs/guides/spend-limits
- Numista API plans and rules: https://en.numista.com/api/pricing.php

## 8. Who built what

- **The students:** the app's screens and navigation, camera and photo upload, sign-up and sign-in with Supabase, the database tables and privacy rules, the first Flask server and its deployment on Render, the history and stats screens, badges and leaderboard ideas, real recent scans on the home screen, and the scan animation.
- **The instructor, with AI tools:** the server's scan pipeline (reading the coin with OpenAI, the evidence check, Numista matching and pricing, the daily limit, saving scans, badge rules, the leaderboard endpoint), most of the automated tests, and the health check details.
- **Everyone:** used AI coding tools throughout.

A note for a future instructor: on September 22 the combined student and instructor code was copied into `main` as one snapshot, so `git blame` on `main` credits one person with almost everything from before that date. The real history is on the `mvp` and `seperate` branches.

## 9. Where to find things

| File | What it is |
|---|---|
| `HANDOFF.md` | This file: status, settings to change now, and the tasks left |
| `docs/AI_CONTEXT.md` | How the system works and the rules it must keep. Give it to your AI tool before any task |
| `docs/SUPABASE.md` | The database: tables, who can do what, setup, checks and fixes |
| `docs/SERVICES.md` | Settings for Render, Expo, OpenAI, Numista, email and Apple |
| `docs/TEACHING_NOTES.md` | For an instructor, and a self-check for the students |
| `supabase/migrations/` | Database setup files, run by hand in the order given in section 5 |
| `supabase/verify.sql` | One query that checks the live database |
| `CONTEXT_EXPORT.md`, `PROTOTYPE_PLAN.md` | History from September. Not current |

## 10. Getting more help

- Coding Mind Academy can tell you about a follow-on project class.
- The official pages listed in section 7 and in `docs/SERVICES.md`.
- The course instructor's work on this project ended with the final class on October 6, 2026.
