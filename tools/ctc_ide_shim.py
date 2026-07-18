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


def _resolve_config() -> tuple[str, str, int, int]:
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
    return token, host, port, listen_port


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


def _make_handler(token: str, up_host: str, up_port: int):
    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
        try:
            raw = await _read_head(client_reader)
            if raw is None:
                client_writer.close()
                return

            first = raw.split(b"\r\n", 1)[0].decode(errors="replace").strip()
            is_connect = first.upper().startswith("CONNECT ")
            rewritten, leftover = inject_proxy_auth(raw, token)

            try:
                up_reader, up_writer = await asyncio.open_connection(up_host, up_port)
            except Exception:
                try:
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    await client_writer.drain()
                except Exception:
                    pass
                client_writer.close()
                return

            # CONNECT: send only the rewritten head — the client waits for the
            # central proxy's 200 before sending its TLS ClientHello, so there is
            # no legitimate leftover to forward (matches the central proxy's
            # optimistic-TLS handling). Plain-HTTP: forward the body bytes too.
            up_writer.write(rewritten if is_connect else rewritten + leftover)
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


async def _main() -> None:
    token, up_host, up_port, listen_port = _resolve_config()
    if not token:
        print("ctc-ide-shim: no CTC token. Set CTC_TOKEN or run `ctc login` first.",
              file=sys.stderr)
        sys.exit(2)
    if not up_host:
        print("ctc-ide-shim: no central proxy host. Set CTC_PROXY_HOST/CTC_PROXY_PORT "
              "or ensure HTTPS_PROXY is set (run `ctc login`).", file=sys.stderr)
        sys.exit(2)

    server = await asyncio.start_server(
        _make_handler(token, up_host, up_port), LISTEN_HOST, listen_port)
    print(f"ctc-ide-shim: listening on http://{LISTEN_HOST}:{listen_port} "
          f"→ {up_host}:{up_port} (identity injected). Ctrl-C to stop.",
          file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
