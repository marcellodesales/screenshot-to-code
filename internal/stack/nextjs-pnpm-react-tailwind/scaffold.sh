#!/usr/bin/env bash
#
# Scaffold a nextjs-pnpm-react-tailwind app into an empty directory:
#
#   scaffold.sh <dest-dir> <app-name> [sources-dir]
#
# 1. pinned create-next-app (see template.yaml `scaffold`)
# 2. overlay files from this template (template.yaml `overlay`)
# 3. optional [sources-dir] copied on top (migrated src/, public/, design/)
# 4. pnpm-lock.yaml, so the Dockerfile's --frozen-lockfile build is reproducible
#
# Everything runs in the pinned node image: no host Node/pnpm needed. The
# scaffold runs in a container-local cwd and is copied out at the end, which
# avoids pnpm leaving a dlx store in a bind-mounted directory.
#
# Keep the pins below in sync with template.yaml `scaffold.versions`.
set -euo pipefail

NODE_IMAGE="node:22.23.3-alpine3.24@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402"
PNPM_VERSION="12.10.1"
CREATE_NEXT_APP_VERSION="16.4.0"
OVERLAY="Dockerfile .dockerignore docker-compose.yaml .env.example next.config.ts"

die() { echo "scaffold: $*" >&2; exit 1; }

[[ $# -ge 2 ]] || die "usage: $0 <dest-dir> <app-name> [sources-dir]"
DEST="$1"
APP_NAME="$2"
SOURCES="${3:-}"
TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# npm package name rules (lowercase, url-safe); also the directory name.
[[ "$APP_NAME" =~ ^[a-z0-9][a-z0-9._-]{0,213}$ ]] || die "invalid app name: $APP_NAME"
mkdir -p "$DEST"
[[ -z "$(ls -A "$DEST")" ]] || die "destination is not empty: $DEST"
DEST="$(cd "$DEST" && pwd)"

mounts=(-v "$TEMPLATE_DIR:/template:ro" -v "$DEST:/out")
if [[ -n "$SOURCES" ]]; then
  [[ -d "$SOURCES" ]] || die "sources dir not found: $SOURCES"
  mounts+=(-v "$(cd "$SOURCES" && pwd):/sources:ro")
fi

docker run --rm "${mounts[@]}" \
  -e APP_NAME="$APP_NAME" \
  -e PNPM_VERSION="$PNPM_VERSION" \
  -e CREATE_NEXT_APP_VERSION="$CREATE_NEXT_APP_VERSION" \
  -e OVERLAY="$OVERLAY" \
  -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
  -e NEXT_TELEMETRY_DISABLED=1 \
  "$NODE_IMAGE" sh -euc '
    corepack enable
    corepack prepare "pnpm@$PNPM_VERSION" --activate
    cd /tmp
    pnpm dlx "create-next-app@$CREATE_NEXT_APP_VERSION" "$APP_NAME" \
      --ts --tailwind --eslint --app --src-dir --import-alias "@/*" \
      --use-pnpm --skip-install --disable-git --no-agent-feedback --yes
    cd "/tmp/$APP_NAME"
    for f in $OVERLAY; do cp "/template/$f" "./$f"; done
    if [ -d /sources ]; then cp -R /sources/. ./; fi
    # Corepack in the Dockerfile installs exactly this pnpm.
    npm pkg set "packageManager=pnpm@$PNPM_VERSION"
    pnpm install --lockfile-only --store-dir /tmp/pnpm-store
    rm -rf node_modules
    cp -R . /out/
    # Hand the files back to the invoking user (matters on Linux hosts).
    chown -R "$(stat -c %u:%g /out)" /out
  '

echo "scaffold: $APP_NAME -> $DEST"
