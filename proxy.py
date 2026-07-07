"""
HTTPS CONNECT MITM proxy for GitHub Copilot CLI traffic.

Plain TCP server — clients use:
  HTTPS_PROXY=http://localhost:8080
  + the proxy cert trusted by the client. NOTE: the Copilot CLI bundles its own
  Node runtime and does NOT honor NODE_EXTRA_CA_CERTS / NODE_TLS_REJECT_UNAUTHORIZED;
  trust the cert via the OS trust store (macOS System keychain) — see TDD.md §6.1.

For every CONNECT tunnel:
  1. Respond 200 Connection established
  2. TLS handshake with client using our self-signed cert (MITM)
  3. Decrypt inner HTTP, swap fake token → real PAT, forward upstream
  4. Log everything

Run:
  REAL_GHE_HOST=api.example.ghe.com REAL_PAT=github_pat_xxx python proxy.py
"""

import asyncio, ssl, os, json, logging, time
from typing import Optional, Dict
import aiohttp
from ctc.metering.capture import record_exchange
from ctc.metering.extract import extract_total_nano_aiu
from ctc import contract
from ctc import sentinel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CERT_FILE         = os.environ.get("CERT_FILE", "cert.pem")
KEY_FILE          = os.environ.get("KEY_FILE",  "key.pem")
REAL_GHE_HOST     = os.environ.get("REAL_GHE_HOST", f"api.{contract.GHE_DOMAIN}")
REAL_PAT          = os.environ.get("REAL_PAT", "")
LISTEN_PORT       = int(os.environ.get("PORT", "8080"))
# When the proxy is reachable from a public/untrusted network (e.g. a raw L4
# port forwarded by a front server), set CTC_RESTRICT_CONNECT=1 so CONNECT is
# only honored for the GitHub/GHE/Copilot host set — closing the open-relay
# path. Default off keeps VPN/localhost-only deployments unchanged.
RESTRICT_CONNECT  = os.environ.get("CTC_RESTRICT_CONNECT", "").strip().lower() in ("1", "true", "yes", "on")
# Extra hostnames to allow through CONNECT when CTC_RESTRICT_CONNECT=1 — e.g.
# an internal Jira/Confluence/other MCP host that legitimate tooling (like an
# MCP server) needs to reach. Comma-separated, case-insensitive. Exact host
# match only (no wildcard/suffix matching) to keep the allowlist explicit.
EXTRA_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("CTC_EXTRA_ALLOWED_HOSTS", "").split(",")
    if h.strip()
}
ATTRIBUTION = None  # set by _build_attribution() at startup; None => legacy single-PAT mode
LIVE_QUOTA = None   # set by _build_attribution() in the DB-backed path; LiveQuotaCache or None


