# Manual Smoke Checklist: Configurable Deployment Modes

**Status:** Manual validation checklist (not automated tests).

This checklist validates the four configurable deployment-mode axes end-to-end:
1. **Website transport mode** (HTTP vs. HTTPS)
2. **Authentication mode** (email magic-link vs. GHE OAuth)
3. **Participants mode** (givers_only vs. givers_and_consumers)
4. **Shared pool** (enabled vs. disabled)

**Prerequisites:**
- A fresh deployed CTC stack (control plane, proxy, web app) on a test domain
- An admin account (created with a valid PAT, then promoted via database or admin panel)
- Two license-holder PATs for scenario 2 (fresh user, then giver)
- Read access to control-plane logs (to retrieve magic-link URLs from the console email backend)

**Important:** The console email backend logs magic-link URLs to stdout/logs because sending real email is not configured. When testing email auth, copy the logged URL directly from `docker compose logs controlplane` or equivalent, then open it in a browser.

---

## Scenario 1: HTTP website mode + email magic-link auth

**Objective:** Verify the website runs over HTTP (no HTTPS/cert required), email auth works, and cookies are not marked `Secure`.

**Setup:**
```bash
CTC_WEB_TRANSPORT=http
CTC_APP_ORIGIN=http://ctc.example.test
CTC_AUTH_MODE=email
CTC_EMAIL_BACKEND=console
CADDYFILE=Caddyfile.http
```

**Steps:**
- [ ] Ensure control plane started without a transport/origin mismatch error (check logs)
- [ ] Open `http://ctc.example.test` in a browser (no certificate trust dialog should appear)
- [ ] See the login page with an email field
- [ ] Enter a test email (e.g., `user1@example.test`)
- [ ] Watch `docker compose logs controlplane` for the logged magic-link URL (looks like `http://ctc.example.test/auth/magic?token=...`)
- [ ] Copy the full URL and open it in the browser
- [ ] Expect: redirected to a logged-in session, the web app loads, and you see your email in the profile dropdown
- [ ] Open browser DevTools → Storage → Cookies and verify the session cookie (`ctc_session` or similar) does **not** have a `Secure` flag
- [ ] Close DevTools; the app remains functional (session is live)

**Expected result:** HTTP-only deployment works, email auth succeeds, cookies are not Secure.

---

## Scenario 2: Givers-only mode + pool disabled (defaults) + license consumption

**Objective:** Verify a fresh user with no PAT is blocked at the proxy, then after adding a PAT they can run Copilot. A second PAT holder funds the first user's request, consuming a grant.

**Setup:**
```bash
CTC_PARTICIPANTS_MODE=givers_only
CTC_SHARED_POOL=off
(or rely on shipped defaults; the live DB setting key is shared_pool_enabled,
 but the env seed var is CTC_SHARED_POOL)
```

