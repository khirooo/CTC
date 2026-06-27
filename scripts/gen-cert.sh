#!/usr/bin/env sh
# Generate the proxy's self-signed MITM cert (cert.pem + key.pem).
#
# The SANs MUST cover every host the proxy decrypts (ctc/contract.py
# EXPECTED_MITM_HOSTS) — adding a MITM host without a matching SAN breaks its
# TLS handshake. Clients trust this cert via `ctc login` (it's served at
# /ctc-ca.pem). Regenerating it means every client must re-trust, so do it once.
#
# Usage: gen-cert.sh [OUT_DIR]   (default: current directory)
set -eu

OUT_DIR="${1:-.}"
mkdir -p "$OUT_DIR"

# Your GitHub Enterprise domain — must match the proxy's GHE_DOMAIN so the SANs
# cover the hosts the proxy decrypts. Defaults to the neutral placeholder.
GHE_DOMAIN="${GHE_DOMAIN:-example.ghe.com}"

# The dashboard host. The same cert fronts the website via Caddy, so trusting it
# once (ctc login) also clears the browser warning. Defaults to localhost.
CTC_DOMAIN="${CTC_DOMAIN:-localhost}"

# CTC_DOMAIN may be a hostname OR a raw IP. Browsers match an IP literal only
# against IP: (iPAddress) SANs, never DNS: ones — so emit the SAN type that fits,
# else HTTPS to a raw-IP CTC_DOMAIN fails (cert "not valid for this address").
case "$CTC_DOMAIN" in
  *[!0-9.]*) CTC_DOMAIN_SAN="DNS:${CTC_DOMAIN}" ;;  # any non-digit/dot char → hostname
  *.*.*.*)   CTC_DOMAIN_SAN="IP:${CTC_DOMAIN}" ;;    # dotted all-numeric → IPv4 address
  *)         CTC_DOMAIN_SAN="DNS:${CTC_DOMAIN}" ;;
esac

if [ -f "$OUT_DIR/cert.pem" ] && [ -f "$OUT_DIR/key.pem" ]; then
  echo "cert.pem/key.pem already exist in $OUT_DIR — leaving them in place."
  echo "(delete them first if you really want to regenerate; clients will need to re-trust.)"
  # Still normalize the key perms: the proxy reads it as a non-root user, and an
  # earlier run (or older script) may have left it 0600. Idempotent + safe.
  chmod 644 "$OUT_DIR/key.pem"
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -keyout "$OUT_DIR/key.pem" -out "$OUT_DIR/cert.pem" \
  -days 365 -nodes -subj "/CN=copilot-proxy-ca" \
  -addext "subjectAltName=DNS:localhost,${CTC_DOMAIN_SAN},DNS:api.${GHE_DOMAIN},DNS:${GHE_DOMAIN},DNS:copilot-api.${GHE_DOMAIN},DNS:api.github.com,DNS:github.com,DNS:api.githubcopilot.com,DNS:githubcopilot.com,DNS:api.localhost,IP:127.0.0.1"

# gencert runs as root but the proxy reads /certs read-only as a non-root user;
# openssl writes the key 0600, so make it readable by the proxy. This is a
# self-signed MITM key living only inside the internal certs volume.
chmod 644 "$OUT_DIR/key.pem"

echo "Wrote $OUT_DIR/cert.pem and $OUT_DIR/key.pem"
