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
from ctc.metering.capture import record_exchange, redact_text, redact_headers, close_captures
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
# port forwarded by a front server), set CTC_RESTRICT_CONNECT=1 so both CONNECT
# tunnels AND direct (non-CONNECT) plain-HTTP proxy requests are only honored
# for the GitHub/GHE/Copilot host set — closing the open-relay/SSRF path on
# both dispatch branches. Default off keeps VPN/localhost-only deployments
# unchanged.
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
        from ctc.auth.crypto import derive_key, validate_secret
        validate_secret(secret)
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
                    ssl=upstream_ssl_context(),
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
def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _insecure_requested(env) -> bool:
    return _truthy(env.get("UPSTREAM_INSECURE", ""))


def _parse_insecure(env) -> bool:
    """Upstream TLS verification is disabled ONLY when BOTH UPSTREAM_INSECURE
    and UPSTREAM_INSECURE_CONFIRM are truthy. Disabling verification exposes the
    real PAT to an on-path attacker, so a bare UPSTREAM_INSECURE (no confirm) is
    refused: verification stays ON (the caller logs an ERROR). Pure — no I/O."""
    return _insecure_requested(env) and _truthy(env.get("UPSTREAM_INSECURE_CONFIRM", ""))


UPSTREAM_CA_BUNDLE = os.environ.get("UPSTREAM_CA_BUNDLE") or None
UPSTREAM_INSECURE  = _parse_insecure(os.environ)
LOG_BODY_CAP      = int(os.environ.get("LOG_BODY_CAP", "8192"))
CAPTURE_DIR = os.environ.get("CTC_CAPTURE_DIR")  # metering spike: dump redacted exchanges
# Upper bound on the in-memory buffer we keep for a streamed response (billing +
# capture). The per-request charge lives in the FINAL SSE event, so we keep the
# trailing window, not the head, bounding memory on very long streams.
CAPTURE_TAIL_CAP = 256 * 1024

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

_HEAD_CAP = 64 * 1024


async def _read_head(reader: asyncio.StreamReader) -> Optional[bytes]:
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            if not chunk:
                return None
            buf += chunk
            if len(buf) > _HEAD_CAP:
                # Bound memory on a client that never sends the header terminator
                # (garbage / slowloris-ish). Give up and close.
                log.warning("[head] request head exceeded %d bytes without terminator; closing",
                            _HEAD_CAP)
                return None
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
    """Indented multi-line log entry. Emitted at DEBUG only: request/response
    bodies are 30-80 verbose records per request and can carry secrets, so they
    stay off unless the operator explicitly turns logging up. Callers must have
    already run the text through redact_text()."""
    log.debug("    ┌── %s ──", label)
    for line in text.splitlines() or [""]:
        log.debug("    │ %s", line)
    log.debug("    └──")


def build_upstream_ssl_context(insecure: bool, ca_bundle):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif ca_bundle:
        ctx.load_verify_locations(ca_bundle)
    return ctx


# Process-wide upstream SSLContext, built lazily once. A fresh context per
# connection (the old behavior) parsed the CA bundle synchronously on the event
# loop AND defeated aiohttp connection pooling — the pool is keyed by
# SSLContext identity, so a new context per call meant every upstream tunnel
# paid a full TCP+TLS handshake to GHE. Resettable (set _upstream_ssl = None)
# so tests that monkeypatch UPSTREAM_INSECURE / UPSTREAM_CA_BUNDLE after import
# force a rebuild.
_upstream_ssl: Optional[ssl.SSLContext] = None


def upstream_ssl_context() -> ssl.SSLContext:
    global _upstream_ssl
    if _upstream_ssl is None:
        _upstream_ssl = build_upstream_ssl_context(UPSTREAM_INSECURE, UPSTREAM_CA_BUNDLE)
    return _upstream_ssl

_HOP_BY_HOP = {"host", "authorization", "content-length",
               "transfer-encoding", "connection", "proxy-connection"}