def _build_attribution():
    """Construct the AttributionService from env, or return None to keep legacy
    single-PAT behavior. #1 will replace the stub seam with the real provider.

    Real DB path (preferred): CTC_DB_PATH + CTC_SECRET_KEY (and no CTC_IDENTITY_JSON)
      CTC_DB_PATH        = path to the accounting sqlite db
      CTC_SECRET_KEY     = secret key for deriving the encryption key
    When both are set and CTC_IDENTITY_JSON is not set, use the real AuthRegistry.

    Legacy stub path: CTC_IDENTITY_JSON + CTC_PATS_JSON + CTC_DB_PATH
      CTC_IDENTITY_JSON  = {"<fake_token>": {"user_id": "...", "is_giver": true}}
      CTC_PATS_JSON      = {"<giver_id>": "<real_pat>"}
      CTC_DB_PATH        = path to the accounting sqlite db
    All three must be set to enable the stub attribution.

    Note: CTC_DB_PATH is used by BOTH paths.
    """
    # DB-backed path (new): CTC_DB_PATH + CTC_SECRET_KEY
    db_path = os.environ.get("CTC_DB_PATH")
    secret = os.environ.get("CTC_SECRET_KEY")
    if db_path and secret and not os.environ.get("CTC_IDENTITY_JSON"):
        from ctc.accounting.wiring import build_live_engine
        from ctc.auth.crypto import derive_key
        from ctc.auth.registry import AuthRegistry
        from ctc.routing.attribution import AttributionService
        from ctc.store.auth_store import AuthStore
        from ctc.store.db import connect, init_db
        conn = connect(db_path)
        init_db(conn)
        store = AuthStore(conn)
        registry = AuthRegistry(store, derive_key(secret))  # implements IdentityProvider + PatRegistry
        engine = build_live_engine(conn)

        # Proxy-side live-quota cache: lets the failover path pre-check each
        # candidate giver's real GitHub premium_interactions.remaining before
        # selecting/forwarding, and skip dead givers without a wasted round-trip.
        # _fetch_user reads the module `_http` + REAL_GHE_HOST lazily at call
        # time, so building this before _http exists (main() order) is fine.
        async def _fetch_user(pat):
            headers = {"authorization": f"Bearer {pat}",
                       "editor-version": "copilot/1.0.63",
                       "copilot-integration-id": "copilot-developer-cli"}
            url = f"https://{REAL_GHE_HOST}/copilot_internal/user"
            async with _http.request(
                    "GET", url, headers=headers,
                    ssl=build_upstream_ssl_context(UPSTREAM_INSECURE, UPSTREAM_CA_BUNDLE),
                    timeout=aiohttp.ClientTimeout(sock_connect=5, sock_read=10)) as r:
                if r.status != 200:
                    raise RuntimeError(f"/copilot_internal/user -> {r.status}")
                return await r.json()

        from ctc.metering.live_quota import LiveQuotaCache
        global LIVE_QUOTA
        LIVE_QUOTA = LiveQuotaCache(registry.pat_for, _fetch_user, ttl=60)
        return AttributionService(engine, registry, registry)

    # Legacy stub path: CTC_IDENTITY_JSON + CTC_PATS_JSON + CTC_DB_PATH.
    # Re-read CTC_DB_PATH here so this guard is self-contained and does not
    # depend on the db_path variable from the DB-backed block above.
    import json as _json
    ident = os.environ.get("CTC_IDENTITY_JSON")
    pats = os.environ.get("CTC_PATS_JSON")
    db_path = os.environ.get("CTC_DB_PATH")
    if not (ident and pats and db_path):
        return None
    from ctc.accounting.wiring import build_live_engine
    from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
    from ctc.routing.attribution import AttributionService
    from ctc.store.db import connect

    idmap = {tok: ConsumerIdentity(v["user_id"], bool(v["is_giver"]))
             for tok, v in _json.loads(ident).items()}
    engine = build_live_engine(connect(db_path))
    return AttributionService(engine, InMemoryIdentityProvider(idmap),
                              InMemoryPatRegistry(_json.loads(pats)))
UPSTREAM_CA_BUNDLE = os.environ.get("UPSTREAM_CA_BUNDLE") or None
UPSTREAM_INSECURE  = os.environ.get("UPSTREAM_INSECURE", "") not in ("", "0", "false", "False")
LOG_BODY_CAP      = int(os.environ.get("LOG_BODY_CAP", "8192"))
CAPTURE_DIR = os.environ.get("CTC_CAPTURE_DIR")  # metering spike: dump redacted exchanges

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("proxy")

_http: Optional[aiohttp.ClientSession] = None
_server_ssl: Optional[ssl.SSLContext]  = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tag(auth: str) -> str:
    return strip_bearer(auth)[:12] or "(no-token)"

def _emit_finding(finding):
    """Log one structured WARN line for a sentinel Finding; no-op on None."""
    if finding is None:
        return
    log.warning("level=WARN event=ctc.drift kind=%s detail=%s", finding.kind, finding.detail)


def _safe_sentinel_emit(detector, *args, **kwargs):
    """Call detector(*args, **kwargs) and emit any Finding it returns.

    Any exception raised by the detector (or by _emit_finding) is caught and
    logged at ERROR level — it is never propagated.  The response has already
    been relayed to the client by the time this is called, so a throw would
    corrupt the connection with a spurious 502.
    """
    try:
        _emit_finding(detector(*args, **kwargs))
    except Exception as exc:
        log.error("[!] sentinel detector raised (logged, not surfaced): %s", exc)

async def _read_head(reader: asyncio.StreamReader) -> Optional[bytes]:
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            if not chunk:
                return None
            buf += chunk
    except Exception:
        return None
    return buf

def decode_body(raw: bytes, content_encoding: str = "", content_type: str = "", limit: int = 2000) -> str:
    """Decode + pretty-print body for logs; handles gzip/deflate/br/zstd."""
    if not raw:
        return "(empty)"
    data = raw
    enc = (content_encoding or "").lower()
    try:
        if enc == "gzip":
            import gzip; data = gzip.decompress(data)
        elif enc == "deflate":
            import zlib; data = zlib.decompress(data)
        elif enc == "br":
            try:
                import brotli; data = brotli.decompress(data)
            except ImportError:
                return f"<br-compressed {len(raw)} bytes — pip install brotli to decode>"
        elif enc == "zstd":
            try:
                import zstandard; data = zstandard.ZstdDecompressor().decompress(data)
            except ImportError:
                return f"<zstd-compressed {len(raw)} bytes — pip install zstandard to decode>"
    except Exception as exc:
        return f"<decode error {enc}: {exc}>"
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return f"<{len(data)} binary bytes>"
    if "json" in (content_type or "").lower():
        try:
            text = json.dumps(json.loads(text), indent=2)
        except Exception:
            pass
    if len(text) > limit:
        text = text[:limit] + f"\n... <{len(text) - limit} more chars truncated>"
    return text

