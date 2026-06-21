# Low-friction CLI Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce CLI onboarding to one browser click + one paste + one password by making the bootstrap fetches tolerate the self-signed cert (`-k`), serving one cert for both proxy and dashboard, and showing an advisory CA fingerprint.

**Architecture:** The CTC host is internal-only (self-signed Caddy cert, no public DNS, no MDM). We (1) add the dashboard domain to the proxy cert's SANs and point Caddy at that cert, so trusting it once via `ctc login` also covers the dashboard; (2) switch the three bootstrap fetches (`install.sh` one-liner, `install.sh`→`/ctc`, `ctc login`→`/ctc-ca.pem`) to `curl -fsSLk`; (3) print the CA SHA-256 in `ctc login` and surface the same fingerprint from the control plane to the dashboard as a defense-in-depth check.

**Tech Stack:** POSIX `sh`/`bash` (CLI + tests), Caddy (Caddyfile), Python 3.12 + aiohttp (control plane), React + TypeScript + Vitest (web), Docker Compose, OpenSSL.

## Global Constraints

- **macOS-only client** — the `ctc` CLI already guards with `_require_macos`; do not add other-OS paths.
- **Trust-on-first-use is accepted** — the fingerprint is advisory (printed + displayed), never enforced. Do not add blocking verification.
- **Single self-signed cert, no CA hierarchy** — keep `CN=copilot-proxy-ca`; do not introduce a root CA.
- **Fingerprint format is canonical** — uppercase hex, colon-separated, SHA-256 over the cert's DER bytes, i.e. exactly what `openssl x509 -noout -fingerprint -sha256` prints after the `=`. Both the CLI and the control plane MUST produce this identical string.
- **`REAL_PAT` is never logged/sent to clients** (existing rule, unaffected here).
- **Cert regeneration requires deleting the old certs first** — `scripts/gen-cert.sh` refuses to overwrite existing `cert.pem`/`key.pem`; any SAN change is a no-op until the old pair is removed.
- **Frequent commits** — one commit per task.

---

### Task 1: Add the dashboard domain to the proxy cert SANs

**Files:**
- Modify: `scripts/gen-cert.sh:15-30`
- Test: `scripts/tests/test_gen_cert.sh` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: a `cert.pem` whose SANs include `DNS:${CTC_DOMAIN}` in addition to the existing MITM hosts. `CTC_DOMAIN` env var (default `localhost`).

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_gen_cert.sh`:

```sh
#!/usr/bin/env sh
# Real-openssl test: gen-cert.sh must embed CTC_DOMAIN in the cert SANs.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
GENCERT="$HERE/../gen-cert.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

CTC_DOMAIN=ctc.example.test GHE_DOMAIN=corp.ghe.com sh "$GENCERT" "$TMP" >/dev/null

sans="$(openssl x509 -in "$TMP/cert.pem" -noout -text | grep -A1 'Subject Alternative Name')"
fail=0
case "$sans" in *"DNS:ctc.example.test"*) echo "  ok: CTC_DOMAIN in SANs";; *) echo "  FAIL: CTC_DOMAIN missing from SANs"; fail=1;; esac
case "$sans" in *"DNS:api.corp.ghe.com"*) echo "  ok: GHE MITM host still present";; *) echo "  FAIL: GHE SAN regressed"; fail=1;; esac
exit "$fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sh scripts/tests/test_gen_cert.sh`
Expected: FAIL with "CTC_DOMAIN missing from SANs" (current script has no `${CTC_DOMAIN}` SAN).

- [ ] **Step 3: Add the SAN**

In `scripts/gen-cert.sh`, after the `GHE_DOMAIN` block (line 17), add:

```sh
# The dashboard host. The same cert fronts the website via Caddy, so trusting it
# once (ctc login) also clears the browser warning. Defaults to localhost.
CTC_DOMAIN="${CTC_DOMAIN:-localhost}"
```

Then change the `-addext` SAN line (line 30) to include `DNS:${CTC_DOMAIN}`:

