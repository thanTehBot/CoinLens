# Teaching notes

For an instructor or mentor who picks this project up, and for the students to check their own understanding.

The course behind this project treated the students as the engineers in charge of an AI coding tool. The AI wrote most of the code. The teaching was about architecture, where trust sits, testing, deployment, debugging and release. Keep that approach: nobody needs to memorize React syntax, but everyone should be able to explain every arrow in the diagram in `docs/AI_CONTEXT.md`.

## Six questions

If someone can answer these in their own words, they understand the system.

1. **Why can the app hold the Supabase publishable key but not the service-role key?**
   The publishable key is meant for clients and is limited by row level security. The service-role key bypasses those rules, so it stays on the server.
2. **Why does the server take the user id from the token instead of from the request?**
   Anyone can type any id into a request. A token signed by Supabase cannot be forged.
3. **Why can the app read its own scans directly but not save one?**
   Reading your own rows is safe. A saved scan carries a value. If the app could save scans, a modified app could save any value it liked.
4. **What happens when Numista cannot match the coin with confidence?**
   The scan is saved without a value. "Not available" is better than a made-up number.
5. **Why is the daily limit recorded before the OpenAI call?**
   The cost happens when the call is made, even if the scan fails afterwards. So every attempt counts, including failed ones.
6. **Why are badges worked out on the server?**
   With one set of rules there is nothing to get out of step. When the app and the server both had badge rules, users saw different counts.

## Trace one scan

Have each student follow one real scan from the phone to the database and back, pointing at the code and the log line for each step:

photo, resize, token, server, daily limit, OpenAI, evidence gate, Numista, save, history.

The server writes an `[identify]` line for every scan and `[numista]` lines for the matching steps, so the trace can be done from the Render log of a scan they just made.

## Checkpoints

1. Explain what the app, the server and Supabase are each responsible for.
2. Explain row level security and GRANT as two separate layers, using the `42501` story in `docs/SUPABASE.md`.
3. Read `/api/health` and say whether the server is safe to test against.
4. Run both test suites, break a rule on purpose (for example, loosen the evidence gate), and watch a test fail.
5. Sign up, scan, and check history, badges and leaderboard on a real phone. Repeat with a second account and confirm neither sees the other's history.
6. Delete a disposable account from inside the app (once HANDOFF task 2 is built) and confirm its rows are gone.

## Stories worth retelling

Things that went wrong on this project, and one trap that is still there.

- **The confident wrong answer.** The AI named real coins with the wrong year and a high confidence score. The fix was to make it write down what it could read first, and to have plain code check that. Lesson: check what the AI actually read, not how sure it says it is.
- **The permission error with the master key.** The server had the key that bypasses row level security and still got "permission denied". Lesson: two layers, two different jobs.
- **Which code is running?** A server was running code without the latest fixes, and nothing showed which code it had. Lesson: have the server report its own commit.
- **The small change that broke scanning.** One camera setting changed, coins became too small in the photo to read, and every automated test still passed. Lesson: scan a real coin after every change to the scan screen.
- **The trap.** If the OpenAI key is missing, the server answers every scan with the same fake 1946 cent and saves it as a real scan. Lesson: read the health check before believing a result.

## Splitting the remaining work in two

The tasks in `HANDOFF.md` section 6 split into two tracks:

| Track A: app and release | Track B: server and database |
|---|---|
| Task 1, App Store build setup | Task 2, account deletion (server route) |
| Task 2, account deletion (button and dialog) | Task 3, privacy and support pages |
| Task 5, two-photo upload and retake hints | Task 4, remove old routes |
| Task 7, waiting message for the sleeping server | Task 6, sign-up email |
| Task 8, Numista credit | Every check in `supabase/verify.sql` says PASS |
| Screenshots and the store listing | Task 9, final check |

For account deletion, agree on the contract first (`DELETE /api/account`, no body, returns `{"deleted": true}`) so both sides can work at once.

After each round, each student explains the other's change before it is merged.

Start the Apple and TestFlight steps early. Accounts, certificates and review all take longer than expected, and none of it can be hurried on the last day.

## Done means

- Both students can answer the six questions.
- No secret is in the app or in Git.
- Every check in `supabase/verify.sql` says PASS on the live project.
- Sign-up with email confirmation works for a brand new address.
- A real coin scans, saves, and appears in history, badges and the leaderboard on a TestFlight build.
- A rejected coin gives a useful retake hint.
- Account deletion works.
- Both test suites pass.

## Credit

`HANDOFF.md` section 8 says who built what. `git blame` on `main` is misleading for work done before September 22, 2026.
