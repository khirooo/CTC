# Glossary

Every CTC term in one line. No prior knowledge assumed. (Skim it, or come back
when a word trips you up.)

### People & roles

- **Giver** — a teammate who *has* paid GitHub Copilot and shares their spare
  capacity with others.
- **Consumer** — a teammate who *doesn't* have paid Copilot and borrows from the
  shared pool.
- **Operator** — the person who runs the CTC servers (the proxy + the website).
- **Tier (aristocracy tier)** — a playful rank shown next to a **giver**, derived
  from their net contribution this cycle (donated minus consumed): **Aristocrat**,
  **Baron**, **Bourgeois**, **Commoner**, **Peasant**, **Beggar**, or **Newcomer**
  (no activity yet). Consumers don't get a tier.
- **Public profile** — a read-only page for any user (reached by clicking their
  name in the leaderboard/marketplace or via search) showing their name, GitLab
  username, role, and — for givers — their tier and headline contribution stats.
  Private details (the Copilot token, exact pledge) are never shown.

### The pieces

- **Copilot CLI** — GitHub's official command-line Copilot tool. CTC never
  modifies it; it just reroutes its traffic.
- **Proxy** — the "middleman" program that sits between Copilot and GitHub,
  swaps tokens, and records cost. (See [01](01-the-proxy.md).)
- **Control plane** — the server + website where you log in, hand in your token,
  and view dashboards. (See [03](03-identity-and-login.md), [05](05-the-web-app.md).)
- **`ctc`** — the one-line command teammates run to launch Copilot through CTC
  without manual setup. (See [02](02-the-cli-launcher.md).)
- **Canary / sentinel** — the early-warning system that detects if a Copilot
  update silently breaks CTC's cost tracking. (See [06](06-drift-detection.md).)

### Tokens & security

- **PAT (Personal Access Token)** — a long secret string that acts like a
  password for a service. A giver's real Copilot PAT is the valuable thing CTC
  protects; it's stored **encrypted** and never leaves the server.
- **Proxy token** — a *throwaway, PAT-shaped* code CTC gives each user. It's what
  you put into Copilot. It identifies you to CTC but is useless to GitHub on its
  own. Revocable anytime.
- **Session cookie** — the small signed token your browser holds after you log in
  to the website, so the server knows it's still you.
- **MITM (Man-In-The-Middle)** — intercepting and reading network traffic that's
  normally private. CTC does this *to its own traffic, on purpose*, to do the
  token swap. Your computer allows it because you install CTC's **certificate**.
- **Certificate (cert)** — a file that tells your computer "trust this server."
  CTC uses one so it can stand in the middle of the encrypted connection.

### Money & measurement

- **AIU (AI Unit)** — the unit GitHub uses to price Copilot usage. CTC counts
  usage in AIU. A small request costs a tiny fraction of an AIU.
- **nano-AIU** — one-billionth of an AIU. CTC stores everything internally in
  these whole numbers (so there are no rounding errors), and only converts to
  friendly "X.XX AIU" when showing it to you. **1 credit = 1 nano-AIU.**
- **Quota** — how much total Copilot capacity a giver has this cycle (read from
  GitHub when they hand in their PAT).
- **Pledge** — the slice of their quota a giver volunteers into the shared pool.
- **Pool** — the combined pledges of all givers. Its balance is shown on the
  marketplace; credit leaves it only when someone fills a request from it.
- **Grant** — a unit of funding on a request, served by one giver's token. Two
  kinds: a **chip-in** (a giver funds someone else's request from their retained
  credit) and a **pool fill** (the requester tops up their *own* request from the
  pool). Only the request owner can pool-fill their request.
- **Cycle** — a billing period (one calendar month). Balances reset each cycle.
  CTC **rolls over automatically** at month end: the ended cycle is archived, a new
  one opens, and each giver's pledge carries forward. Archived cycle reports are
  **frozen** the first time they're viewed, so past winners/labels never drift.

### Concepts you'll see in the proxy docs

- **CONNECT** — the first thing a browser/CLI sends to a proxy to say "open a
  tunnel to host X." CTC decides per-tunnel whether to inspect it or pass it
  through untouched.
- **Billable request** — a Copilot call that actually costs money (a `POST` to
  `/chat/completions`, `/v1/messages`, or `/responses`). Only these are metered.
- **Health gate / failover** — before charging a giver, the proxy checks a
  short-lived snapshot of that giver's live GitHub quota and skips any whose quota
  is exhausted. If GitHub still rejects the chosen giver with a `402`, the proxy
  marks them spent and retries with another eligible giver instead of failing your
  request.
- **Metering field** — the exact spot in GitHub's response that states the cost:
  `copilot_usage.total_nano_aiu`. CTC reads this for every billable request.
- **Bearer** — the required format for the authorization header (`Bearer <token>`).
  Copilot's API rejects other formats.
