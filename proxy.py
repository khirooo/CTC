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
from datetime import datetime, timezone
from typing import Optional, Dict
import aiohttp
from ctc.metering.capture import record_exchange
from ctc.metering.extract import extract_total_nano_aiu
from ctc import contract
from ctc import sentinel
from ctc.routing.mock_exchange import build_token_response

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CERT_FILE         = os.environ.get("CERT_FILE", "cert.pem")
KEY_FILE          = os.environ.get("KEY_FILE",  "key.pem")
REAL_GHE_HOST     = os.environ.get("REAL_GHE_HOST", f"api.{contract.GHE_DOMAIN}")
REAL_PAT          = os.environ.get("REAL_PAT", "")
LISTEN_PORT       = int(os.environ.get("PORT", "8080"))
ATTRIBUTION = None  # set by _build_attribution() at startup; None => legacy single-PAT mode


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
        from ctc.accounting.engine import AccountingEngine
        from ctc.auth.crypto import derive_key
        from ctc.auth.registry import AuthRegistry
        from ctc.routing.attribution import AttributionService
        from ctc.store.auth_store import AuthStore
        from ctc.store.accounting_store import AccountingStore
        from ctc.store.db import connect, init_db
        conn = connect(db_path)
        init_db(conn)
        store = AuthStore(conn)
        registry = AuthRegistry(store, derive_key(secret))  # implements IdentityProvider + PatRegistry
        engine = AccountingEngine(AccountingStore(conn))
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
    from ctc.accounting.engine import AccountingEngine
    from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
    from ctc.routing.attribution import AttributionService
    from ctc.store.accounting_store import AccountingStore
    from ctc.store.db import connect

    idmap = {tok: ConsumerIdentity(v["user_id"], bool(v["is_giver"]))
             for tok, v in _json.loads(ident).items()}
    engine = AccountingEngine(AccountingStore(connect(db_path)))
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
    for p in ("Bearer ", "bearer ", "token ", "Token "):
        if auth.startswith(p):
            auth = auth[len(p):]
            break
    return auth.strip()[:12] or "(no-token)"

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


def is_token_exchange(upstream_host: str, method: str, path: str) -> bool:
    """The VS Code Copilot extension's mandatory token exchange. The CLI never
    calls it; the endpoint accepts no PAT, so we answer it locally."""
    return (should_swap(upstream_host)
            and method.upper() == "GET"
            and path.split("?", 1)[0] == contract.TOKEN_EXCHANGE_PATH)


def _mock_token_exchange_response() -> bytes:
    payload = json.dumps(build_token_response(int(time.time()))).encode()
    head = (f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: keep-alive\r\n\r\n").encode()
    return head + payload


def apply_copilot_api_identity(fwd: dict, upstream_host: str) -> dict:
    """On copilot-api, rewrite the client-identity headers to the CLI's
    allowlisted values so the swapped PAT is accepted (copilot-api rejects the
    PAT for the extension's copilot-integration-id: vscode-chat). No-op on other
    hosts and a no-op for the CLI (it already sends these values). Mutates+returns
    fwd."""
    if upstream_host == contract.BILLABLE_HOST:
        fwd.update(contract.COPILOT_API_IDENTITY_HEADERS)
    return fwd


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

        # Mock the IDE token exchange: answer locally, never forward (the endpoint
        # rejects every PAT). The extension replays this token to copilot-api.*,
        # where we swap ALL auth to the PAT — so it only needs to be replayable.
        if is_token_exchange(upstream_host, method, path):
            log.info("[→ MOCK]    session=%-12s GET %s (fabricated token exchange)",
                     session, path)
            writer.write(_mock_token_exchange_response())
            await writer.drain()
            continue

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
            _log_block("REQUEST BODY", decode_body(body, "", hdrs.get("content-type", "")))

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
            source = ATTRIBUTION.select_source(cycle.id, consumer) if (cycle and consumer) else None
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
        # receive a giver PAT.
        if not pat_to_use and ATTRIBUTION is not None and should_swap(upstream_host):
            pat_to_use = ATTRIBUTION.any_giver_pat() or pat_to_use

        fwd = build_upstream_headers(hdrs, upstream_host, auth, len(body), pat_to_use)
        fwd = apply_copilot_api_identity(fwd, upstream_host)

        _status = 0
        _ct = ""
        try:
            async with _http.request(
                method   = method,
                url      = f"https://{upstream_host}{path}",
                headers  = fwd,
                data     = body or None,
                ssl      = upstream_ssl,
                allow_redirects = False,
                timeout  = aiohttp.ClientTimeout(sock_connect=10, sock_read=120),
            ) as resp:
                full_body = await _relay_response(writer, resp, upstream_host, path, method, hdrs,
                                                  capture_full=billable)
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