```sh
  -addext "subjectAltName=DNS:localhost,DNS:${CTC_DOMAIN},DNS:api.${GHE_DOMAIN},DNS:${GHE_DOMAIN},DNS:copilot-api.${GHE_DOMAIN},DNS:api.github.com,DNS:github.com,DNS:api.githubcopilot.com,DNS:githubcopilot.com,DNS:api.localhost,IP:127.0.0.1"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sh scripts/tests/test_gen_cert.sh`
Expected: both `ok:` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/gen-cert.sh scripts/tests/test_gen_cert.sh
git commit -m "feat(cert): add CTC_DOMAIN to proxy cert SANs for shared dashboard cert"
```

---

### Task 2: Serve the proxy cert as Caddy's TLS cert

**Files:**
- Modify: `Caddyfile:6-7`
- Modify: `docker-compose.yml` (caddy service already mounts `ctccerts:/certs:ro` — verify; add `CTC_DOMAIN` is already passed)

**Interfaces:**
- Consumes: `cert.pem`/`key.pem` from Task 1 in the `/certs` volume.
- Produces: Caddy serving the shared cert on `{$CTC_DOMAIN}`, so the browser and `curl` see the same cert `ctc login` trusts.

- [ ] **Step 1: Add the explicit `tls` directive**

In `Caddyfile`, inside the `{$CTC_DOMAIN} {` block, immediately after `encode gzip` (line 7), add:

```caddy
	# Use the shared self-signed proxy cert (not Caddy's internal CA) so the cert
	# `ctc login` trusts also fronts the dashboard — no separate trust, no warning
	# after install. /certs is the same volume the proxy and gencert write.
	tls /certs/cert.pem /certs/key.pem
```

- [ ] **Step 2: Validate the Caddyfile parses**

Run (the caddy image is built from `web/Dockerfile`; validate with the adapter):

```bash
docker run --rm -e CTC_DOMAIN=localhost -v "$PWD/Caddyfile":/etc/caddy/Caddyfile:ro caddy:2 \
  caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration` (it does not require the cert files to exist at validate time for syntax; if it warns about missing files that is acceptable — syntax must be valid).

- [ ] **Step 3: Stack-level verification**

```bash
docker compose --profile tools run --rm gencert   # regenerates only if certs absent
docker compose up -d --build caddy controlplane
# From the host, against the self-signed cert:
curl -fsSLk https://localhost/ctc-ca.pem -o /tmp/ca.pem && echo "ca fetch ok"
openssl s_client -connect localhost:443 -servername localhost </dev/null 2>/dev/null \
  | openssl x509 -noout -subject | grep -q copilot-proxy-ca && echo "caddy serves shared cert"
```

Expected: `ca fetch ok` and `caddy serves shared cert`.

- [ ] **Step 4: Commit**

```bash
git add Caddyfile
git commit -m "feat(caddy): serve shared proxy cert as dashboard TLS"
```

---

### Task 3: `install.sh` fetches the `ctc` binary with `-k`

**Files:**
- Modify: `cli/install.sh:27`
- Modify: `cli/install.sh:2` (usage comment)
- Test: `cli/tests/test_install.sh` (add a case)

**Interfaces:**
- Consumes: nothing.
- Produces: the installer survives the self-signed Caddy cert on the `/ctc` download.

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_install.sh`:

```sh
test_install_uses_insecure_flag_for_http_source() {
  setup_sandbox
  export SHELL=/bin/zsh
  # Stub curl to log args and produce a fake binary at the -o target.
  make_stub curl 'prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then printf "#!/bin/sh\n" > "$a"; fi; prev="$a"; done'
  CTC_SRC="https://ctc.local/ctc" sh "$(dirname "$CTC_BIN")/install.sh" </dev/null >/dev/null 2>&1 || true
  assert_contains "$(cat "$SANDBOX/curl.log")" "-k" "install.sh fetches /ctc with -k"
  teardown_sandbox
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash cli/tests/run.sh 2>&1 | grep -A1 insecure_flag`
Expected: FAIL — current line 27 is `curl -fsSL` (no `-k`).

- [ ] **Step 3: Add `-k`**

In `cli/install.sh`, change line 27:

```sh
  http*://*) curl -fsSLk "$CTC_SRC" -o "$BIN_DIR/ctc";;
```

And update the usage comment on line 2:

```sh
# CTC launcher installer. Usage: curl -fsSLk https://<ctc-host>/install.sh | sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bash cli/tests/run.sh`
Expected: all tests pass, including `install.sh fetches /ctc with -k`. The existing `file://`/cp test is unaffected (it uses the `cp` branch).

- [ ] **Step 5: Commit**

```bash
git add cli/install.sh cli/tests/test_install.sh
git commit -m "feat(cli): install.sh fetches ctc binary with -k (self-signed bootstrap)"
```

---

### Task 4: `ctc login` fetches CA with `-k` and prints its fingerprint

**Files:**
- Modify: `cli/ctc:54-57` (the `/ctc-ca.pem` fetch)
- Modify: `cli/ctc:58-60` (print fingerprint before the sudo)
- Test: `cli/tests/test_login.sh` (extend `_stub_login_env` + assertions)

**Interfaces:**
- Consumes: nothing.
- Produces: `ctc login` survives the self-signed cert and prints `CA fingerprint (SHA-256): <FP>` on stderr before the `sudo`.

- [ ] **Step 1: Extend the test**

In `cli/tests/test_login.sh`, replace `_stub_login_env` (lines 1-5) with:

```sh
_stub_login_env() {
  make_stub security ':'                       # trust succeeds, no-op
  make_stub sudo 'exec "$@"'                    # run the wrapped command directly
  make_stub curl 'prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then printf "FAKECERT" > "$a"; fi; prev="$a"; done'
  make_stub openssl 'echo "sha256 Fingerprint=AA:BB:CC:DD"'   # deterministic fingerprint
}
```

Then add assertions inside `test_login_writes_env_and_cert` (after line 13, the cert-downloaded assertion):

```sh
  assert_contains "$(cat "$SANDBOX/curl.log")" "-k" "CA fetched with -k"
```

And add a new test:

```sh
test_login_prints_ca_fingerprint() {
  setup_sandbox; _stub_login_env
  out="$(printf 'github_pat_TESTTOKEN1234\n' | "$CTC_BIN" login 2>&1)"; code=$?
  assert_exit "$code" 0 "login exits 0"
  assert_contains "$out" "AA:BB:CC:DD" "fingerprint printed"
  assert_contains "$out" "dashboard" "verify-against-dashboard hint printed"
  teardown_sandbox
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bash cli/tests/run.sh 2>&1 | grep -E "fingerprint|-k"`
Expected: FAIL on the `-k` assertion and the new fingerprint test.

- [ ] **Step 3: Add `-k` and the fingerprint print**

In `cli/ctc`, change the download (lines 54-57):

```sh
  echo "Downloading CA cert from https://$CTC_HOST/ctc-ca.pem ..." >&2
  if ! curl -fsSLk "https://$CTC_HOST/ctc-ca.pem" -o "$cert"; then
    echo "ctc: failed to download CA cert from https://$CTC_HOST/ctc-ca.pem" >&2; exit 1
  fi
```

Then, immediately before the trust block (currently line 59), insert:

```sh
  fp="$(openssl x509 -in "$cert" -noout -fingerprint -sha256 2>/dev/null | sed 's/^.*=//')"
  if [ -n "${fp:-}" ]; then
    echo "CA fingerprint (SHA-256): $fp" >&2
    echo "Verify this matches the fingerprint on the dashboard before trusting." >&2
  fi
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bash cli/tests/run.sh`
Expected: all pass, including `CA fetched with -k`, `fingerprint printed`, `verify-against-dashboard hint printed`.

- [ ] **Step 5: Commit**

```bash
git add cli/ctc cli/tests/test_login.sh
git commit -m "feat(cli): ctc login fetches CA with -k and prints SHA-256 fingerprint"
```

---

### Task 5: Control plane computes + exposes the CA fingerprint

**Files:**
- Create: `ctc/auth/ca_fingerprint.py`
- Test: `tests/test_ca_fingerprint.py` (create)
- Modify: `api_server.py` (`api_token_create`, ~line 160-165; `build_from_env` to read `CTC_CA_CERT`)
- Modify: `docker-compose.yml` (mount `ctccerts:/certs:ro` on `controlplane`, add `CTC_CA_CERT`)

**Interfaces:**
- Consumes: the cert PEM at `CTC_CA_CERT` (default `/certs/cert.pem`).
- Produces:
  - `ca_fingerprint_sha256(pem_path: str) -> str | None` — canonical colon-hex SHA-256, or `None` if the file is absent/unparseable.
  - `POST /api/proxy-token` response gains `"ca_fingerprint": <str|null>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ca_fingerprint.py`:

```python
import subprocess
from ctc.auth.ca_fingerprint import ca_fingerprint_sha256


def _make_cert(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key), "-out", str(cert), "-days", "1", "-nodes",
        "-subj", "/CN=copilot-proxy-ca",
    ], check=True, capture_output=True)
    return cert


def test_matches_openssl(tmp_path):
    cert = _make_cert(tmp_path)
    expected = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
        check=True, capture_output=True, text=True,
    ).stdout.split("=", 1)[1].strip()
    assert ca_fingerprint_sha256(str(cert)) == expected


def test_missing_file_returns_none(tmp_path):
    assert ca_fingerprint_sha256(str(tmp_path / "nope.pem")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ca_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: ctc.auth.ca_fingerprint`.

- [ ] **Step 3: Implement the module**

Create `ctc/auth/ca_fingerprint.py`:

```python
"""SHA-256 fingerprint of a PEM certificate, formatted to match
`openssl x509 -noout -fingerprint -sha256` (uppercase colon-separated hex over
the DER bytes). Dependency-free: parses the first CERTIFICATE block by hand."""
from __future__ import annotations

import base64
import hashlib
import re

_CERT_RE = re.compile(
    rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.DOTALL
)


def ca_fingerprint_sha256(pem_path: str) -> str | None:
    try:
        with open(pem_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    m = _CERT_RE.search(data)
    if not m:
        return None
    try:
        der = base64.b64decode(b"".join(m.group(1).split()))
    except Exception:
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ca_fingerprint.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Wire the fingerprint into the token response**

In `api_server.py`, in `build_from_env`, read the cert path once (near the other `os.environ` reads, before `make_app`):

```python
    ca_cert_path = os.environ.get("CTC_CA_CERT", "/certs/cert.pem")
```

Pass it into `make_app` — add a `ca_cert_path` parameter to `make_app`'s signature and the `make_app(...)` call. Inside `make_app`, compute the fingerprint once at build time:

```python
    from ctc.auth.ca_fingerprint import ca_fingerprint_sha256
    _ca_fingerprint = ca_fingerprint_sha256(ca_cert_path)
```

Then extend `api_token_create` (lines 160-165):

```python
    async def api_token_create(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        tid, token, fp = registry.issue_proxy_token(user["id"], now())
        return web.json_response({"id": tid, "token": token, "fingerprint": fp,
                                  "ca_fingerprint": _ca_fingerprint})
```

- [ ] **Step 6: Mount the cert volume on the control plane**

In `docker-compose.yml`, under the `controlplane` service, add the cert mount and env:

```yaml
    environment:
      # ... existing vars ...
      CTC_CA_CERT: /certs/cert.pem
    volumes:
      - ctcdata:/data
      - ctccerts:/certs:ro
```

- [ ] **Step 7: Run the control-plane test suite**

Run: `pytest tests/test_ca_fingerprint.py -v && python -c "import api_server"`
Expected: tests pass; `api_server` imports without error.

- [ ] **Step 8: Commit**

```bash
git add ctc/auth/ca_fingerprint.py tests/test_ca_fingerprint.py api_server.py docker-compose.yml
git commit -m "feat(control-plane): expose CA SHA-256 fingerprint on /api/proxy-token"
```

---

### Task 6: Web API layer — `-k` one-liner + `caFingerprint`

**Files:**
- Modify: `web/src/api/CtcApi.ts:56` (interface)
- Modify: `web/src/api/HttpCtcApi.ts:113-121`
- Modify: `web/src/api/mockApi.ts:530-...` (getCliCredentials)
- Modify: `web/src/api/__tests__/cliCredentials.test.ts`

**Interfaces:**
- Consumes: `POST /api/proxy-token` returning `{ token, fingerprint, ca_fingerprint }` (Task 5).
- Produces: `getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }>` with `installCommand` using `curl -fsSLk`.

- [ ] **Step 1: Update the existing test (failing)**

In `web/src/api/__tests__/cliCredentials.test.ts`, extend the well-formed test (after line 19) and the embed test:

```ts
    expect(a.installCommand).toContain('install.sh');
    expect(a.installCommand).toContain('-fsSLk');        // bootstrap tolerates self-signed cert
    expect(a).toHaveProperty('caFingerprint');
```

And in the embed test (line 27 area) leave the `--token` assertion, adding:

```ts
    expect(c.installCommand).toContain('curl -fsSLk');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/api/__tests__/cliCredentials.test.ts`
Expected: FAIL — mock `installCommand` uses `-fsSL` (no `k`) and has no `caFingerprint`.

- [ ] **Step 3: Update the interface**

In `web/src/api/CtcApi.ts`, change line 56:

```ts
  getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }>;
