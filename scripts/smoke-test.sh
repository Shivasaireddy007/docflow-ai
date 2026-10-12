#!/usr/bin/env bash
# Uploads a receipt to a running stack and waits for its extraction.
#   scripts/smoke-test.sh <api-key> [base_url] [file]
set -euo pipefail
KEY="$1"
BASE="${2:-http://localhost:8000}"
FILE="${3:-$(dirname "$0")/../e2e/receipt.png}"
AUTH="Authorization: Api-Key $KEY"

fail() { echo "FAILED: $*" >&2; exit 1; }

echo "== Health"
curl -fsS "$BASE/ready" | grep -q '"database": "ok"' || fail "not ready"

echo "== Upload"
id=$(curl -fsS -H "$AUTH" -F "file=@$FILE" "$BASE/api/v1/documents" | jq -r .id)
[ -n "$id" ] && [ "$id" != null ] || fail "upload returned no id"
echo "document $id"

echo "== Same file again is deduplicated"
dup=$(curl -fsS -H "$AUTH" -F "file=@$FILE" "$BASE/api/v1/documents" | jq -r .duplicate)
[ "$dup" = true ] || fail "duplicate upload created a new document"

echo "== Extraction"
for _ in $(seq 1 60); do
  status=$(curl -fsS -H "$AUTH" "$BASE/api/v1/documents/$id" | jq -r .status)
  [ "$status" = extracted ] || [ "$status" = failed ] && break
  sleep 2
done
[ "$status" = extracted ] || fail "status is $status"
curl -fsS -H "$AUTH" "$BASE/api/v1/documents/$id" | jq '{status, confidence: .extraction.confidence, total: .extraction.fields.total, pipeline: .extraction.pipeline_version}'

echo "== Requests without a key are refused"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/documents/$id")" = 401 ] || fail "unauthenticated access allowed"

echo
echo "All smoke tests passed."