def _compute_accept_encoding() -> str:
    """Encodings we can actually decode for relay + billing. Node/Copilot
    advertises `br`, but if the `brotli` package isn't installed a br response
    can't be decompressed and the relay 502s (br/zstd are load-bearing for
    RELAYING, not just log decoding). So we pin the forwarded accept-encoding to
    the codecs this process can decode — gzip/deflate always, br/zstd only when
    their library is importable. aiohttp transparently decompresses these on the
    upstream response, so extract/relay see plaintext."""
    codecs = ["gzip", "deflate"]
    try:
        import brotli  # noqa: F401
        codecs.append("br")
    except ImportError:
        pass
    try:
        import zstandard  # noqa: F401
        codecs.append("zstd")
    except ImportError:
        pass
    return ", ".join(codecs)


_ACCEPT_ENCODING = _compute_accept_encoding()


def should_swap(upstream_host: str) -> bool:
    return upstream_host in SWAP_HOSTS


_BILLABLE_PATHS = contract.BILLABLE_PATHS
_COPILOT_API_HOST = contract.BILLABLE_HOST


def is_billable(upstream_host: str, method: str, path: str) -> bool:
    return (upstream_host == _COPILOT_API_HOST
            and method.upper() == contract.BILLABLE_METHOD
            and path.split("?", 1)[0] in _BILLABLE_PATHS)


def is_session_bootstrap(upstream_host: str, method: str, path: str) -> bool:
    """POST /models/session: resolves auto_mode -> concrete model + a
    copilot-session-token bound to whichever giver identity requests it.
    Not billable/metered itself, but its giver pick must be pinned and reused
    on the client's next billable call -- see ctc/routing/attribution.py."""
    return (upstream_host == _COPILOT_API_HOST
            and method.upper() == contract.BILLABLE_METHOD
            and path.split("?", 1)[0] == contract.SESSION_BOOTSTRAP_PATH)


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
    # Force accept-encoding to codecs we can decode: a client-advertised `br`
    # with brotli uninstalled would otherwise come back br-compressed and 502
    # the relay (and zero out billing).
    fwd["accept-encoding"] = _ACCEPT_ENCODING
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
class RequestBodyError(Exception):
    """Malformed or incomplete client request body. Rather than forward a
    truncated/corrupt body upstream (which corrupts billing and, under
    keep-alive pipelining, the next request), the proxy replies 400 and closes."""


async def _read_chunked(reader, leftover: bytes) -> bytes:
    buf = bytearray(leftover)
    out = bytearray()
    while True:
        while b"\r\n" not in buf:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            except asyncio.TimeoutError:
                raise RequestBodyError("timeout reading chunk size")
            if not chunk:
                raise RequestBodyError("EOF before chunk size")
            buf += chunk
        line, _, rest = buf.partition(b"\r\n")
        buf = bytearray(rest)
        try:
            size = int(line.split(b";")[0].strip() or b"0", 16)
        except ValueError:
            raise RequestBodyError("malformed chunk size")
        if size == 0:
            # Consume the optional trailer section, terminated by a blank line,
            # so it isn't mistaken for the head of a pipelined next request.
            while True:
                while b"\r\n" not in buf:
                    try:
                        chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
                    except asyncio.TimeoutError:
                        raise RequestBodyError("timeout reading trailers")
                    if not chunk:
                        return bytes(out)  # EOF w/o terminating CRLF — body is complete
                    buf += chunk
                tline, _, rest = buf.partition(b"\r\n")
                buf = bytearray(rest)
                if tline == b"":
                    break
            break
        while len(buf) < size + 2:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            except asyncio.TimeoutError:
                raise RequestBodyError("timeout reading chunk body")
            if not chunk:
                raise RequestBodyError("EOF mid-chunk")
            buf += chunk
        out += buf[:size]
        buf = bytearray(buf[size + 2:])  # drop the chunk's trailing CRLF
    return bytes(out)