def _log_block(label: str, text: str):
    """Indented multi-line log entry."""
    log.info("    ┌── %s ──", label)
    for line in text.splitlines() or [""]:
        log.info("    │ %s", line)
    log.info("    └──")


def build_upstream_ssl_context(insecure: bool, ca_bundle):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif ca_bundle:
        ctx.load_verify_locations(ca_bundle)
    return ctx

_HOP_BY_HOP = {"host", "authorization", "content-length",
               "transfer-encoding", "connection", "proxy-connection"}


def should_swap(upstream_host: str) -> bool:
    return upstream_host in SWAP_HOSTS


_BILLABLE_PATHS = contract.BILLABLE_PATHS
_COPILOT_API_HOST = contract.BILLABLE_HOST


def is_billable(upstream_host: str, method: str, path: str) -> bool:
    return (upstream_host == _COPILOT_API_HOST
            and method.upper() == contract.BILLABLE_METHOD
            and path.split("?", 1)[0] in _BILLABLE_PATHS)


def strip_bearer(auth: str) -> str:
    for p in ("Bearer ", "bearer ", "token ", "Token "):
        if auth.startswith(p):
            return auth[len(p):].strip()
    return auth.strip()


_HTTP_REASON = {401: "Unauthorized", 402: "Payment Required", 503: "Service Unavailable"}

