#!/usr/bin/env bash
# Smoke test of the running containers (docker compose up): the built image works
# end to end, including the worker carrying a click from the Stream to Cassandra.
#
#   bash scripts/smoke_test.sh [base url]      (default http://localhost:8001)
#
# Needs curl and jq. Leaves its user and link behind: meant for CI, where the
# databases are thrown away afterwards, or for a throwaway local stack.
set -euo pipefail

API="${1:-http://localhost:8001}"
EMAIL="smoke-$(date +%s)-$RANDOM@example.com"  # unique, so a rerun is never a 409
PASSWORD="smoke-test-password"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

curl -fsS "$API/ready" >/dev/null || fail "/ready: the API cannot reach MongoDB"

credentials="{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}"
curl -fsS -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "$credentials" >/dev/null || fail "register"
TOKEN=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "$credentials" | jq -r .access_token) || fail "login"

CODE=$(curl -fsS -X POST "$API/links" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"url": "https://example.com/"}' \
  | jq -r .code) || fail "create a link"

location=$(curl -sS -o /dev/null -w '%{redirect_url}' "$API/$CODE")
[ "$location" = "https://example.com/" ] || fail "the redirect went to '$location'"

# Counting is asynchronous on purpose (Stream, then worker), so wait for it. Until
# the API's first Cassandra connection succeeds, statistics may answer 503.
clicks=""
for _ in $(seq 30); do
  clicks=$(curl -sS "$API/links/$CODE/stats" -H "Authorization: Bearer $TOKEN" \
    | jq -r '.total_clicks // empty' 2>/dev/null || true)
  if [ "$clicks" = "1" ]; then
    echo "OK: registered, created $CODE, redirected, and the worker counted the click"
    exit 0
  fi
  sleep 1
done
fail "the click was not counted within 30 seconds (total_clicks: '${clicks}')"