async def assemble_request_body(reader, hdrs, leftover: bytes) -> bytes:
    if "chunked" in hdrs.get("transfer-encoding", "").lower():
        return await _read_chunked(reader, leftover)
    try:
        cl = int(hdrs.get("content-length", 0) or 0)
    except ValueError:
        raise RequestBodyError("malformed content-length")
    body = bytearray(leftover)
    if len(body) > cl:
        # More bytes buffered than Content-Length declares — truncate so the
        # excess (a pipelined next request) doesn't corrupt this forwarded body.
        log.warning("[body] buffered bytes exceed Content-Length (%d > %d); truncating",
                    len(body), cl)
        return bytes(body[:cl])
    while len(body) < cl:
        try:
            chunk = await asyncio.wait_for(reader.read(cl - len(body)), timeout=30)
        except asyncio.TimeoutError:
            raise RequestBodyError("timeout reading body")
        if not chunk:
            raise RequestBodyError("EOF before Content-Length satisfied")
        body += chunk
    return bytes(body)


# ---------------------------------------------------------------------------
# Response relay — buffered for small known-length bodies, chunked otherwise
# ---------------------------------------------------------------------------
class RelayState:
    """Progress holder threaded through _relay_response so the caller can tell,
    after a relay that raised (client disconnect / upstream death mid-stream),
    how far it got:

    - head_sent: the response status line + headers were already written to the
      client. If True we must NOT inject a fresh HTTP status line (a 502/504) —
      it would land inside the open chunked body and corrupt the stream — so we
      abort the socket instead (_fail_client).
    - status / content_type: the upstream response's, for the partial-relay
      debit decision + cost extraction.
    - body: the streamed/buffered response bytes captured so far (a bytearray
      when capture was requested), so a dropped billable stream can still be
      best-effort debited from whatever we have.
    """
    __slots__ = ("head_sent", "status", "content_type", "body")

    def __init__(self):
        self.head_sent = False
        self.status = 0
        self.content_type = ""
        self.body = None


def _headers_block(headers, skip, extra) -> str:
    """Render an HTTP response header block. Iterates `headers` as a LIST of
    (k, v) pairs — aiohttp's CIMultiDict yields duplicate keys separately — so
    duplicate Set-Cookie headers survive instead of being collapsed by a dict;
    drops any key in `skip`, then appends the headers we set ourselves (`extra`)."""
    pairs = [(k, v) for k, v in headers.items() if k.lower() not in skip]
    pairs.extend(extra.items())
    return "".join(f"{k}: {v}\r\n" for k, v in pairs)


