# 07 · Deploying CTC (single VM)

> A practical runbook for shipping CTC to one Linux VM with `docker compose`.
> It runs all three pieces + the shared database, with automatic HTTPS.

---

## Layer 0 — Deployment shapes

CTC ships with defaults that target the "license-holders trade credits" use-case
(email magic-link auth, plain HTTP transport, givers-only pool, shared pool off).
The legacy "all-GHE" configuration (ghe_oauth + HTTPS + givers_and_consumers +
pool on) is still fully supported — just set the right env vars.

### Configuration knobs

| Knob | Default (shipped) | Legacy / alternative |
|---|---|---|
| `CTC_AUTH_MODE` | `email` — magic-link, no GHE account needed | `ghe_oauth` — GitHub Enterprise OAuth |
| `CTC_WEB_TRANSPORT` | `http` — plain HTTP (VPN/LAN only) | `https` — TLS via Caddy |
| `CADDYFILE` | `Caddyfile.http` | `Caddyfile` (HTTPS with TLS) |
| `CTC_PARTICIPANTS_MODE` | `givers_only` — anyone who uploads a PAT is a giver | `givers_and_consumers` |
| `CTC_SHARED_POOL` | `off` | `on` — shared quota pool |

### Deployment shapes at a glance

| Shape | Auth | Transport | Participants | Pool | Key env vars |
|---|---|---|---|---|---|
| **Default (shipped)** | `email` | `http` | `givers_only` | `off` | `CTC_AUTH_MODE=email`, `CTC_WEB_TRANSPORT=http`, `CADDYFILE=Caddyfile.http` |
| **Legacy / public** | `ghe_oauth` | `https` | `givers_and_consumers` | `on` | `CTC_AUTH_MODE=ghe_oauth`, `CTC_WEB_TRANSPORT=https`, `CADDYFILE=Caddyfile`, `GHE_OAUTH_*` set |

> **Upgrading from an earlier version? Read this.**
> Before this release CTC only supported ghe_oauth + HTTPS. The shipped defaults
> have changed: if you deploy a new image without explicitly setting the env vars,
> auth becomes `email` (magic-link), the website becomes plain HTTP, participants
> mode becomes `givers_only`, and the shared pool turns off. Set the env vars
> from the "Legacy / public" row above to preserve the old behavior.

### Selecting the Caddy config (HTTP vs HTTPS)

Two Caddyfile variants are shipped:

- **`Caddyfile`** — HTTPS, terminates TLS using `/certs/cert.pem` + `/certs/key.pem`.
  Use for public deployments. Set `CADDYFILE=Caddyfile` (or leave it unset — the
  docker-compose default is the HTTPS variant).
- **`Caddyfile.http`** — plain HTTP with `auto_https off`. Use when CTC sits behind
  a VPN or trusted LAN and TLS is terminated elsewhere (or not at all).
  Set `CADDYFILE=Caddyfile.http`.

`docker-compose.yml` mounts `./${CADDYFILE:-Caddyfile}` into the Caddy container,
so setting `CADDYFILE` in `.env` is all you need.

> **Security warning — plain HTTP:** when `CTC_WEB_TRANSPORT=http` / `CADDYFILE=Caddyfile.http`,
> session cookies and magic-link tokens travel in plaintext. Only use this behind a
> VPN or on a trusted private network. Never expose HTTP-mode CTC to the public internet.

---

## Layer 1 — The shape of a deployment

One VM runs three containers that share one database:

```mermaid
flowchart TB
    subgraph VM["one Linux VM"]
        Caddy["Caddy :443<br/>HTTPS · web app · /ctc-ca.pem · /install.sh<br/>proxies /api + /auth"]
        CP["control-plane :8090<br/>(internal)"]
        PX["proxy :8080<br/>(VPN/internal only)"]
        DB[("shared volume:<br/>ctc.db + cert")]
        Caddy --> CP
        CP --- DB
        PX --- DB
    end
    Browser["browsers"] --> Caddy
    VPN["teammates on VPN<br/>(ctc launcher)"] --> PX
    PX --> GHE["GitHub Enterprise"]
    CP --> GHE
```

- **Caddy** is the only thing on the public internet (ports 80/443). It serves the
  web app, hands out the CA cert + installer, and forwards API/auth calls inward.
