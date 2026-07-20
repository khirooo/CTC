#!/usr/bin/env python3
"""CTC IDE shim — local CONNECT-forwarder for the VS Code Copilot extension.

The VS Code Copilot extension drops any credentials embedded in `http.proxy`
(http://<token>@host) on its own CONNECTs, so it can't identify the consumer to
the central CTC proxy. This shim is the reliable injection point: it runs on the
user's laptop as a plain HTTP forward-proxy, and for every request it forwards to
the central CTC proxy it stamps on a `Proxy-Authorization: Basic base64("ctc:<token>")`
header. The central proxy reads that to resolve the consumer, then does the TLS
MITM + PAT swap as usual. This shim never terminates TLS — it only pipes bytes.

Point VS Code at it:
  "http.proxy": "http://127.0.0.1:8899",
  "http.proxyStrictSSL": false,
  "http.proxySupport": "on"

Config (env overrides first, then ~/.config/ctc/env written by `ctc login`):
  CTC_TOKEN            the CTC proxy token (else COPILOT_GITHUB_TOKEN from env file)
  CTC_PROXY_HOST       central CTC proxy host (else parsed from HTTPS_PROXY)
  CTC_PROXY_PORT       central CTC proxy port (else parsed from HTTPS_PROXY, default 8080)
  CTC_IDE_LISTEN_PORT  local listen port (default 8899)

Usage:
  CTC_TOKEN=github_pat_... CTC_PROXY_HOST=ctc.local CTC_PROXY_PORT=8080 \
  python3 tools/ctc_ide_shim.py
  # or just `ctc ide`, which sources ~/.config/ctc/env and runs this.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
from pathlib import Path

LISTEN_HOST = "127.0.0.1"
_HEAD_CAP = 64 * 1024


def _load_env_file() -> dict[str, str]:
    """Parse the shell env file `ctc login` writes (`export KEY="val"` lines).
    Best-effort: returns {} if absent/unreadable. Only the keys we need."""
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = Path(cfg) / "ctc" / "env"
    out: dict[str, str] = {}
    try:
        text = path.read_text()
    except Exception:
        return out
    for m in re.finditer(r'^\s*export\s+([A-Z_]+)="?([^"\n]*)"?\s*$', text, re.MULTILINE):
        out[m.group(1)] = m.group(2)
    return out


def _resolve_config() -> tuple[str, str, int, int, str]:
    env_file = _load_env_file()
    token = os.environ.get("CTC_TOKEN") or env_file.get("COPILOT_GITHUB_TOKEN", "")

    host = os.environ.get("CTC_PROXY_HOST", "")
    port_s = os.environ.get("CTC_PROXY_PORT", "")
    if not host or not port_s:
        # Fall back to HTTPS_PROXY (http://host:port) from the env file / environment.
        https_proxy = os.environ.get("HTTPS_PROXY") or env_file.get("HTTPS_PROXY", "")
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", https_proxy)
        if m:
            host = host or m.group(1)
            port_s = port_s or (m.group(2) or "8080")
    port = int(port_s or "8080")
    listen_port = int(os.environ.get("CTC_IDE_LISTEN_PORT", "8899"))
    # Only *.GHE_DOMAIN traffic is routed through CTC; everything else the shim
    # tunnels directly (so the central proxy only ever sees Copilot/GHE calls).
    # Empty domain => route ALL traffic to CTC (back-compat default).
    ghe_domain = (os.environ.get("CTC_GHE_DOMAIN")
                  or env_file.get("GH_HOST", "")).strip().lower()
    return token, host, port, listen_port, ghe_domain


def should_route_to_ctc(host: str, ghe_domain: str) -> bool:
    """True if `host` should be tunneled through the central CTC proxy. An empty
    ghe_domain routes everything (back-compat). Otherwise only the GHE domain and
    its sub-hosts (api., copilot-api., …) go to CTC; all else is tunneled direct."""
    if not ghe_domain:
        return True
    h = host.strip().lower()
    return h == ghe_domain or h.endswith("." + ghe_domain)


def _target_host_port(first_line: str, raw: bytes) -> tuple[str, int]:
    """Best-effort (host, port) for the request. CONNECT carries host:port on the
    request line; plain-HTTP falls back to the Host header (default port 80)."""
    parts = first_line.split()
    if len(parts) >= 2 and parts[0].upper() == "CONNECT":
        tgt = parts[1]
        h, _, p = tgt.rpartition(":")
        if h:
            try:
                return h, int(p)
            except ValueError:
                return tgt, 443
        return tgt, 443
    # plain-HTTP: read the Host header from the raw head
    for line in raw.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        if line.lower().startswith(b"host:"):
            hv = line.partition(b":")[2].strip().decode(errors="replace")
            h, _, p = hv.rpartition(":")
            if h and p.isdigit():
                return h, int(p)
            return hv, 80
    return "", 80


def _to_origin_form(raw: bytes) -> bytes:
    """Rewrite an absolute-form request line (`GET http://host/p HTTP/1.1`) to
    origin-form (`GET /p HTTP/1.1`) for direct forwarding to an origin server."""
    head, sep, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    parts = lines[0].split(b" ", 2)
    if len(parts) == 3 and b"://" in parts[1]:
        after = parts[1].split(b"://", 1)[1]
        path = b"/" + after.partition(b"/")[2]
        lines[0] = parts[0] + b" " + path + b" " + parts[2]
    return b"\r\n".join(lines) + sep + rest


def inject_proxy_auth(raw: bytes, token: str) -> tuple[bytes, bytes]:
    """Return (rewritten_head, leftover_body). Strips any client-supplied
    proxy-authorization / proxy-connection, appends our
    `Proxy-Authorization: Basic base64("ctc:<token>")`. The request line and all
    other headers are preserved verbatim."""
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    request_line, header_lines = lines[0], lines[1:]
    kept = [
        ln for ln in header_lines
        if ln and not ln.lower().startswith(b"proxy-authorization:")
        and not ln.lower().startswith(b"proxy-connection:")
    ]
    cred = base64.b64encode(f"ctc:{token}".encode()).decode()
    kept.append(b"Proxy-Authorization: Basic " + cred.encode())
    rewritten = b"\r\n".join([request_line] + kept) + b"\r\n\r\n"
    return rewritten, rest


async def _read_head(reader: asyncio.StreamReader) -> bytes | None:
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=30)
            if not chunk:
                return None
            buf += chunk
            if len(buf) > _HEAD_CAP:
                return None
    except Exception:
        return None
    return buf


async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
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


async def _tunnel_502(client_writer: asyncio.StreamWriter) -> None:
    try:
        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await client_writer.drain()
    except Exception:
        pass
    try:
        client_writer.close()
    except Exception:
        pass


def _make_handler(token: str, up_host: str, up_port: int, ghe_domain: str = ""):
    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
        try:
            raw = await _read_head(client_reader)
            if raw is None:
                client_writer.close()
                return

            first = raw.split(b"\r\n", 1)[0].decode(errors="replace").strip()
            is_connect = first.upper().startswith("CONNECT ")
            host, port = _target_host_port(first, raw)

            if should_route_to_ctc(host, ghe_domain):
                # Copilot/GHE → central CTC proxy, with our identity injected. The
                # proxy answers the CONNECT 200 and does the TLS MITM + PAT swap.
                rewritten, leftover = inject_proxy_auth(raw, token)
                try:
                    up_reader, up_writer = await asyncio.open_connection(up_host, up_port)
                except Exception:
                    await _tunnel_502(client_writer)
                    return
                # CONNECT: send only the rewritten head (client waits for the 200
                # before its ClientHello). Plain-HTTP: forward the body bytes too.
                up_writer.write(rewritten if is_connect else rewritten + leftover)
                await up_writer.drain()
            else:
                # Everything else → straight to the origin; never touches CTC.
                try:
                    up_reader, up_writer = await asyncio.open_connection(host, port)
                except Exception:
                    await _tunnel_502(client_writer)
                    return
                if is_connect:
                    client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    await client_writer.drain()
                else:
                    up_writer.write(_to_origin_form(raw))
                    await up_writer.drain()

            await asyncio.gather(
                _pipe(client_reader, up_writer),
                _pipe(up_reader, client_writer),
            )
        except Exception:
            try:
                client_writer.close()
            except Exception:
                pass

    return handle


async def _parent_death_watchdog() -> None:
    """Exit when our launching process (the VS Code extension host) goes away, so
    the shim never lingers as an orphan holding the listen port — otherwise the
    next VS Code launch can't bind and the extension shows an error. On POSIX a
    reparented process reports getppid()==1."""
    start_ppid = os.getppid()
    while True:
        await asyncio.sleep(2)
        ppid = os.getppid()
        if ppid == 1 or ppid != start_ppid:
            os._exit(0)


async def _main() -> None:
    token, up_host, up_port, listen_port, ghe_domain = _resolve_config()
    if not token:
        print("ctc-ide-shim: no CTC token. Set CTC_TOKEN or run `ctc login` first.",
              file=sys.stderr)
        sys.exit(2)
    if not up_host:
        print("ctc-ide-shim: no central proxy host. Set CTC_PROXY_HOST/CTC_PROXY_PORT "
              "or ensure HTTPS_PROXY is set (run `ctc login`).", file=sys.stderr)
        sys.exit(2)

    try:
        server = await asyncio.start_server(
            _make_handler(token, up_host, up_port, ghe_domain), LISTEN_HOST, listen_port)
    except OSError as exc:
        # Port already held (likely a stale shim). Exit non-zero; the extension
        # surfaces it, and the watchdog on the stale one will soon free the port.
        print(f"ctc-ide-shim: cannot bind {LISTEN_HOST}:{listen_port} ({exc}). "
              "Another shim may still be running.", file=sys.stderr)
        sys.exit(3)

    asyncio.ensure_future(_parent_death_watchdog())
    route = f"only *.{ghe_domain} → CTC; else direct" if ghe_domain else "all → CTC"
    print(f"ctc-ide-shim: listening on http://{LISTEN_HOST}:{listen_port} "
          f"→ {up_host}:{up_port} ({route}). Ctrl-C to stop.",
          file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
