#!/usr/bin/env bash
cd "$(dirname "$0")"
. ./lib.sh
for f in test_*.sh; do
  echo "== $f =="
  . "./$f"
  for fn in $(grep -oE '^test_[a-zA-Z0-9_]+' "$f"); do echo "- $fn"; "$fn"; done
done
echo "== $TESTS_RUN run, $TESTS_FAILED failed =="
[ "$TESTS_FAILED" -eq 0 ]