def _ctc_block_response(path: str, status: int, message: str) -> bytes:
    """Render a CTC pre-forward rejection in the upstream endpoint's *native*
    error envelope, so the Copilot CLI surfaces our message the same way it shows
    a real GHE quota error. A bare status code (the old empty-body 402) showed the
    user nothing useful. Billable paths are /chat/completions (OpenAI shape) and
    /v1/messages (Anthropic shape)."""
    if path.split("?", 1)[0] == "/v1/messages":
        payload = {"type": "error", "error": {"type": "ctc_error", "message": message}}
    else:
        payload = {"error": {"message": message, "type": "ctc_error", "code": "ctc"}}
    body = json.dumps(payload).encode()
    head = (f"HTTP/1.1 {status} {_HTTP_REASON.get(status, 'Error')}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode()
    return head + body


def _now() -> int:
    return int(time.time())


def build_upstream_headers(hdrs, upstream_host, original_auth, body_len, real_pat):
    fwd = {k: v for k, v in hdrs.items() if k not in _HOP_BY_HOP}
    if should_swap(upstream_host) and real_pat:
        fwd["authorization"] = f"Bearer {real_pat}"
    elif original_auth:
        fwd["authorization"] = original_auth
    fwd["host"] = upstream_host
    if body_len:
        fwd["content-length"] = str(body_len)
    return fwd

# Hosts that are actually "us" — remap to real GHE upstream
_LOCALHOST_ALIASES = {"api.localhost", "localhost", "127.0.0.1"}


def decide_route(host: str, port: int, real_ghe_host: str):
    """Return (do_mitm, upstream_host, upstream_port) for a target host:port."""
    if host in _LOCALHOST_ALIASES:
        return True, real_ghe_host, 443
    return host in MITM_HOSTS, host, port


def connect_allowed(host: str) -> bool:
    """Whether a CONNECT to `host` is permitted when CTC_RESTRICT_CONNECT is on.

    Allows the hosts we MITM plus the wider GitHub/GHE/Copilot ecosystem that
    Copilot legitimately blind-tunnels (telemetry on the GHE domain, github.com,
    *.githubcopilot.com), plus any operator-trusted hosts named in
    CTC_EXTRA_ALLOWED_HOSTS (e.g. an internal Jira/Confluence host an MCP
    server needs to reach). Everything else is refused, so a publicly
    reachable proxy can't be used as an open relay to arbitrary hosts.
    """
    h = host.lower()
    if h in MITM_HOSTS or h in _LOCALHOST_ALIASES:
        return True
    if h in EXTRA_ALLOWED_HOSTS:
        return True
    if contract.is_github_ish(h):        # GHE_DOMAIN / githubcopilot.com suffixes, api.github.com
        return True
    return h == "github.com" or h.endswith(".github.com")


# ---------------------------------------------------------------------------
# Request-body assembly (Content-Length and Transfer-Encoding: chunked)
# ---------------------------------------------------------------------------
async def _read_chunked(reader, leftover: bytes) -> bytes:
    buf = leftover
    out = b""
    while True:
        while b"\r\n" not in buf:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            except asyncio.TimeoutError:
                return out
            if not chunk:
                return out
            buf += chunk
        line, _, buf = buf.partition(b"\r\n")
        size = int(line.split(b";")[0].strip() or b"0", 16)
        if size == 0:
            break
        while len(buf) < size + 2:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            except asyncio.TimeoutError:
                return out
            if not chunk:
                break
            buf += chunk
        out += buf[:size]
        buf = buf[size + 2:]  # drop the chunk's trailing CRLF
    return out


async def assemble_request_body(reader, hdrs, leftover: bytes) -> bytes:
    if "chunked" in hdrs.get("transfer-encoding", "").lower():
        return await _read_chunked(reader, leftover)
    cl = int(hdrs.get("content-length", 0) or 0)
    body = leftover
    while len(body) < cl:
        try:
            chunk = await asyncio.wait_for(reader.read(cl - len(body)), timeout=30)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        body += chunk
    return body


# ---------------------------------------------------------------------------
# Response relay — buffered for small known-length bodies, chunked otherwise
# ---------------------------------------------------------------------------
async def _relay_response(writer, resp, upstream_host, path, method="", request_headers=None,
                          capture_full=False) -> Optional[bytes]:
    log.info("[← RESPONSE] status=%-3s host=%-25s path=%s", resp.status, upstream_host, path)
    ct = resp.headers.get("Content-Type", "")
    cl = resp.headers.get("Content-Length")
    skip = {"transfer-encoding", "content-encoding", "content-length", "connection"}
    rh = {k: v for k, v in resp.headers.items() if k.lower() not in skip}

    # RFC 7230 §3.3: 204 and 304 responses MUST NOT include a message body or
    # Transfer-Encoding.  Short-circuit before any content read.
    if resp.status in (204, 304):
        rh["Connection"] = "keep-alive"
        hblock = "".join(f"{k}: {v}\r\n" for k, v in rh.items())
        writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode())
        await writer.drain()
        return None

    buffered = cl is not None and cl.isdigit() and int(cl) <= LOG_BODY_CAP
    if buffered:
        rb = await resp.read()
        if CAPTURE_DIR:
            record_exchange(CAPTURE_DIR, method=method, path=path, upstream_host=upstream_host,
                            status=resp.status, request_headers=request_headers or {},
                            response_headers=dict(resp.headers), response_body=rb,
                            response_content_type=ct)
        _log_block("RESPONSE BODY", decode_body(rb, "", ct, LOG_BODY_CAP))
        rh["Content-Length"] = str(len(rb))
        rh["Connection"] = "keep-alive"
        hblock = "".join(f"{k}: {v}\r\n" for k, v in rh.items())
        writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode() + rb)
        await writer.drain()
        return rb if capture_full else None

    rh["Transfer-Encoding"] = "chunked"
    rh["Connection"] = "keep-alive"
    hblock = "".join(f"{k}: {v}\r\n" for k, v in rh.items())
    writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode())
    await writer.drain()
    tee = bytearray()
    full = bytearray() if (CAPTURE_DIR or capture_full) else None
    async for chunk in resp.content.iter_chunked(65536):
        writer.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
        await writer.drain()
        if len(tee) < LOG_BODY_CAP:
            tee.extend(chunk[:LOG_BODY_CAP - len(tee)])
        if full is not None:
            full.extend(chunk)
    writer.write(b"0\r\n\r\n")
    await writer.drain()
    if CAPTURE_DIR:
        record_exchange(CAPTURE_DIR, method=method, path=path, upstream_host=upstream_host,
                        status=resp.status, request_headers=request_headers or {},
                        response_headers=dict(resp.headers), response_body=bytes(full),
                        response_content_type=ct)
    _log_block("RESPONSE BODY (streamed)",
               decode_body(bytes(tee), "", ct, LOG_BODY_CAP) + "\n… (streamed, truncated)")
    if capture_full:
        return bytes(full) if full is not None else b""
    return None


def _write_buffered(writer, resp, body: bytes) -> None:
    """Relay an already-read upstream response (status line + headers + body) to
    the client. Used by the failover path when we've had to .read() a 402 to peek
    its error code and so can no longer stream it via _relay_response. Mirrors the
    buffered branch of _relay_response: drop hop-by-hop/length/encoding headers and
    re-emit a fixed Content-Length."""
    rh = {k: v for k, v in resp.headers.items()
          if k.lower() not in ("content-length", "transfer-encoding",
                               "content-encoding", "connection")}
    rh["Content-Length"] = str(len(body))
    rh["Connection"] = "keep-alive"
    hblock = "".join(f"{k}: {v}\r\n" for k, v in rh.items())
    writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode() + body)


