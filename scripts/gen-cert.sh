#!/usr/bin/env sh
# Generate the proxy's MITM certificates: a CA (cert.pem + key.pem) and the
# server certificate the proxy/Caddy actually present (leaf.pem + leafkey.pem,
# chained in leafchain.pem).
#
# Why two certs and not one: a certificate with basicConstraints CA:TRUE may not
# be used as an end-entity (server) certificate. OpenSSL tolerated it, so CTC
# served its CA directly for a long time — but Copilot CLI >= 1.0.82 does its
# HTTPS in Rust (reqwest/rustls + rustls-webpki), which enforces the rule and
# rejects the handshake with CaUsedAsEndEntity -> a `certificate_unknown` alert.
# Clients keep trusting the CA (cert.pem) exactly as before; only what the proxy
# presents on the wire changes, so no client has to re-trust anything.
#
# The SANs MUST cover every host the proxy decrypts (ctc/contract.py
# EXPECTED_MITM_HOSTS) plus CTC_DOMAIN for the dashboard — adding a MITM host
# without a matching SAN breaks its TLS handshake. Clients trust the CA via
# `ctc login` (it's served at /ctc-ca.pem). Regenerating the CA means every
# client must re-trust, so do it once; the leaf can be reissued freely.
#
# Usage: gen-cert.sh [OUT_DIR]   (default: current directory)
set -eu

OUT_DIR="${1:-.}"
mkdir -p "$OUT_DIR"

# Your GitHub Enterprise domain — must match the proxy's GHE_DOMAIN so the SANs
# cover the hosts the proxy decrypts. Defaults to the neutral placeholder.
GHE_DOMAIN="${GHE_DOMAIN:-example.ghe.com}"

# The dashboard host. The same cert fronts the website via Caddy, so trusting the
# CA once (ctc login) also clears the browser warning. Defaults to localhost.
CTC_DOMAIN="${CTC_DOMAIN:-localhost}"

# CTC_DOMAIN may be a hostname OR a raw IP. Browsers match an IP literal only
# against IP: (iPAddress) SANs, never DNS: ones — so emit the SAN type that fits,
# else HTTPS to a raw-IP CTC_DOMAIN fails (cert "not valid for this address").
case "$CTC_DOMAIN" in
  *[!0-9.]*) CTC_DOMAIN_SAN="DNS:${CTC_DOMAIN}" ;;  # any non-digit/dot char → hostname
  *.*.*.*)   CTC_DOMAIN_SAN="IP:${CTC_DOMAIN}" ;;    # dotted all-numeric → IPv4 address
  *)         CTC_DOMAIN_SAN="DNS:${CTC_DOMAIN}" ;;
esac

# One SAN list, shared by the CA and the leaf, so the two can never drift.
SANS="DNS:localhost,${CTC_DOMAIN_SAN},DNS:api.${GHE_DOMAIN},DNS:${GHE_DOMAIN},DNS:copilot-api.${GHE_DOMAIN},DNS:api.github.com,DNS:github.com,DNS:api.githubcopilot.com,DNS:githubcopilot.com,DNS:api.localhost,IP:127.0.0.1"

# ---------------------------------------------------------------------------
# 1. The CA. Long-lived and trusted by every client — never regenerate in place.
# ---------------------------------------------------------------------------
if [ -f "$OUT_DIR/cert.pem" ] && [ -f "$OUT_DIR/key.pem" ]; then
  echo "cert.pem/key.pem (CA) already exist in $OUT_DIR — leaving them in place."
  echo "(delete them first if you really want to regenerate; clients will need to re-trust.)"
else
  openssl req -x509 -newkey rsa:2048 -keyout "$OUT_DIR/key.pem" -out "$OUT_DIR/cert.pem" \
    -days 3650 -nodes -subj "/CN=copilot-proxy-ca" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectAltName=${SANS}"
  echo "Wrote $OUT_DIR/cert.pem and $OUT_DIR/key.pem (CA)"
fi

# gencert runs as root but the proxy reads /certs read-only as a non-root user;
# openssl writes keys 0600, so make them readable by the proxy. These are
# self-signed MITM keys living only inside the internal certs volume.
chmod 644 "$OUT_DIR/key.pem"

# ---------------------------------------------------------------------------
# 2. The leaf the proxy and Caddy present. Signed by the CA above, so an existing
#    deployment gets one without touching the CA clients already trust.
#    Reissued whenever it is missing or its SANs no longer match this config
#    (e.g. GHE_DOMAIN/CTC_DOMAIN changed) — safe, since nothing trusts the leaf
#    directly.
# ---------------------------------------------------------------------------
leaf_is_current() {
  [ -f "$OUT_DIR/leaf.pem" ] && [ -f "$OUT_DIR/leafkey.pem" ] && [ -f "$OUT_DIR/leafchain.pem" ] || return 1
  # Still signed by the CA in place, and not expiring within 30 days?
  openssl verify -CAfile "$OUT_DIR/cert.pem" "$OUT_DIR/leaf.pem" >/dev/null 2>&1 || return 1
  openssl x509 -in "$OUT_DIR/leaf.pem" -noout -checkend 2592000 >/dev/null 2>&1 || return 1
  # Same SAN set we would issue today? Compare the normalized SAN line.
  want="$(printf '%s' "$SANS" | tr -d ' ' | tr ',' '\n' | sed -e 's/^DNS://' -e 's/^IP:/IP Address:/' | sort)"
  have="$(openssl x509 -in "$OUT_DIR/leaf.pem" -noout -ext subjectAltName 2>/dev/null \
            | tail -n +2 | tr -d ' ' | tr ',' '\n' | sed -e 's/^DNS://' -e 's/^IPAddress:/IP Address:/' | sort)"
  [ "$want" = "$have" ]
}

if leaf_is_current; then
  echo "leaf.pem/leafkey.pem already current in $OUT_DIR — leaving them in place."
else
  # 398 days: the max lifetime Apple/Chrome accept for a server certificate.
  openssl req -new -newkey rsa:2048 -nodes \
    -keyout "$OUT_DIR/leafkey.pem" -out "$OUT_DIR/leaf.csr" \
    -subj "/CN=api.${GHE_DOMAIN}" >/dev/null 2>&1
  openssl x509 -req -in "$OUT_DIR/leaf.csr" -out "$OUT_DIR/leaf.pem" \
    -CA "$OUT_DIR/cert.pem" -CAkey "$OUT_DIR/key.pem" \
    -CAserial "$OUT_DIR/ca.srl" -CAcreateserial \
    -days 398 -sha256 \
    -extfile /dev/stdin >/dev/null 2>&1 <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SANS}
EOF
  rm -f "$OUT_DIR/leaf.csr"
  # The chain the servers present: leaf first, then the issuing CA.
  cat "$OUT_DIR/leaf.pem" "$OUT_DIR/cert.pem" > "$OUT_DIR/leafchain.pem"
  echo "Wrote $OUT_DIR/leaf.pem, $OUT_DIR/leafkey.pem and $OUT_DIR/leafchain.pem (server cert)"
fi

chmod 644 "$OUT_DIR/leafkey.pem"
