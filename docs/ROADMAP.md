# CTC Roadmap / Backlog

The running list of future improvements and known gaps. Append freely — keep
items one line each with enough context to pick up cold. Move items between
sections as priorities shift. Stable technical contracts live in
`docs/reference/`; when an item graduates into real work, write its design there
(or in `docs/guide/`) and link to it from here.

## Now (in flight)

_(nothing active)_

## Next (queued)

- **Make the Rotate / Revoke license buttons work.** On the Profile screen
  (`web/src/screens/Profile/ProfileScreen.tsx:297,300`) the Rotate and Revoke
  buttons next to the Copilot license are decoration only — no click handlers and
  no backend endpoint. Build it: **Revoke** deletes the Host's stored encrypted
  PAT (demote back to Guest); **Rotate** replaces it with a freshly validated one
  (re-read quota). (The existing `revoke_proxy_token`/`revoke_session` are for
  proxy tokens and sessions — not the license.)

## Later / ideas

- **Run CTC from inside the Copilot CLI.** Let users drive CTC commands without
  leaving the CLI. Preferred approach: an MCP server (clean, structured) over
  proxy-side text-regex interception.
- **View other users' public profiles.** Let a user open someone else's profile
  by clicking them (e.g. in the leaderboard or marketplace) or searching by name.
  Show a read-only version of what that person sees on their own profile —
  role (Host/Guest), allowance, credits used, chip-ins given/received, etc. —
  **minus the private fields**: the actual Copilot license/token and the private
  pledged-surplus amount (which is explicitly "never shown publicly"). Needs a
  public-profile endpoint that returns only the non-private subset, plus
  click-through / search UI.
- **Return received credits.** When a user has received credits they didn't use
  (marketplace chip-ins / grants from a Host), let them give the unused portion
  back. The returned amount goes back into the available ("not used") balance so
  it can be re-pledged or chipped in again. Open question to settle in design:
  does it return to the original donor(s) — and how is it split across multiple
  donors — or to the common pool?
- **Support the Copilot IDE extension, not just the CLI.** Today CTC only
  routes the Copilot **CLI** through the proxy (via `HTTPS_PROXY`, cert trust,
  `COPILOT_GITHUB_TOKEN`, `GH_HOST` — see `TDD.md` §6.3). Explore doing the same
  for the **VS Code / JetBrains Copilot extension** so users on the IDE can also
  draw on shared credits. Things to investigate:
  - **Traffic routing:** does the extension honor `http.proxy` / `HTTPS_PROXY` /
    system proxy settings, and can we point it at the CTC proxy host? Confirm
    which hosts it talks to vs. the CLI's host set (`MITM_HOSTS`/`SWAP_HOSTS`).
  - **Cert trust:** the extension runs inside the IDE's Node/Electron runtime —
    figure out how it picks up our self-signed MITM cert (extra-CA env,
    `http.proxyStrictSSL`, OS keychain) the way the CLI needs the System keychain.
  - **Auth/token injection:** the extension typically authenticates via the
    GitHub OAuth/device flow tied to the user's GH session, not a
    `COPILOT_GITHUB_TOKEN` env var. Determine whether we can inject the
    disposable fake token (settings override? a signed-in GHE account on the
    enterprise instance?) so the proxy can swap it for the real PAT.
  - **Install/setup UX:** what the equivalent of the CLI one-liner looks like for
    the extension (settings JSON snippet, profile, or a small installer).
  Start with a discovery spike (capture the extension's traffic through the proxy
  like the original CLI endpoint discovery) before committing to a design.
- **Transaction history on the profile.** Show the signed-in user a chronological
  ledger of every CTC credit movement involving them: pledges set/changed,
  chip-ins they gave (grants out), chip-ins/grants they received, draws from the
  common pool, and per-request fundings — each with a timestamp, amount (AIU), and
  counterparty where applicable. Distinct from the existing History screen, which
  shows monthly *cycle reports*; this is a per-user, per-transaction feed.
  The data largely exists in the accounting store (grants, requests, pledge
  changes, pool consumption) — needs a "list my transactions" aggregation +
  endpoint and a feed section on the profile.
- **Operator end-to-end smoke test.** A scripted run exercising the full
  operator path (login → connect license → CLI tunnel through proxy) against the
  real binaries.

## Done (recent, for context)

- Admin panel: all users, masked PAT + audited reveal, runtime default config.
- Giver credit visualization (used / pledged / donated / left) with live
  reconciliation; striped credit bar + legend.