# ---------------------------------------------------------------------------
# Failover helpers (live-quota health gate + 402-driven giver retry)
# ---------------------------------------------------------------------------
def is_quota_exceeded_402(status: int, body: bytes) -> bool:
    """True iff this is a real GitHub premium-quota 402 (error.code ==
    "quota_exceeded"). False for non-402, CTC's own 402 block (code "ctc"), and
    non-JSON bodies."""
    if status != 402:
        return False
    try:
        err = (json.loads(body or b"{}").get("error") or {})
    except Exception:
        return False
    return err.get("code") == "quota_exceeded"


def candidate_givers(engine, cycle_id, consumer) -> set:
    """The set of giver_ids whose live quota is worth pre-checking for this
    consumer: the consumer itself if it's a giver, every donor backing an active
    grant to it, and — for a shared-pool-eligible consumer — every giver with pool
    capacity. Pre-checking the pool givers is what lets select_source skip a dead
    one and lets the caller's failover loop retry across them (otherwise a pool
    consumer got max_attempts=1 and a dead top giver's 402 was relayed as-is)."""
    ids = set()
    if getattr(consumer, "is_giver", False):
        ids.add(consumer.user_id)
    for g in engine.active_grants(cycle_id, consumer.user_id):
        ids.add(g.donor_id)
    if not getattr(consumer, "is_giver", False) \
            and getattr(engine.config, "shared_pool_enabled", True) \
            and engine.allowance_remaining(cycle_id, consumer.user_id) > 0:
        for giver_id, _rem in engine.givers_with_pool_capacity(cycle_id):
            ids.add(giver_id)
    return ids


async def reconcile_candidate(engine, live_cache, cycle_id, giver_id):
    """Fetch a candidate giver's live quota, reconcile out-of-band drift into a
    BYPASS event, and return their live remaining (None if unknown). Best-effort:
    a reconcile failure never blocks routing or distorts the returned health."""
    v = await live_cache.get(giver_id) if live_cache is not None else None
    if v is None:
        return None
    try:
        engine.reconcile_giver(cycle_id, giver_id, v)
    except Exception as exc:
        log.warning("[reconcile] candidate %s failed: %s", giver_id, exc)
    r = v.get("remaining")
    return int(r) if r is not None else None


async def reconcile_exhausted(engine, live_cache, cycle_id, giver_id) -> None:
    """A really-dead giver (upstream 402 quota_exceeded): book the outstanding
    out-of-band burn as a BYPASS event so every surface reflects it, and mark the
    live cache exhausted so health-gated selection skips it. The quota ceiling is
    NOT mutated — all usage lives in events. Best-effort: never raises."""
    try:
        v = await live_cache.get(giver_id) if live_cache is not None else None
        ent = v.get("entitlement") if v else None
        if ent is not None and int(ent) >= 0:
            engine.reconcile_giver(cycle_id, giver_id,
                                   {"entitlement": int(ent), "remaining": 0})
    except Exception as exc:
        log.warning("[failover] reconcile failed for %s: %s", giver_id, exc)
    if live_cache is not None:
        live_cache.set_exhausted(giver_id)


