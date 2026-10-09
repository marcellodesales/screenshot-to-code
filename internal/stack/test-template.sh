#!/usr/bin/env bash
#
# End-to-end test for one stack template behind the system gateway.
#
#   internal/stack/test-template.sh <stack-id> [fixture-html] [marker]
#
# 1. copies internal/stack/<stack-id>/ to a temp dir
# 2. copies the fixture into the template's `mock_path` (from template.yaml)
# 3. writes .env with APP_ID=tst-<stack-id>-<rand> and APP_HOST=<APP_ID>.localhost
# 4. docker compose up -d --build --wait
# 5. curl -H "Host: $APP_HOST" http://localhost:${GATEWAY_PORT:-3311}/ and
#    asserts the marker is in the body
# 6. docker compose down --rmi local -v (always, via trap)
#
# Marker: 3rd argument, else parsed from the fixture's
#   <!-- s2c-fixture-marker: <MARKER> -->
# comment.
#
# Requires the gateway from the root docker-compose.yml to be running
# (Traefik on host port 3311 + network `traefik_webgateway`).
#
# Env:
#   GATEWAY_PORT   Traefik `web` host port (default 3311)
#   KEEP=1         leave the app running for manual inspection (prints the
#                  teardown command instead of running it)
#   WAIT_SECONDS   how long to retry the gateway request (default 60)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_PORT="${GATEWAY_PORT:-3311}"
WAIT_SECONDS="${WAIT_SECONDS:-60}"

die() { echo "FAIL: $*" >&2; exit 1; }
log() { echo "==> $*"; }

[[ $# -ge 1 ]] || die "usage: $0 <stack-id> [fixture-html] [marker]"
STACK_ID="$1"
FIXTURE="${2:-$SCRIPT_DIR/fixtures/react-tailwind-mock.html}"
TEMPLATE_DIR="$SCRIPT_DIR/$STACK_ID"

[[ -d "$TEMPLATE_DIR" ]] || die "no template directory: $TEMPLATE_DIR"
[[ -f "$TEMPLATE_DIR/template.yaml" ]] || die "missing $TEMPLATE_DIR/template.yaml"
[[ -f "$FIXTURE" ]] || die "fixture not found: $FIXTURE"

# Top-level scalar from template.yaml (no yq dependency).
yaml_get() {
  sed -nE "s/^$1:[[:space:]]*['\"]?([^'\"#]*[^'\"#[:space:]])['\"]?[[:space:]]*(#.*)?$/\1/p" "$2" | head -n1
}

MOCK_PATH="$(yaml_get mock_path "$TEMPLATE_DIR/template.yaml")"
[[ -n "$MOCK_PATH" ]] || die "template.yaml has no top-level 'mock_path:'"
case "$MOCK_PATH" in /*|*..*) die "mock_path must be relative to the template: $MOCK_PATH" ;; esac

MARKER="${3:-$(sed -nE 's/.*s2c-fixture-marker:[[:space:]]*([^[:space:]]+).*/\1/p' "$FIXTURE" | head -n1)}"
[[ -n "$MARKER" ]] || die "no marker: pass one or add '<!-- s2c-fixture-marker: X -->' to the fixture"

docker network inspect traefik_webgateway >/dev/null 2>&1 \
  || die "network traefik_webgateway not found; start the gateway (root docker-compose.yml) first"

# DNS label: [a-z0-9-], <= 63 chars.
RAND="$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
APP_ID="$(printf 'tst-%s' "$STACK_ID" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-55)-$RAND"
APP_HOST="$APP_ID.localhost"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/s2c-$STACK_ID.XXXXXX")"
APP_DIR="$WORK_DIR/app"

compose() { docker compose --project-directory "$APP_DIR" -f "$APP_DIR/docker-compose.yaml" "$@"; }

cleanup() {
  local rc=$?
  if [[ "${KEEP:-0}" == "1" ]]; then
    echo "KEEP=1: app left running at http://$APP_HOST:$GATEWAY_PORT/"
    echo "teardown: docker compose --project-directory '$APP_DIR' down --rmi local -v && rm -rf '$WORK_DIR'"
  else
    log "tearing down $APP_ID"
    compose down --rmi local -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK_DIR"
  fi
  if [[ $rc -eq 0 ]]; then echo "PASS: $STACK_ID ($APP_ID)"; else echo "FAIL: $STACK_ID ($APP_ID) rc=$rc" >&2; fi
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

log "template  $STACK_ID -> $APP_DIR"
cp -R "$TEMPLATE_DIR" "$APP_DIR"
mkdir -p "$(dirname "$APP_DIR/$MOCK_PATH")"
cp "$FIXTURE" "$APP_DIR/$MOCK_PATH"
log "fixture   $FIXTURE -> $MOCK_PATH (marker $MARKER)"

cat > "$APP_DIR/.env" <<EOF
APP_ID=$APP_ID
APP_HOST=$APP_HOST
EOF
log "APP_ID=$APP_ID APP_HOST=$APP_HOST"

compose config -q
log "docker compose up -d --build --wait"
compose up -d --build --wait

URL="http://localhost:$GATEWAY_PORT/"
log "GET $URL (Host: $APP_HOST)"
deadline=$(( $(date +%s) + WAIT_SECONDS ))
body=""
while :; do
  # Traefik picks the container up only once it is healthy; retry briefly.
  if body="$(curl -fsS --max-time 10 -H "Host: $APP_HOST" "$URL" 2>/dev/null)"; then
    break
  fi
  (( $(date +%s) < deadline )) || { compose ps >&2 || true; die "no 2xx from gateway for Host: $APP_HOST within ${WAIT_SECONDS}s"; }
  sleep 2
done

grep -qF -- "$MARKER" <<<"$body" || die "marker '$MARKER' not found in response body"
log "marker found ($(printf '%s' "$body" | wc -c | tr -d ' ') bytes)"