```

- [ ] **Step 4: Update HttpCtcApi**

In `web/src/api/HttpCtcApi.ts`, replace `getCliCredentials` (lines 113-121):

```ts
  async getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }> {
    const minted = await apiFetch(this.base, '', '/proxy-token', { method: 'POST' });
    const ctcHost = (import.meta.env.VITE_CTC_HOST as string | undefined) ?? 'localhost';
    return {
      token: minted.token,
      proxyHost: (import.meta.env.VITE_PROXY_HOST as string | undefined) ?? 'localhost:8080',
      installCommand: `curl -fsSLk https://${ctcHost}/install.sh | sh -s -- --token ${minted.token}`,
      caFingerprint: minted.ca_fingerprint ?? null,
    };
  }
```

- [ ] **Step 5: Update mockApi**

In `web/src/api/mockApi.ts`, in `getCliCredentials` (around line 530), change the returned `installCommand` to `-fsSLk` and add a deterministic fake fingerprint:

```ts
        installCommand: `curl -fsSLk https://ctc.local/install.sh | sh -s -- --token github_pat_${body}`,
        caFingerprint: 'AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99',
```

(keep the surrounding `delay({ ... })` wrapper and `token`/`proxyHost` fields intact.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run src/api/__tests__/cliCredentials.test.ts`
Expected: PASS.