**Preconditions:**
- Have two valid GHE PATs on hand:
  - `PAT_A`: a fresh PAT (new user, zero prior credits)
  - `PAT_B`: a license-holder PAT (has quota, intended to fund PAT_A's requests)
- Both PATs belong to different GHE users

**Steps:**

### Part 1: Fresh user (no PAT) is blocked
- [ ] Log in to the web app as `PAT_A`'s user (add PAT_A via the web UI)
- [ ] Note: the user now has a PAT stored but zero credits (freshly created)
- [ ] In a terminal, attempt a Copilot CLI completion:
  ```bash
  export HTTPS_PROXY=http://localhost:8080
  export NODE_EXTRA_CA_CERTS=/path/to/cert.pem
  export COPILOT_GITHUB_TOKEN=<fake-token-from-proxy>
  export GH_HOST=example.ghe.com
  gh copilot explain "what is this code?"
  ```
- [ ] Expect: HTTP 402 Payment Required from the proxy
- [ ] Check the web app: see a banner or message "Add a license to continue" (or similar, depending on UI)
- [ ] This confirms givers_only mode is active and the user is not a giver yet

### Part 2: After adding a PAT, user becomes a giver
- [ ] (Already done above, but confirm) PAT_A user now has a valid PAT stored
- [ ] Verify in the web app that the "Add a license" message is gone or the PAT is displayed
- [ ] Attempt the same Copilot command again
- [ ] Expect: success (200 OK from the proxy); Copilot completes the request
- [ ] This confirms the user is now a giver (has a valid, quota-bearing PAT)

### Part 3: Grant consumption from a second giver
- [ ] In the admin panel (or via API), add a grant: `PAT_B`'s user funds `PAT_A`'s user
  - (Implementation detail: create a row in the grants table or via the admin API if available)
- [ ] With `PAT_A`'s credentials, make another Copilot CLI request
- [ ] Expect: success (200 OK); the request consumes nano-AIU from the grant
- [ ] Verify in the accounting logs or database that a `Bucket.GRANT` row was charged (look for `source = "grant"` or `bucket_type = "GRANT"` in the accounting table)
- [ ] Make a second request and confirm the grant balance decreased
- [ ] When the grant is exhausted, the next request fails with 402 (assuming no other credits)

**Expected result:** givers_only + pool off works; fresh users are blocked; grants from other givers can be consumed.

---

## Scenario 3: Live toggle: givers_and_consumers mode + shared pool

**Objective:** Verify admin can flip modes live (no restart) and consumers are immediately unblocked/blocked.

**Setup (initial state):**
- Start in givers_only + pool off (from Scenario 2)
- Have a test user with no PAT (`CONSUMER_USER`)
- Have a giver user with a valid PAT and some balance (`GIVER_USER`)

**Steps:**

### Part 1: Confirm consumer is blocked (givers_only)
- [ ] Log in as `CONSUMER_USER` (no PAT)
- [ ] Attempt a Copilot CLI request with `CONSUMER_USER`'s token
- [ ] Expect: HTTP 402 Payment Required (blocked, no PAT, no pool to draw from)

### Part 2: Admin flips to givers_and_consumers + pool on
- [ ] Open the admin panel
- [ ] Locate the settings for `participants_mode` and `shared_pool_enabled`
- [ ] Toggle `participants_mode` from `givers_only` to `givers_and_consumers`
- [ ] Toggle `shared_pool_enabled` from `off` to `on`
- [ ] Confirm the save (no page reload required if live-update is implemented)
- [ ] Check control-plane logs for any errors (should see a settings update, no crashes)

### Part 3: Consumer is now unblocked (draws from pool)
- [ ] Still logged in as `CONSUMER_USER` (or re-login)
- [ ] Attempt the same Copilot CLI request
- [ ] Expect: success (200 OK); the request is charged to the shared pool
- [ ] Verify in the accounting logs that `source = "pool"` or `bucket_type = "POOL"` was charged
- [ ] Verify the shared pool balance decreased

### Part 4: Admin flips back to givers_only + pool off
- [ ] Return to the admin panel
- [ ] Toggle `participants_mode` back to `givers_only`
- [ ] Toggle `shared_pool_enabled` back to `off`
- [ ] Save (no restart)
- [ ] Check logs for settings update

### Part 5: Consumer is blocked again
- [ ] Still logged in as `CONSUMER_USER`
- [ ] Attempt another Copilot CLI request
- [ ] Expect: HTTP 402 Payment Required (blocked again, no PAT, no pool available)
- [ ] Confirm the request is refused immediately (check request timestamp in logs)

**Expected result:** Admin toggles work live; consumers can be enabled/disabled without restart; pool on/off gates access correctly.

---

## Scenario 4: CLI and proxy unchanged (end-to-end smoke)

**Objective:** Verify the normal `ctc login` + Copilot chat flow still works exactly as before — i.e., Axis 1 (web transport) did not break the proxy data path.

**Setup:**
```bash
CTC_WEB_TRANSPORT=https  (can be http, doesn't matter for proxy)
HTTPS_PROXY=http://localhost:8080
NODE_EXTRA_CA_CERTS=/path/to/cert.pem
GH_HOST=example.ghe.com
(cert is trusted in macOS System keychain per TDD.md §6.1)
```

**Steps:**

### Part 1: ctc login works
- [ ] Run `ctc login` in a clean terminal
- [ ] Expect: login prompt for GitHub Enterprise
- [ ] Log in with a valid GHE account
- [ ] Expect: "Successfully authenticated" or similar success message
- [ ] Confirm a token is stored (check `~/.ctc/config.json` or equivalent)

### Part 2: Copilot chat completion works
- [ ] In the same terminal, run:
  ```bash
  gh copilot explain "for (let i = 0; i < 10; i++) { console.log(i); }"
  ```
- [ ] Expect: Copilot responds with an explanation (streaming output is fine)
- [ ] The request should complete without proxy errors
- [ ] Check proxy logs: see the request was routed through the MITM'd host, token was swapped, and the response was relayed

### Part 3: Repeat Copilot operations
- [ ] Run another chat completion, e.g., `gh copilot explain "SELECT * FROM users;"`
- [ ] Expect: success again, response streams in
- [ ] Verify proxy logs show consistent token swapping and no authentication errors

**Expected result:** `ctc login` and Copilot CLI work unchanged; the proxy data path is unaffected by web-transport changes.

---

## Validation checklist

- [ ] All four scenarios pass with no errors
- [ ] Admin toggles did not require restart (Scenario 3)
- [ ] No sensitive data (PATs, `CTC_SECRET_KEY`) leaked in logs (check all scenarios)
- [ ] Email magic-links are single-use and expire (if applicable; test by re-opening the same link — should fail)
- [ ] Session cookies are appropriately scoped (Scenario 1: not Secure; Scenario 2+: Secure if HTTPS)
- [ ] Proxy logs show correct token swapping in all scenarios
- [ ] No typos or broken links in the web app UI

**Sign-off:** Date _________, Operator _________, Notes: _____________________________