# ---------------------------------------------------------------------------
# HTTP request loop (runs after TLS is up)
# ---------------------------------------------------------------------------
async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 upstream_host: str, port: int = 443):
    upstream_ssl = build_upstream_ssl_context(UPSTREAM_INSECURE, UPSTREAM_CA_BUNDLE)

    while True:
        raw = await _read_head(reader)
        if raw is None:
            break

        head, _, leftover = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        try:
            method, path, _ = lines[0].decode(errors="replace").split(" ", 2)
        except ValueError:
            break

        hdrs: Dict[str, str] = {}
        for line in lines[1:]:
            if b":" in line:
                k, _, v = line.partition(b":")
                hdrs[k.decode().strip().lower()] = v.decode().strip()

        body = await assemble_request_body(reader, hdrs, leftover)

        auth    = hdrs.get("authorization", "")
        session = _tag(auth)

        # NOTE: We deliberately do NOT mock /user or /copilot_internal/*
        # endpoints. The PAT we swap in is valid for all of them on GHE, and
        # Copilot reads the real /user response to decide it's entitled + how to
        # proceed. There is NO token-exchange step in this flow: the captures show
        # no /copilot_internal/v2/token call, and copilot-api accepts the swapped
        # PAT directly as Bearer (verified by tools/verify_token_rewrite.py).
        # Copilot keeps one token throughout; we swap it to the PAT on every call.

        # ── Forward everything else ────────────────────────────────────────
        tag = "[→ COPILOT] " if "copilot" in path.lower() else "[→ REQUEST] "
        log.info("%s session=%-12s method=%-6s host=%-25s path=%s",
                 tag, session, method, upstream_host, path)
        for k, v in hdrs.items():
            log.info("    %-30s %s", k + ":", "***MASKED***" if k == "authorization" else v)
        if body:
            _log_block("REQUEST BODY", decode_body(body, "", hdrs.get("content-type", ""), LOG_BODY_CAP))

        source = None
        consumer = None
        pat_to_use = REAL_PAT
        billable = ATTRIBUTION is not None and is_billable(upstream_host, method, path)
        if billable:
            # ensure_active_cycle also rolls a month-ended cycle over (archive +
            # open + seed) on first access. It is fully synchronous — no `await`
            # between its BEGIN IMMEDIATE and COMMIT — so it respects the no-await
            # invariant documented below for select_source/debit.
            cycle = ATTRIBUTION.engine.ensure_active_cycle(_now())
            consumer = ATTRIBUTION.resolve_consumer(strip_bearer(auth)) if cycle else None
            # Live-quota health gate: pre-fetch each candidate giver's real GitHub
            # premium_interactions.remaining so select_source can skip a giver that
            # is already dead at the source. This awaits BEFORE select_source, so
            # the no-await-inside-transaction invariant below still holds.
            health: Dict[str, Optional[int]] = {}
            if cycle and consumer and LIVE_QUOTA is not None:
                for gid in candidate_givers(ATTRIBUTION.engine, cycle.id, consumer):
                    health[gid] = await reconcile_candidate(
                        ATTRIBUTION.engine, LIVE_QUOTA, cycle.id, gid)
            source = (ATTRIBUTION.select_source(cycle.id, consumer, health=health)
                      if (cycle and consumer) else None)
            if source is None:
                # Pre-gate failed: no eligible credit. Block BEFORE forwarding.
                # Log the specific cause so operators can distinguish misconfigurations.
                if cycle is None:
                    log.warning("[503] no active cycle (accounting DB misconfigured?)")
                    resp = _ctc_block_response(
                        path, 503,
                        "CTC has no active billing cycle. Contact your CTC operator.")
                elif consumer is None:
                    log.warning("[401] unknown consumer token (session=%s)", session)
                    resp = _ctc_block_response(
                        path, 401,
                        "Your CTC proxy token was not recognized. Run `ctc login` to refresh it.")
                else:
                    log.warning("[402] no eligible credit for session=%s", session)
                    resp = _ctc_block_response(
                        path, 402,
                        "You have exceeded your monthly quota (CTC credit pool).")
                writer.write(resp)
                await writer.drain()
                continue
            # INVARIANT: engine calls here must stay synchronous; the shared sqlite
            # connection is not safe across `await` points between select_source and
            # debit.  This is safe only because current_cycle/select_source/debit are
            # all fully synchronous — no `await` occurs between BEGIN IMMEDIATE and
            # COMMIT, so the event loop cannot interleave two transactions.
            pat_to_use = source.pat

        # Non-billable GHE calls (token validation/exchange: /copilot_internal/*)
        # still need a real PAT, but attribution only selects one for billable
        # requests and there's no REAL_PAT in multi-tenant mode. Without this the
        # client's fake token is forwarded as-is and GHE returns 401 Bad credentials.
        # Borrow any stored giver PAT (no metering — these calls aren't billable).
        # Gated on should_swap so non-GHE MITM hosts (e.g. api.github.com) never
        # receive a giver PAT. Also require a recognized CTC proxy token: without
        # this an unknown bearer could borrow a giver PAT for non-metered GHE calls
        # (e.g. reading entitlement via /copilot_internal/user). Billable requests
        # are already gated above; this closes the same hole on non-billable ones.
        if not pat_to_use and ATTRIBUTION is not None and should_swap(upstream_host):
            if consumer is None:
                consumer = ATTRIBUTION.resolve_consumer(strip_bearer(auth))
            if consumer is None:
                log.warning("[401] unrecognized token on non-billable GHE call (session=%s)", session)
                resp = _ctc_block_response(
                    path, 401,
                    "Your CTC proxy token was not recognized. Run `ctc login` to refresh it.")
                writer.write(resp)
                await writer.drain()
                continue
            pat_to_use = ATTRIBUTION.any_giver_pat() or pat_to_use

        # Forward with failover-on-402. For a billable request with a resolved
        # source we may retry across candidate givers: a real GitHub premium-quota
        # 402 (error.code == "quota_exceeded") on one giver reconciles its ledger,
        # excludes it, and re-selects the next bucket. Non-billable requests (and
        # billable ones with no source — which were already 402-blocked above) make
        # exactly one attempt. The cap is len(health)+1: at most one try per
        # pre-checked giver plus the initial source.
        _status = 0
        _ct = ""
        exclude: set = set()
        attempts = 0
        max_attempts = len(health) + 1 if billable else 1
        try:
            while True:
                attempts += 1
                if billable and source is not None:
                    pat_to_use = source.pat
                fwd = build_upstream_headers(hdrs, upstream_host, auth, len(body), pat_to_use)
                async with _http.request(
                    method   = method,
                    url      = f"https://{upstream_host}{path}",
                    headers  = fwd,
                    data     = body or None,
                    ssl      = upstream_ssl,
                    allow_redirects = False,
                    timeout  = aiohttp.ClientTimeout(sock_connect=10, sock_read=120),
                ) as resp:
                    if (billable and source is not None and attempts < max_attempts
                            and resp.status == 402):
                        # Peek the body to distinguish a real quota_exceeded 402
                        # from anything else. Reading consumes the response, so we
                        # can no longer stream it — relay via _write_buffered.
                        peek = await resp.read()
                        if is_quota_exceeded_402(resp.status, peek):
                            await reconcile_exhausted(ATTRIBUTION.engine, LIVE_QUOTA,
                                                      cycle.id, source.giver_id)
                            exclude.add(source.grant_id or source.giver_id)
                            nxt = ATTRIBUTION.select_source(
                                cycle.id, consumer,
                                health=health, exclude=frozenset(exclude))
                            if nxt is not None:
                                log.warning("[failover] %s exhausted -> retry via %s",
                                            source.giver_id, nxt.giver_id)
                                source = nxt
                                continue
                        # Not a retriable quota 402, or no next bucket: relay this
                        # 402 (already read) to the client and stop.
                        _write_buffered(writer, resp, peek)
                        await writer.drain()
                        _status = resp.status
                        _ct = resp.headers.get("Content-Type", "")
                        break
                    full_body = await _relay_response(writer, resp, upstream_host, path, method,
                                                      hdrs, capture_full=billable)
                    _status = resp.status
                    _ct = resp.headers.get("Content-Type", "")
                if billable and _status == 200:
                    if not full_body:
                        log.warning("[!] billable 200 had empty/None body; debiting 0 path=%s", path)
                    _safe_sentinel_emit(sentinel.check_billable_response, _status, full_body or b"", _ct, path.split("?", 1)[0])
                    cost = extract_total_nano_aiu(full_body or b"", _ct)
                    try:
                        ATTRIBUTION.debit(cycle.id, consumer, source, cost, ts=_now())
                    except Exception as exc:  # debit must never break the sent response
                        log.error("[!] debit failed (logged, not surfaced): %s", exc)
                if is_billable(upstream_host, method, path) and _status in (400, 401, 403):
                    _safe_sentinel_emit(sentinel.check_billable_rejection, _status, path.split("?", 1)[0])
                break
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            log.error("[!] Upstream timeout: %s %s", method, path)
            writer.write(b"HTTP/1.1 504 Gateway Timeout\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            break
        except Exception as exc:
            log.error("[!] Forward error: %s", exc)
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            break

# Hosts we actively MITM (decrypt + log + mock/swap). Everything else
# is blind-tunneled at the TCP layer so it works exactly like no-proxy.
MITM_HOSTS = set(contract.EXPECTED_MITM_HOSTS)

# All GHE hosts we MITM get the PAT swap.
# Note: the copilot-telemetry-service.* host is blind-tunneled (not in MITM_HOSTS)
# so it does not receive the token swap.
SWAP_HOSTS = set(contract.SWAP_HOSTS)

# ---------------------------------------------------------------------------
# Blind TCP tunnel — copies bytes both ways without inspection
# ---------------------------------------------------------------------------
async def _blind_tunnel(client_reader, client_writer, host: str, port: int):
    try:
        up_reader, up_writer = await asyncio.open_connection(host, port)
    except Exception as exc:
        log.warning("[TUNNEL]    upstream connect failed (%s:%s): %s", host, port, exc)
        try:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await client_writer.drain()
        except Exception:
            pass
        return

    async def pipe(r, w):
        try:
            while True:
                data = await r.read(65536)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except Exception:
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    await asyncio.gather(
        pipe(client_reader, up_writer),
        pipe(up_reader, client_writer),
    )
async def _dispatch(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    try:
        raw = await _read_head(reader)
        if raw is None:
            return

        first = raw.split(b"\r\n")[0].decode(errors="replace").strip()

        # ── CONNECT tunnel ─────────────────────────────────────────────────
        if first.upper().startswith("CONNECT "):
            target = first.split()[1]
            host, port = (target.rsplit(":", 1) if ":" in target else (target, "443"))
            port = int(port)

            # Decide: MITM or blind tunnel (also remaps localhost aliases)
            do_mitm, tunnel_host, tunnel_port = decide_route(host, port, REAL_GHE_HOST)

            # Open-relay guard for publicly reachable proxies (CTC_RESTRICT_CONNECT).
            # Refuse tunnels to anything outside the GitHub/GHE/Copilot ecosystem.
            if RESTRICT_CONNECT and not connect_allowed(host):
                log.warning("[CONNECT]   REJECTED (restricted) %s → %s:%s", peer, host, port)
                writer.write(b"HTTP/1.1 403 Forbidden\r\nProxy-Agent: copilot-proxy\r\n\r\n")
                await writer.drain()
                return

            log.info("[CONNECT]   %s → %s:%s  [%s]", peer, host, port,
                     "MITM" if do_mitm else "tunnel")

            writer.write(b"HTTP/1.1 200 Connection established\r\nProxy-Agent: copilot-proxy\r\n\r\n")
            await writer.drain()

            if not do_mitm:
                _safe_sentinel_emit(sentinel.check_bypassed_host, host)
                # Blind passthrough — works just like no proxy at all
                await _blind_tunnel(reader, writer, tunnel_host, tunnel_port)
                return

            # TLS MITM: upgrade this connection to TLS (we impersonate the target)
            loop      = asyncio.get_running_loop()
            transport = writer.transport
            protocol  = transport.get_protocol()
            try:
                tls_t = await loop.start_tls(transport, protocol, _server_ssl, server_side=True)
            except (ssl.SSLError, ConnectionResetError) as exc:
                log.warning("[CONNECT]   TLS MITM failed (%s): %s", host, exc)
                return

            tls_w = asyncio.StreamWriter(tls_t, protocol, reader, loop)
            await _serve(reader, tls_w, tunnel_host, tunnel_port)

        # ── Direct plain HTTP (no CONNECT) ─────────────────────────────────
        else:
            head, _, _ = raw.partition(b"\r\n\r\n")
            hdrs: Dict[str, str] = {}
            for line in head.split(b"\r\n")[1:]:
                if b":" in line:
                    k, _, v = line.partition(b":")
                    hdrs[k.decode().strip().lower()] = v.decode().strip()
            host = hdrs.get("host", REAL_GHE_HOST).split(":")[0]
            replay = asyncio.StreamReader()
            replay.feed_data(raw)
            replay.feed_eof()  # single one-shot request; without EOF _serve's next
                               # _read_head blocks until the 30s timeout before close.
            _, up_host, _ = decide_route(host, 443, REAL_GHE_HOST)
            await _serve(replay, writer, up_host)

    except Exception as exc:
        log.exception("Dispatch error: %s", exc)
    finally:
        try:
            writer.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    global _http, _server_ssl, ATTRIBUTION

    ATTRIBUTION = _build_attribution()
    if ATTRIBUTION is not None:
        log.info("attribution: ENABLED (multi-tenant routing)")
    else:
        log.info("attribution: disabled (legacy single-PAT mode)")

    _server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    _server_ssl.load_cert_chain(CERT_FILE, KEY_FILE)
    _server_ssl.set_alpn_protocols(["http/1.1"])

    _http = aiohttp.ClientSession(connector=aiohttp.TCPConnector())
    if UPSTREAM_INSECURE:
        log.warning("UPSTREAM_INSECURE=1 — upstream GHE certificate will NOT be verified")

    if not REAL_PAT:
        log.warning("REAL_PAT is not set — forwarded requests will have no auth!")

    srv = await asyncio.start_server(_dispatch, "0.0.0.0", LISTEN_PORT)
    log.info("=" * 60)
    log.info("  Copilot MITM proxy listening on port %s", LISTEN_PORT)
    log.info("  Upstream:  https://%s", REAL_GHE_HOST)
    log.info("  Client env vars to set:")
    log.info("    HTTPS_PROXY=http://localhost:%s", LISTEN_PORT)
    log.info("    NODE_EXTRA_CA_CERTS=%s", os.path.abspath(CERT_FILE))
    log.info("=" * 60)

    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Proxy stopped.")
    finally:
        if _http and not _http.closed:
            asyncio.run(_http.close())