- [ ] **Step 7: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors (both CtcApi implementers now satisfy the extended interface).

- [ ] **Step 8: Commit**

```bash
git add web/src/api/CtcApi.ts web/src/api/HttpCtcApi.ts web/src/api/mockApi.ts web/src/api/__tests__/cliCredentials.test.ts
git commit -m "feat(web): -fsSLk install one-liner + caFingerprint in getCliCredentials"
```

---

### Task 7: Show the fingerprint on the dashboard panels

**Files:**
- Modify: `web/src/screens/Profile/ProfileScreen.tsx:355-357`
- Modify: `web/src/screens/Onboarding/OnboardingScreen.tsx:22` (state type) and the install step JSX (~line 404-407)

**Interfaces:**
- Consumes: `cli.caFingerprint` from Task 6.
- Produces: a visible "CA fingerprint (SHA-256): …" line next to the install command, only when present.

- [ ] **Step 1: Profile panel — render the fingerprint**

In `web/src/screens/Profile/ProfileScreen.tsx`, after the `Proxy:` line (line 357), add:

```tsx
          {cli.data.caFingerprint && (
            <p style={{ color: 'var(--text-faint)', fontSize: 11, wordBreak: 'break-all' }}>
              CA fingerprint (SHA-256): <code>{cli.data.caFingerprint}</code> — <code>ctc login</code> prints this; verify they match.
            </p>
          )}
```