async def _relay_response(writer, resp, upstream_host, path, method="", request_headers=None,
                          capture_full=False, state: Optional["RelayState"] = None) -> Optional[bytes]:
    log.info("[← RESPONSE] status=%-3s host=%-25s path=%s", resp.status, upstream_host, path)
    ct = resp.headers.get("Content-Type", "")
    cl = resp.headers.get("Content-Length")
    if state is not None:
        state.status = resp.status
        state.content_type = ct
    skip = {"transfer-encoding", "content-encoding", "content-length", "connection"}

    # RFC 7230 §3.3: 204 and 304 responses MUST NOT include a message body or
    # Transfer-Encoding.  Short-circuit before any content read.
    if resp.status in (204, 304):
        hblock = _headers_block(resp.headers, skip, {"Connection": "keep-alive"})
        writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode())
        if state is not None:
            state.head_sent = True
        await writer.drain()
        return None

    buffered = cl is not None and cl.isdigit() and int(cl) <= LOG_BODY_CAP
    if buffered:
        rb = await resp.read()
        if state is not None:
            state.body = bytearray(rb)
        if CAPTURE_DIR:
            record_exchange(CAPTURE_DIR, method=method, path=path, upstream_host=upstream_host,
                            status=resp.status, request_headers=request_headers or {},
                            response_headers=dict(resp.headers), response_body=rb,
                            response_content_type=ct)
        if log.isEnabledFor(logging.DEBUG):
            _log_block("RESPONSE BODY", redact_text(decode_body(rb, "", ct, LOG_BODY_CAP)))
        hblock = _headers_block(resp.headers, skip,
                                {"Content-Length": str(len(rb)), "Connection": "keep-alive"})
        writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode() + rb)
        if state is not None:
            state.head_sent = True
        await writer.drain()
        return rb if capture_full else None

    hblock = _headers_block(resp.headers, skip,
                            {"Transfer-Encoding": "chunked", "Connection": "keep-alive"})
    writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode())
    if state is not None:
        state.head_sent = True
    await writer.drain()
    tee = bytearray()
    # When capturing, the streamed buffer IS state.body, so a relay that raises
    # mid-stream leaves the caller with the bytes we managed to read (for a
    # best-effort partial-relay debit).
    if CAPTURE_DIR or capture_full:
        full = bytearray()
        if state is not None:
            state.body = full
    else:
        full = None
    trimmed_billable = False
    async for chunk in resp.content.iter_chunked(65536):
        if full is not None:
            full.extend(chunk)
            if len(full) > CAPTURE_TAIL_CAP:
                # Keep only the trailing window — the charge is in the final SSE
                # event. (A very large non-SSE JSON body would lose its head and
                # so its top-level charge; WARN so that's visible.)
                del full[:len(full) - CAPTURE_TAIL_CAP]
                if capture_full and not trimmed_billable:
                    log.warning("[capture] billable response exceeded %d bytes; "
                                "keeping trailing window for billing path=%s",
                                CAPTURE_TAIL_CAP, path)
                    trimmed_billable = True
        writer.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
        await writer.drain()
        if len(tee) < LOG_BODY_CAP:
            tee.extend(chunk[:LOG_BODY_CAP - len(tee)])
    writer.write(b"0\r\n\r\n")
    await writer.drain()
    if CAPTURE_DIR:
        record_exchange(CAPTURE_DIR, method=method, path=path, upstream_host=upstream_host,
                        status=resp.status, request_headers=request_headers or {},
                        response_headers=dict(resp.headers), response_body=bytes(full),
                        response_content_type=ct)
    if log.isEnabledFor(logging.DEBUG):
        _log_block("RESPONSE BODY (streamed)",
                   redact_text(decode_body(bytes(tee), "", ct, LOG_BODY_CAP))
                   + "\n… (streamed, truncated)")
    if capture_full:
        return bytes(full) if full is not None else b""
    return None


def _write_buffered(writer, resp, body: bytes, state: Optional["RelayState"] = None) -> None:
    """Relay an already-read upstream response (status line + headers + body) to
    the client. Used by the failover path when we've had to .read() a 402 to peek
    its error code and so can no longer stream it via _relay_response. Mirrors the
    buffered branch of _relay_response: drop hop-by-hop/length/encoding headers and
    re-emit a fixed Content-Length."""
    skip = {"content-length", "transfer-encoding", "content-encoding", "connection"}
    hblock = _headers_block(resp.headers, skip,
                            {"Content-Length": str(len(body)), "Connection": "keep-alive"})
    writer.write(f"HTTP/1.1 {resp.status} {resp.reason}\r\n{hblock}\r\n".encode() + body)
    if state is not None:
        state.status = resp.status
        state.head_sent = True


def _fail_client(writer, state: Optional["RelayState"], status_bytes: bytes) -> None:
    """Terminate the client side of a relay that raised. If the response head was
    already sent (mid-chunked-body or after a buffered write), we CANNOT write a
    fresh HTTP status line — it would corrupt the client's in-flight stream — so
    abort the transport. Otherwise best-effort deliver the error status. All
    writes are exception-safe; the client may already be gone."""
    if state is not None and state.head_sent:
        try:
            writer.transport.abort()
        except Exception:
            pass
        return
    try:
        writer.write(status_bytes)
    except Exception:
        pass


