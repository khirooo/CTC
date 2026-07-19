# Web image: build the static SPA, then serve it (plus the CLI files) with Caddy.
#
# All host-specific values are baked in AT BUILD TIME from CTC_DOMAIN (a hostname
# or a raw IP). docker-compose passes them from .env:
#   VITE_API_BASE  = https://<CTC_DOMAIN>/api   (the SPA's control-plane base)
#   VITE_CTC_HOST  = <CTC_DOMAIN>               (host in the CLI install one-liner)
#   VITE_PROXY_HOST= <CTC_DOMAIN>:8080          (proxy host shown in "Set up CLI")
#   VITE_GHE_HOST  = https://<GHE_DOMAIN>       (token-creation link in the PAT help)
#   CTC_DOMAIN     = <CTC_DOMAIN>               (baked into the served ctc/install.sh)

# ---- stage 1: build the static site ----
FROM node:20-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
ARG VITE_API_BASE
ARG VITE_CTC_HOST
ARG VITE_PROXY_HOST
ARG VITE_GHE_HOST
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_CTC_HOST=${VITE_CTC_HOST}
ENV VITE_PROXY_HOST=${VITE_PROXY_HOST}
ENV VITE_GHE_HOST=${VITE_GHE_HOST}
RUN npm run build      # -> /web/dist

# ---- stage 1b: build the VS Code extension into a .vsix ----
# Dir layout mirrors the repo so the extension's copy-shim (../../tools/…) resolves.
FROM node:20-slim AS extbuild
WORKDIR /work/ide/ctc-vscode
COPY ide/ctc-vscode/package.json ide/ctc-vscode/package-lock.json* ./
RUN npm ci || npm install
COPY ide/ctc-vscode/ ./
COPY tools/ctc_ide_shim.py /work/tools/ctc_ide_shim.py
RUN npx @vscode/vsce package --allow-missing-repository --skip-license -o /ctc-copilot.vsix

# ---- stage 2: Caddy serving dist + CLI assets ----
FROM caddy:2-alpine
# The built SPA.
COPY --from=build /web/dist /srv/www
# CLI launcher assets, served so `curl https://<host>/install.sh | sh` and the
# launcher's `ctc login` cert download work.
COPY cli/install.sh /srv/www/install.sh
COPY cli/install-vscode.sh /srv/www/install-vscode.sh
COPY cli/ctc /srv/www/ctc
# The VS Code identity shim, downloaded by `ctc ide` on first use.
COPY tools/ctc_ide_shim.py /srv/www/ctc_ide_shim.py
# The packaged VS Code extension, installed by install-vscode.sh.
COPY --from=extbuild /ctc-copilot.vsix /srv/www/ctc-copilot.vsix
# Bake the deployment hosts into the served launcher scripts. Their in-repo
# defaults are placeholders: `ctc.local` (the CTC host) and `example.ghe.com`
# (the GitHub Enterprise host `ctc login` writes as GH_HOST). Without the
# GHE_DOMAIN rewrite, the launched Copilot points at the wrong GHE host and the
# proxy blind-tunnels it → "fetch failed". Teammates can still override at
# runtime with CTC_HOST=… / GHE_DOMAIN=….
ARG CTC_DOMAIN
ARG GHE_DOMAIN
# The web transport (http|https). The served launcher scripts default to https;
# rewrite that default so the install one-liner and `ctc login` cert download use
# the same scheme Caddy actually serves (http-mode would otherwise hit :443).
ARG CTC_WEB_SCHEME
# Public proxy port the launcher points HTTPS_PROXY at (default 8080). Baked so a
# custom/forwarded proxy port reaches teammates without them setting it by hand.
ARG CTC_PROXY_PUBLIC_PORT
# Host the launcher reaches the proxy at, when it differs from the web host (e.g.
# public website, VPN-only proxy). Empty → launcher falls back to CTC_HOST.
ARG CTC_PROXY_HOST
RUN if [ -n "$CTC_DOMAIN" ]; then \
      sed -i "s/ctc\.local/$CTC_DOMAIN/g" /srv/www/install.sh /srv/www/install-vscode.sh /srv/www/ctc; \
    fi; \
    if [ -n "$GHE_DOMAIN" ]; then \
      sed -i "s/example\.ghe\.com/$GHE_DOMAIN/g" /srv/www/ctc; \
    fi; \
    if [ -n "$CTC_WEB_SCHEME" ]; then \
      sed -i "s/CTC_SCHEME:-https/CTC_SCHEME:-$CTC_WEB_SCHEME/g" /srv/www/install.sh /srv/www/install-vscode.sh /srv/www/ctc; \
    fi; \
    if [ -n "$CTC_PROXY_PUBLIC_PORT" ]; then \
      sed -i "s/CTC_PROXY_PORT:-8080/CTC_PROXY_PORT:-$CTC_PROXY_PUBLIC_PORT/g" /srv/www/ctc; \
    fi; \
    if [ -n "$CTC_PROXY_HOST" ]; then \
      sed -i "s/CTC_PROXY_HOST:-\$CTC_HOST/CTC_PROXY_HOST:-$CTC_PROXY_HOST/g" /srv/www/ctc; \
    fi
# Routing / TLS config.
COPY Caddyfile /etc/caddy/Caddyfile