- [ ] **Step 2: Onboarding — widen the cli state type**

In `web/src/screens/Onboarding/OnboardingScreen.tsx`, change line 22:

```tsx
  const [cli, setCli] = useState<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null } | null>(null);
```

- [ ] **Step 3: Onboarding — render the fingerprint**

In `OnboardingScreen.tsx`, inside the `{cli && (...)}` block, after the "token is baked in" paragraph (~line 407), add:

```tsx
                {cli.caFingerprint && (
                  <p style={{ fontSize: 11, color: 'var(--text-faint)', margin: '0 0 18px', wordBreak: 'break-all' }}>
                    CA fingerprint (SHA-256): <code>{cli.caFingerprint}</code> — <code>ctc login</code> prints this; verify they match.
                  </p>
                )}
```

- [ ] **Step 4: Typecheck + build**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/screens/Profile/ProfileScreen.tsx web/src/screens/Onboarding/OnboardingScreen.tsx
git commit -m "feat(web): show CA fingerprint next to the install command"
```

---

### Task 8: Docs

**Files:**
- Modify: `cli/README.md:6,9`
- Modify: `README.md` (the install one-liner, if present)
- Modify: `CLAUDE.md` (client-side section / install instructions)

**Interfaces:** none.

- [ ] **Step 1: Update cli/README.md**

In `cli/README.md`, change the install line (line 6) to include `-k` and note the fingerprint:

```markdown
## Install (once)
    curl -fsSLk https://<ctc-host>/install.sh | sh