def _reconcile_partial_relay(billable, debited, state: Optional["RelayState"],
                             cycle, consumer, source, path) -> None:
    """P1-1: a relay that raised (client Ctrl-C mid-SSE, upstream death) skips
    the normal post-relay debit even though upstream may have fully burned the
    giver's quota — leaving the cost to be mis-booked later as a BYPASS on the
    giver (giver charged, consumer free). Best-effort extract the cost from the
    bytes we buffered and debit exactly once here, with a distinctive marker.
    Never raises."""
    if not (billable and not debited and state is not None and state.status == 200):
        return
    if ATTRIBUTION is None or cycle is None or consumer is None or source is None:
        return
    body = bytes(state.body) if state.body is not None else b""
    try:
        cost = extract_total_nano_aiu(body, state.content_type)
        ATTRIBUTION.debit(cycle.id, consumer, source, cost, ts=_now())
        log.warning("[reconcile] partial-relay debit: cost=%s path=%s "
                    "(client/upstream dropped mid-stream)", cost, path)
    except Exception as exc:
        log.error("[!] partial-relay debit failed (logged, not surfaced): %s", exc)


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


def is_invalid_auto_mode_selector_401(status: int, body: bytes) -> bool:
    if status != 401:
        return False
    try:
        return contract.INVALID_AUTO_MODE_SELECTOR_BODY in body.decode("utf-8", errors="replace")
    except Exception:
        return False


def _patch_json_model_field(body: bytes, new_model: str) -> bytes:
    try:
        payload = json.loads(body)
    except Exception:
        return body
    if not isinstance(payload, dict) or "model" not in payload:
        return body
    if payload.get("model") == new_model:
        return body
    payload["model"] = new_model
    try:
        return json.dumps(payload).encode()
    except Exception:
        return body


