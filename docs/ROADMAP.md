# CTC Roadmap / Backlog

The running list of future improvements and known gaps. Append freely — keep
items one line each with enough context to pick up cold. Move items between
sections as priorities shift. Stable technical contracts live in
`docs/reference/`; when an item graduates into real work, write its design there
(or in `docs/guide/`) and link to it from here.

## Now (in flight)

_(nothing active)_

## Next (queued)

_(nothing active)_

## Later / ideas

- **Run CTC from inside the Copilot CLI.** Let users drive CTC commands without
  leaving the CLI. Preferred approach: an MCP server (clean, structured) over
  proxy-side text-regex interception. (Partly addressed: the `ctc` launcher now
  bridges Copilot's `/ide` into the isolated HOME so VS Code can be driven from the
  CTC-routed CLI — see `cli/README.md`. This item is about CTC's *own* commands,
  still open.)
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
  (Note: a `/ide` *bridge* now lets the CTC-routed CLI attach to a running VS Code
  via Copilot's own `/ide` command — but the IDE Copilot extension itself is still
  not routed through the proxy, which is what this item is about.)
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

- **GitLab OAuth as the sole login path.** Magic-link and email auth removed
  entirely; identity is the GitLab username, accounts created on first login.
- **Rotate / Revoke license buttons.** Rotate re-validates a fresh PAT (re-reads
  quota); Revoke deletes the stored PAT via `DELETE /api/pat` and demotes back to
  consumer.
- **Public profiles.** Click a user (leaderboard/marketplace) or search by name to
  see a read-only profile — name, GitLab login, role, and (for givers) tier + net
  contribution stats. Private fields stay hidden.
- **Aristocracy tiers.** Givers ranked by net contribution this cycle
  (Aristocrat → Beggar, Newcomer for no activity); shown as badges on the profile
  and leaderboard.
- **Meter `POST /responses`** (OpenAI Responses API) alongside `/chat/completions`
  and `/v1/messages`.
- **Health-aware routing + failover.** Live-quota health gate skips exhausted
  givers; failover-on-402 marks a giver spent and retries another; grant debits
  spill across the consumer's grants. (`LiveQuotaCache`, `ctc/routing/attribution.py`.)
- **Automatic cycle rollover** at month end (archive + open + seed) with frozen
  archived-cycle reports so past labels stop drifting.
- **Configurable deployment modes** (web transport, participants, shared pool) and
  **server-migration scripts** (`scripts/migrate-backup.sh` / `migrate-restore.sh`).
- Admin panel: all users, masked PAT + audited reveal, runtime default config.
- Giver credit visualization (used / pledged / donated / left) with live
  reconciliation; striped credit bar + legend.