The `-k` is required on first contact: the CTC host uses a self-signed cert that
isn't trusted yet. `ctc login` then trusts it and prints the CA's SHA-256
fingerprint — compare it with the one shown in the dashboard "Set up CLI" panel.
```

And update the `ctc login` line (line 9) to mention the fingerprint check.

- [ ] **Step 2: Update README.md and CLAUDE.md**

Search both for the install one-liner and any `curl -fsSL https://` onboarding snippet:

```bash
grep -rn "install.sh" README.md CLAUDE.md
```

Replace each user-facing one-liner with the `-fsSLk` form and add a one-sentence note that the bootstrap is trust-on-first-use with an advisory fingerprint check. Do not change the proxy/control-plane env-var tables.

- [ ] **Step 3: Verify no stale `-fsSL ` one-liners remain**

Run:

```bash
grep -rn "curl -fsSL https://" README.md CLAUDE.md cli/README.md cli/install.sh | grep -v "fsSLk" || echo "clean"
```

Expected: `clean` (every user-facing install one-liner now uses `-fsSLk`).

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md cli/README.md
git commit -m "docs: -fsSLk install one-liner + fingerprint verification note"
```

---

## End-to-end validation (after all tasks)

Per the project's real-binary validation preference, validate the whole flow on `CTC_DOMAIN=localhost`:

```bash
# 1. Regenerate certs with the new SAN (delete old first — gen-cert.sh won't overwrite)
docker run --rm -v ctc_ctccerts:/certs alpine:3.20 sh -c 'rm -f /certs/cert.pem /certs/key.pem'
docker compose --profile tools run --rm gencert
# 2. Bring up the stack
docker compose up -d --build
# 3. Bootstrap as a user would (token from the dashboard "Set up CLI" panel)
curl -fsSLk https://localhost/install.sh | sh -s -- --token <token>
```

Confirm: install succeeds with a single `sudo` prompt; `ctc login` prints a fingerprint; the dashboard shows the same fingerprint; a second dashboard visit shows **no** browser warning; `bash cli/tests/run.sh` and `pytest tests/test_ca_fingerprint.py` pass.

## Self-review notes

- **Spec coverage:** Decision 1 → Tasks 1–2; Decision 2 (`-k`) → Tasks 3,4,6; Decision 2 (fingerprint) → Tasks 4,5,6,7; Decision 3 (docs/tests) → Task 8 + per-task tests. All spec sections covered.
- **Type consistency:** `getCliCredentials` return shape `{ token, proxyHost, installCommand, caFingerprint }` is identical in CtcApi.ts, HttpCtcApi.ts, mockApi.ts, and OnboardingScreen state. `ca_fingerprint_sha256` / response key `ca_fingerprint` / TS `caFingerprint` consistently mapped in Task 6 Step 4.
- **Canonical fingerprint:** CLI uses `openssl …-fingerprint -sha256 | sed 's/^.*=//'`; control plane uses DER-SHA256 colon-hex — both produce the same string (asserted in `tests/test_ca_fingerprint.py::test_matches_openssl`).