async def _bootstrap_session_token(source, hdrs, auth) -> Optional[dict]:
    if source is None or _http is None:
        return None
    try:
        fwd = build_upstream_headers(
            hdrs, contract.BILLABLE_HOST, auth, len(contract.SESSION_BOOTSTRAP_BODY), source.pat)
        async with _http.request(
            "POST",
            f"https://{contract.BILLABLE_HOST}{contract.SESSION_BOOTSTRAP_PATH}",
            headers=fwd,
            data=contract.SESSION_BOOTSTRAP_BODY,
            ssl=upstream_ssl_context(),
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(sock_connect=10, sock_read=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if not isinstance(data, dict) or "session_token" not in data:
                return None
            return data
    except Exception:
        return None


def candidate_givers(engine, cycle_id, consumer) -> set:
    """The set of giver_ids whose live quota is worth pre-checking for this
    consumer: the consumer itself if it's a giver, plus every donor backing an
    active grant to it (pool fills arrive as grants too, so their givers are
    covered here)."""
    ids = set()
    if getattr(consumer, "is_giver", False):
        ids.add(consumer.user_id)
    for g in engine.active_grants(cycle_id, consumer.user_id):
        ids.add(g.donor_id)
    return ids


async def reconcile_candidate(engine, live_cache, cycle_id, giver_id):
    """Fetch a candidate giver's live quota, reconcile out-of-band drift into a
    BYPASS event, and return their live remaining (None if unknown). Best-effort:
    a reconcile failure never blocks routing or distorts the returned health."""
    v = await live_cache.get(giver_id) if live_cache is not None else None
    if v is None:
        return None
    try:
        # Hot path: stays debounced (two-observation confirm) + throttled so an
        # in-flight cost isn't double-booked as BYPASS and the loop isn't stalled.
        engine.reconcile_giver(cycle_id, giver_id, v, ts=_now())
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
            # Confirmed 402 (quota exhausted upstream): book the outstanding burn
            # immediately, no debounce — the giver really is spent.
            engine.reconcile_giver(cycle_id, giver_id,
                                   {"entitlement": int(ent), "remaining": 0},
                                   ts=_now(), immediate=True)
    except Exception as exc:
        log.warning("[failover] reconcile failed for %s: %s", giver_id, exc)
    if live_cache is not None:
        live_cache.set_exhausted(giver_id)


# ---------------------------------------------------------------------------
# HTTP request loop (runs after TLS is up)
# ---------------------------------------------------------------------------
async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 upstream_host: str, port: int = 443):
    upstream_ssl = upstream_ssl_context()

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

        try:
            body = await assemble_request_body(reader, hdrs, leftover)
        except RequestBodyError as exc:
            log.warning("[400] malformed request body: %s", exc)
            try:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n"
                             b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
            break

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
        if log.isEnabledFor(logging.DEBUG):
            # redact_headers masks the full sensitive-header set (authorization,
            # cookie/set-cookie, x-access-token, copilot-session-token) and scrubs
            # tokens from any other header value — not just authorization.
            for k, v in redact_headers(hdrs).items():
                log.debug("    %-30s %s", k + ":", v)
            if body:
                _log_block("REQUEST BODY",
                           redact_text(decode_body(body, "", hdrs.get("content-type", ""), LOG_BODY_CAP)))

        source = None
        consumer = None
        cycle = None  # set below for billable/session paths; kept defined so the
                      # relay except handlers can reference it unconditionally.
        pat_to_use = REAL_PAT
        billable = ATTRIBUTION is not None and is_billable(upstream_host, method, path)
        # /models/session resolves auto_mode -> a copilot-session-token bound to
        # whichever giver identity requested it. It isn't billable/metered, but
        # its giver pick has to be pinned so the client's next billable call
        # (matched by consumer + x-client-session-id) reuses the same giver —
        # otherwise upstream rejects the session token with
        # 401 "Invalid auto-mode selector" whenever the two picks diverge.
        session_bootstrap = (not billable and ATTRIBUTION is not None
                              and is_session_bootstrap(upstream_host, method, path))
        client_session_id = hdrs.get("x-client-session-id", "")
        pin_key = None
        health: Dict[str, Optional[int]] = {}
        if billable or session_bootstrap:
            # ensure_active_cycle also rolls a month-ended cycle over (archive +
            # open + seed) on first access. It is fully synchronous — no `await`
            # between its BEGIN IMMEDIATE and COMMIT — so it respects the no-await
            # invariant documented below for select_source/debit.
            cycle = ATTRIBUTION.engine.ensure_active_cycle(_now())
            consumer = ATTRIBUTION.resolve_consumer(strip_bearer(auth)) if cycle else None
            if consumer and client_session_id:
                pin_key = (consumer.user_id, client_session_id)
            # Live-quota health gate: pre-fetch each candidate giver's real GitHub
            # premium_interactions.remaining so select_source can skip a giver that
            # is already dead at the source. This awaits BEFORE select_source, so
            # the no-await-inside-transaction invariant below still holds.
            if cycle and consumer and LIVE_QUOTA is not None:
                for gid in candidate_givers(ATTRIBUTION.engine, cycle.id, consumer):
                    health[gid] = await reconcile_candidate(
                        ATTRIBUTION.engine, LIVE_QUOTA, cycle.id, gid)
        if billable:
            # Reuse the giver pinned by this client's /models/session bootstrap
            # call (same consumer + x-client-session-id), if any is still valid,
            # instead of letting select_source()'s independent dynamic pick land
            # on a different giver. Falls back to normal selection when there's
            # no pin (client skipped auto-mode / pinned a specific model) or the
            # pinned giver has expired/gone dead.
            source = (ATTRIBUTION.pinned_source(pin_key, cycle_id=cycle.id, health=health)
                      if pin_key else None)
            if source is None:
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
        elif session_bootstrap and cycle and consumer:
            # Same selection path as billable calls (not any_giver_pat()'s static
            # first-in-list pick) so the giver chosen here is the one we can
            # meaningfully pin. No credit is consumed — this call isn't metered.
            # If nothing is eligible (e.g. pool exhausted), leave pat_to_use as-is
            # so the non-billable fallback below borrows any giver PAT; the
            # actual billable call afterward will 402-block on its own merits.
            source = ATTRIBUTION.select_source(cycle.id, consumer, health=health)
            if source is not None:
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
        relay_state = RelayState()
        debited = False
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
                        _write_buffered(writer, resp, peek, state=relay_state)
                        await writer.drain()
                        _status = resp.status
                        _ct = resp.headers.get("Content-Type", "")
                        break
                    if (billable and source is not None and attempts < max_attempts
                            and resp.status == 401
                            and hdrs.get(contract.COPILOT_SESSION_TOKEN_HEADER, "")):
                        # Same retry pattern as the 402 failover above, but for the
                        # auto-mode session token being bound to the wrong giver.
                        peek = await resp.read()
                        if is_invalid_auto_mode_selector_401(resp.status, peek):
                            exclude.add(source.grant_id or source.giver_id)
                            nxt = ATTRIBUTION.select_source(
                                cycle.id, consumer, health=health, exclude=frozenset(exclude))
                            if nxt is not None:
                                healed = await _bootstrap_session_token(nxt, hdrs, auth)
                                if healed is not None:
                                    new_token = healed["session_token"]
                                    selected_model = healed.get("selected_model")
                                    expires_at = healed.get("expires_at")
                                    # Mutate hdrs (not fwd): fwd is rebuilt from hdrs at
                                    # the top of the next loop iteration via
                                    # build_upstream_headers(), so patching fwd here
                                    # would be silently discarded on retry.
                                    hdrs[contract.COPILOT_SESSION_TOKEN_HEADER] = new_token
                                    if isinstance(selected_model, str):
                                        current_model = None
                                        model_present = False
                                        try:
                                            parsed_body = json.loads(body or b"{}")
                                            if isinstance(parsed_body, dict) and "model" in parsed_body:
                                                model_present = True
                                                current_model = parsed_body.get("model")
                                        except Exception:
                                            model_present = False
                                        if model_present and current_model != selected_model:
                                            log.warning("[failover] model changed %s -> %s; retry via %s",
                                                        current_model, selected_model, nxt.giver_id)
                                            patched_body = _patch_json_model_field(body, selected_model)
                                            if patched_body != body:
                                                body = patched_body
                                                fwd["content-length"] = str(len(body))
                                    if pin_key:
                                        try:
                                            ATTRIBUTION.pin_source(pin_key, nxt, expires_at)
                                        except Exception as exc:
                                            log.warning("[!] failed to pin healed giver from /models/session response: %s", exc)
                                    source = nxt
                                    continue
                        _write_buffered(writer, resp, peek, state=relay_state)
                        await writer.drain()
                        _status = resp.status
                        _ct = resp.headers.get("Content-Type", "")
                        break
                    full_body = await _relay_response(writer, resp, upstream_host, path, method,
                                                      hdrs, capture_full=(billable or session_bootstrap),
                                                      state=relay_state)
                    _status = resp.status
                    _ct = resp.headers.get("Content-Type", "")
                if billable and _status == 200:
                    if not full_body:
                        log.warning("[!] billable 200 had empty/None body; debiting 0 path=%s", path)
                    _safe_sentinel_emit(sentinel.check_billable_response, _status, full_body or b"", _ct, path.split("?", 1)[0])
                    cost = extract_total_nano_aiu(full_body or b"", _ct)
                    try:
                        ATTRIBUTION.debit(cycle.id, consumer, source, cost, ts=_now())
                        debited = True
                    except Exception as exc:  # debit must never break the sent response
                        log.error("[!] debit failed (logged, not surfaced): %s", exc)
                if session_bootstrap and _status == 200 and source is not None and pin_key is not None:
                    # Pin the giver we bootstrapped auto-mode with so the client's
                    # next billable call (matched by consumer + x-client-session-id)
                    # reuses the same identity as the copilot-session-token we just
                    # got back — avoiding the 401 "Invalid auto-mode selector" that
                    # follows a mismatched giver pick.
                    try:
                        data = json.loads(full_body or b"{}")
                        ATTRIBUTION.pin_source(pin_key, source, data.get("expires_at"))
                    except Exception as exc:
                        log.warning("[!] failed to pin giver from /models/session response: %s", exc)
                if is_billable(upstream_host, method, path) and _status in (400, 401, 403):
                    _safe_sentinel_emit(sentinel.check_billable_rejection, _status, path.split("?", 1)[0])
                break
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            log.error("[!] Upstream timeout: %s %s", method, path)
            _reconcile_partial_relay(billable, debited, relay_state, cycle, consumer, source, path)
            _fail_client(writer, relay_state,
                         b"HTTP/1.1 504 Gateway Timeout\r\nContent-Length: 0\r\n\r\n")
            break
        except Exception as exc:
            # Client disconnect (writer.drain raising) or upstream death mid-relay
            # both land here. If the head is already sent we must NOT inject a
            # status line into the open (chunked) body — abort the socket instead
            # (_fail_client). And a billable stream that dropped mid-flight still
            # burned the giver's quota upstream, so best-effort debit it now
            # (_reconcile_partial_relay) rather than leaking it into a later BYPASS.
            log.error("[!] Forward error: %s", exc)
            _reconcile_partial_relay(billable, debited, relay_state, cycle, consumer, source, path)
            _fail_client(writer, relay_state,
                         b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
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

            # Optimistic-TLS clients pipeline the TLS ClientHello immediately
            # after the CONNECT head. We can't feed these pre-read bytes into
            # loop.start_tls (it reads straight from the transport), so they are
            # dropped — such a client will stall until it retries. The Copilot
            # CLI waits for our 200 before starting TLS, so this doesn't affect
            # it; documented limitation (audit P3).
            _, _, connect_leftover = raw.partition(b"\r\n\r\n")
            if connect_leftover:
                log.warning("[CONNECT]   %d byte(s) after CONNECT head dropped "
                            "(optimistic-TLS client unsupported)", len(connect_leftover))

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

            # Open-relay/SSRF guard, mirroring the CONNECT branch: a non-CONNECT
            # proxy request forwards to https://{host}{path}, so without this an
            # arbitrary Host: header would turn the proxy into an open forward
            # proxy (and, in legacy single-PAT mode, leak REAL_PAT to any
            # attacker-chosen GHE-shaped host). Refuse anything outside the
            # allowlist when CTC_RESTRICT_CONNECT is on.
            if RESTRICT_CONNECT and not connect_allowed(host):
                log.warning("[HTTP]      REJECTED (restricted) %s → %s", peer, host)
                writer.write(b"HTTP/1.1 403 Forbidden\r\nProxy-Agent: copilot-proxy\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return

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
    # Build the shared upstream SSLContext once, up front, so the first request
    # doesn't pay the CA-parse cost on the loop and every request reuses the
    # same context (aiohttp pools connections keyed by SSLContext identity).
    upstream_ssl_context()
    if UPSTREAM_INSECURE:
        log.warning("UPSTREAM_INSECURE=1 — upstream GHE certificate will NOT be verified")
    elif _insecure_requested(os.environ):
        log.error("UPSTREAM_INSECURE is set but UPSTREAM_INSECURE_CONFIRM is not — "
                  "refusing to disable upstream TLS verification (keeping it ON). "
                  "Set UPSTREAM_INSECURE_CONFIRM=1 to confirm you accept the "
                  "on-path PAT-exposure risk.")

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
        close_captures()
        if _http and not _http.closed:
            asyncio.run(_http.close())