- The **control-plane** is internal — only Caddy talks to it.
- The **proxy** is **VPN/internal only** — never public (see the security note).
- All three share one **SQLite database** on a Docker volume. (This is why it's a
  single VM: SQLite can't be shared across machines.)

---

## Quick deploy (copy-paste)

The whole sequence, front to back:

```bash
# 1. Configure
cp .env.example .env
# edit .env: CTC_DOMAIN, CTC_SECRET_KEY (openssl rand -hex 32), GHE_DOMAIN,
#            PROXY_BIND, CTC_ADMINS, and GHE_OAUTH_* (only if CTC_AUTH_MODE=ghe_oauth)

# 2. Validate config (fails loudly on missing/inconsistent vars)
sh scripts/preflight.sh

# 3. Build + start everything (gencert runs first; proxy/caddy wait for health)
docker compose up -d --build

# 4. Verify all services are healthy
docker compose ps

# 5. Tail logs if anything is unhealthy
docker compose logs -f proxy controlplane caddy
```

Operating it afterwards:

```bash
docker compose logs -f proxy                 # follow one service
git pull && docker compose up -d --build     # update to a new version
docker compose down                          # stop (the ctcdata/ctccerts volumes persist)
```

The sections below explain each step in detail.

---

## Layer 2 — One-time setup

You need, before you start:

1. **A VM** with Docker + the Docker Compose plugin, reachable by your team on
   ports **80/443** (web) and **8080** (proxy). A public domain is **optional** —
   a raw internal IP works too (see "Internal server with no domain" below).
2. **A GHE OAuth app** registered on your GitHub Enterprise, with the callback URL
   `https://<CTC_DOMAIN>/auth/callback` (where `<CTC_DOMAIN>` is your hostname *or*
   IP, e.g. `https://10.0.0.5/auth/callback`).
3. **A VPN / private network** your teammates are on (the proxy binds to it).

Then:

1. Copy `.env.example` to `.env` and fill it in.
   Set `CTC_DOMAIN`, `CTC_SECRET_KEY` (`openssl rand -hex 32`),
   `GHE_DOMAIN` (your real GitHub Enterprise domain, e.g. `example.ghe.com`),
   the `GHE_OAUTH_*` values (if using `ghe_oauth` mode), and `PROXY_BIND`
   (your VM's VPN-facing IP).

2. Run the preflight check: `sh scripts/preflight.sh` — it validates required
   variables and web-transport consistency and fails loudly if something's off.

3. Start everything: `docker compose up -d --build`. The `gencert` step runs
   automatically first and writes the MITM cert into the shared volume; the
   proxy and Caddy wait for it and for the control plane to report healthy.

4. Check health: `docker compose ps` — every service should show `healthy`.
   If one is `unhealthy`, `docker compose logs <service>` shows why.

Caddy fetches a Let's Encrypt cert automatically, and the database is
created/migrated on first start.

### What each `.env` value is for

| Variable | Meaning |
|---|---|
| `CTC_DOMAIN` | **The one host knob** — a hostname *or* a raw IP. Sets the web/API origin and is the source the CLI install command, the proxy host, and the launcher's default all derive from. `localhost` for a local test. |
| `CTC_SECRET_KEY` | One secret, shared by proxy + control-plane. Encrypts stored PATs, signs cookies. **Never change it** once set (it would orphan stored PATs). |
| `CTC_AUTH_MODE` | `email` (default) — magic-link login, no GHE account required. `ghe_oauth` — GitHub Enterprise OAuth login. |
| `CTC_WEB_TRANSPORT` | `http` (default) — plain HTTP, VPN/LAN only. `https` — TLS via Caddy. Must match `CTC_APP_ORIGIN` scheme. |
| `CADDYFILE` | Caddyfile to mount. Default (unset) = `Caddyfile` (HTTPS). Set `Caddyfile.http` for plain HTTP. |
| `CTC_PARTICIPANTS_MODE` | `givers_only` (default) or `givers_and_consumers`. Seeds the admin-panel default on first boot. |
| `CTC_SHARED_POOL` | `off` (default) or `on`. Seeds the admin-panel default on first boot. |
| `CTC_EMAIL_BACKEND` | `console` (default, logs link to stdout) or `smtp` (sends real email). |
| `CTC_SMTP_HOST` / `_PORT` / `_USER` / `_PASS` / `_FROM` / `_STARTTLS` | SMTP credentials (only used when `CTC_EMAIL_BACKEND=smtp`). |
| `GHE_DOMAIN` | Your GitHub Enterprise domain (e.g. `example.ghe.com`). The proxy derives the hosts it decrypts + the cert SANs from this; the CLI launcher uses it for `GH_HOST`. The code default is the neutral placeholder `example.ghe.com` — override it here. |
| `GHE_OAUTH_CLIENT_ID` / `_SECRET` | GHE OAuth app credentials. **Only required when `CTC_AUTH_MODE=ghe_oauth`.** |
| `GHE_OAUTH_BASE` | GHE **web** host (login). Only used in `ghe_oauth` mode. |
| `GHE_API_BASE` | GHE **API** host (Copilot quota / PAT validation). **Required in both auth modes** — PAT validation always hits the API host. Note: no longer defaults to `GHE_OAUTH_BASE`; must be set explicitly. |
| `REAL_GHE_HOST` | API host the proxy forwards Copilot traffic to. |
| `PROXY_BIND` | The VM's **VPN-facing IP** for port 8080. Keep proxy off the public internet. |
| `CTC_ADMINS` | Comma-separated identities that get the admin panel (all users, PAT reveal, runtime defaults). Case-insensitive. Lock down like a secret — an admin can reveal any giver's PAT. Empty = no admin. **In email mode: email addresses. In ghe_oauth mode: GHE login names.** |

---

## Layer 2 — Internal server with no domain (raw IP)

Deploying to an internal box your team reaches by IP? You don't need a domain.
Everything keys off `CTC_DOMAIN`, so just set it to the IP:

```bash
CTC_DOMAIN=10.0.0.5          # your server's internal IP (web + proxy live here)
GHE_DOMAIN=example.ghe.com
PROXY_BIND=10.0.0.5          # bind the proxy to the same internal interface
# …plus CTC_SECRET_KEY, GHE_OAUTH_* as usual
```

Then `sh scripts/preflight.sh && docker compose up -d --build` as normal. With an IP, **Caddy can't get a Let's Encrypt cert** (those are
domain-only), so it serves HTTPS using its **own internal CA**. That's fine — it's
real HTTPS — but nothing trusts that CA yet, which means two one-time trust steps:

1. **OAuth callback:** register `https://10.0.0.5/auth/callback` in your GHE OAuth
   app (your GHE admin must allow a non-public callback host).
2. **Trust Caddy's CA on each machine.** Until it's trusted, the browser warns on
   `https://10.0.0.5`, and the `curl -fsSL https://10.0.0.5/install.sh …`
   one-liner fails cert verification. Distribute Caddy's root CA to the team and
   have them add it to their system trust store. Grab it from the running
   container:

   ```bash
   docker compose exec caddy \
     cat /data/caddy/pki/authorities/local/root.crt > ctc-internal-ca.crt
   ```

   (Quick, less-clean alternative: teammates click through the browser warning and
   add `-k` to the install `curl`. Trusting the CA once is cleaner.)

Note this is a *separate* cert from the proxy's MITM cert that `ctc login` trusts:
Caddy's CA secures the **website**; the proxy cert secures the **Copilot traffic**.
On a raw-IP deploy teammates end up trusting both (the proxy one is automatic
inside `ctc login`).

Prefer not to deal with the CA at all? Ask whoever runs your **internal DNS** for a
name (e.g. `ctc.corp.company.com`) pointing at the VM and use that as `CTC_DOMAIN`
— same deploy, nicer URL, and HTTPS still via Caddy's internal CA (or a real cert
if the name is a public subdomain).

---

## Layer 2 — Before you go live (checklist)

Don't invite the team until all of these pass. The first four are setup; the last
one is the real proof — the tests cover the parts, not the live wiring.

- [ ] **GHE OAuth app registered** with the exact callback `https://<CTC_DOMAIN>/auth/callback`,
      and `GHE_OAUTH_CLIENT_ID` / `_SECRET` set in `.env`. (A mismatched callback is
      the #1 cause of a broken login.)
- [ ] **`CTC_SECRET_KEY` generated** (`openssl rand -hex 32`) and stored safely.
      **Never change it** once givers have uploaded PATs — it would orphan them.
      Also set **`CTC_ADMINS`** to the operator GHE login(s) — an admin can reveal
      any giver's PAT in cleartext, so treat it like a secret and keep the list short.
- [ ] **Proxy locked down** — `PROXY_BIND` on the VPN/internal interface and port
      **8080 firewalled** from the public internet. It blind-tunnels unknown hosts,
      so a public proxy is an open relay.
- [ ] **Cert trust sorted** — real domain: nothing to do (Let's Encrypt). Raw IP /
      internal name: distribute Caddy's internal CA to the team (see the raw-IP
      section above) so the browser and the install `curl` trust the site.
- [ ] **One real end-to-end run passes** (the smoke test below).

### The smoke test — prove the live flow once

Run this yourself with **two** GHE accounts (or one giver + one teammate) before
handing it out. It exercises the whole chain the unit tests can't.

**As a giver:**
1. Open `https://<CTC_DOMAIN>`, log in with GitHub Enterprise → you land in the
   first-run walkthrough.
2. Choose **giver**, paste a real Copilot PAT → it should verify (`✓ belongs to
   @you · N AIU`) and read your quota. Set a pledge. Copy the install one-liner.
3. Run the one-liner, then `ctc -p "say hello"`. Confirm you get a **real Copilot
   reply** (not an auth/cert error).
4. Back on the dashboard, confirm your **usage went up** and credit was **debited**
   (the cost is read from Copilot's response, in nano-AIU).

**As a consumer (second account):**
5. Log in, choose **consumer**, finish onboarding (you get the free allowance).
   Install + `ctc -p "…"`.
6. Confirm the request **routes through a giver's PAT** (charged to the giver, not
   you) and the **leaderboard / dashboard update** to reflect it.

If steps 3–4 and 6 pass, the live wiring is good. If `ctc` errors on TLS, the cert
isn't trusted (see cert trust above); if login bounces, re-check the OAuth callback.

---

## Layer 2 — How teammates connect afterwards

Once it's up, a teammate:

1. opens `https://<your-domain>`, logs in with GitHub, and is walked through a
   short **first-run setup** (or later, the Settings → "Set up CLI" panel) that
   hands them a ready-to-run install one-liner with their token baked in;
2. runs that one-liner —
   `curl -fsSL https://<your-domain>/install.sh | sh -s -- --token <their-token>` —
   which installs `ctc` **and** logs in (downloads + trusts the cert) in one step,
   then runs `ctc` to use Copilot.

See [02 · The `ctc` command](02-the-cli-launcher.md) for that side.

---

## Layer 3 — Operating it

- **Logs:** `docker compose logs -f proxy` / `controlplane` / `caddy`.
- **Update to a new version:** `git pull && docker compose up -d --build`.
  (Also redeploy to the **canary** box if it runs separately — see
  [06 · Drift detection](06-drift-detection.md).)
- **Backups:** the only state is the `ctcdata` volume (the SQLite DB). Snapshot it
  regularly — it holds users, encrypted PATs, and all credit history.
- **The cert:** `cert.pem`/`key.pem` live in the `ctccerts` volume. Don't
  regenerate casually — every client trusts it via `ctc login`, so a new cert
  means everyone must re-run `ctc login`.

### ⚠️ Security notes (read these)

- **The proxy must never be public.** It's an HTTP `CONNECT` proxy; for hosts it
  doesn't inspect it blind-tunnels, which on the open internet is an **open
  relay**. Keep `PROXY_BIND` on a VPN/internal interface and firewall port 8080.
- **`CTC_SECRET_KEY` and `.env` are secrets.** `.env` is gitignored; keep it off
  git and out of images. Treat the `ctcdata` volume as sensitive (it contains
  encrypted PATs — encrypted, but still).
- **HTTPS is required for login.** Session cookies are `Secure` and the OAuth
  redirect is `https`, so the control-plane must be reached over HTTPS (Caddy
  handles this for a real domain).

---

## Layer 3 — Running across multiple servers? Not yet.

This kit is deliberately single-VM because the proxy and control-plane share one
**SQLite** file. To scale horizontally you'd move the accounting/auth store to a
networked database (e.g. Postgres) and run the services on separate hosts — a
real change to `ctc/store/`, out of scope here. For a team-sized internal tool,
one well-sized VM is plenty.

---

That's the whole picture, front to back. Back to the [Guide index](00-overview.md).
