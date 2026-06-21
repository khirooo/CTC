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
