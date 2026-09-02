#!/usr/bin/env sh
# Real-openssl test: gen-cert.sh must embed CTC_DOMAIN in the SANs, and must emit
# a CA plus a separate CA:FALSE server leaf. Serving the CA as the end-entity
# cert is what broke Copilot CLI >= 1.0.82 (rustls: CaUsedAsEndEntity).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
GENCERT="$HERE/../gen-cert.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

gen() { CTC_DOMAIN="$1" GHE_DOMAIN=corp.ghe.com sh "$GENCERT" "$TMP" >/dev/null 2>&1; }
gen ctc.example.test

fail=0
check() { # check <description> <expected-substring> <haystack>
  case "$3" in *"$2"*) echo "  ok: $1";; *) echo "  FAIL: $1"; fail=1;; esac
}

# --- the leaf is what servers present: SANs must cover the MITM hosts + domain
sans="$(openssl x509 -in "$TMP/leaf.pem" -noout -ext subjectAltName)"
check "CTC_DOMAIN in leaf SANs"      "DNS:ctc.example.test"     "$sans"
check "GHE MITM host in leaf SANs"   "DNS:api.corp.ghe.com"     "$sans"
check "copilot-api in leaf SANs"     "DNS:copilot-api.corp.ghe.com" "$sans"

# --- the leaf must be usable as an end-entity server cert
leaf_ext="$(openssl x509 -in "$TMP/leaf.pem" -noout -ext basicConstraints,extendedKeyUsage)"
check "leaf is CA:FALSE"             "CA:FALSE"                 "$leaf_ext"
check "leaf has serverAuth EKU"      "TLS Web Server Authentication" "$leaf_ext"

# --- the CA must remain a CA, and must NOT be what gets presented
ca_ext="$(openssl x509 -in "$TMP/cert.pem" -noout -ext basicConstraints)"
check "CA is CA:TRUE"                "CA:TRUE"                  "$ca_ext"
check "CTC_DOMAIN still in CA SANs"  "DNS:ctc.example.test" \
      "$(openssl x509 -in "$TMP/cert.pem" -noout -ext subjectAltName)"

# --- the chain the servers load must verify against the CA clients trust
if openssl verify -CAfile "$TMP/cert.pem" "$TMP/leaf.pem" >/dev/null 2>&1; then
  echo "  ok: leaf verifies against the CA"
else
  echo "  FAIL: leaf does not verify against the CA"; fail=1
fi
check "leafchain starts with the leaf" \
      "$(openssl x509 -in "$TMP/leaf.pem" -noout -serial)" \
      "$(openssl x509 -in "$TMP/leafchain.pem" -noout -serial)"
if [ "$(grep -c 'BEGIN CERTIFICATE' "$TMP/leafchain.pem")" = 2 ]; then
  echo "  ok: leafchain carries leaf + issuer"
else
  echo "  FAIL: leafchain should hold exactly 2 certificates"; fail=1
fi

# --- re-running must not rotate the CA (clients would have to re-trust)
ca_before="$(openssl x509 -in "$TMP/cert.pem" -noout -fingerprint -sha256)"
leaf_before="$(openssl x509 -in "$TMP/leaf.pem" -noout -fingerprint -sha256)"
gen ctc.example.test
check "CA unchanged on re-run" "$ca_before" \
      "$(openssl x509 -in "$TMP/cert.pem" -noout -fingerprint -sha256)"
check "leaf unchanged on re-run" "$leaf_before" \
      "$(openssl x509 -in "$TMP/leaf.pem" -noout -fingerprint -sha256)"

# --- a changed CTC_DOMAIN must reissue the leaf (and still keep the CA)
gen other.example.test
check "CA survives a domain change" "$ca_before" \
      "$(openssl x509 -in "$TMP/cert.pem" -noout -fingerprint -sha256)"
check "leaf reissued for new domain" "DNS:other.example.test" \
      "$(openssl x509 -in "$TMP/leaf.pem" -noout -ext subjectAltName)"

# --- an existing CA-only deployment (the real upgrade path) gains a leaf
rm -f "$TMP/leaf.pem" "$TMP/leafkey.pem" "$TMP/leafchain.pem"
gen other.example.test
check "CA-only deployment gains a leaf" "$ca_before" \
      "$(openssl x509 -in "$TMP/cert.pem" -noout -fingerprint -sha256)"
if openssl verify -CAfile "$TMP/cert.pem" "$TMP/leaf.pem" >/dev/null 2>&1; then
  echo "  ok: backfilled leaf signed by the pre-existing CA"
else
  echo "  FAIL: backfilled leaf does not chain to the pre-existing CA"; fail=1
fi

exit "$fail"
