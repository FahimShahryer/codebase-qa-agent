#!/usr/bin/env bash
# Restore a pre-built Weaviate index from a tarball.
#
# Usage:
#   ./backend/scripts/restore_index.sh <repo-tag>
#
# Example:
#   ./backend/scripts/restore_index.sh flask-v1
#
# Looks for indexes/<repo-tag>.tar.gz. Stops weaviate, wipes the named
# volume, untars into it (via a staging volume to dodge Windows path
# translation), restarts weaviate.

set -euo pipefail

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
    echo "usage: $0 <repo-tag>   (e.g. flask-v1)" >&2
    exit 2
fi

PROJECT="ajentica"
VOLUME="${PROJECT}_weaviate_data"
INDEXES_DIR="$(cd "$(dirname "$0")/../.." && pwd)/indexes"
INPUT_FILE="${INDEXES_DIR}/${TAG}.tar.gz"
STAGE_VOL="${PROJECT}_restore_stage_$$"

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "✗ Snapshot not found: ${INPUT_FILE}" >&2
    echo "  Available snapshots:" >&2
    ls -1 "${INDEXES_DIR}"/*.tar.gz 2>/dev/null || echo "  (none)"
    exit 1
fi

cleanup() {
    docker volume rm -f "$STAGE_VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "→ Stopping weaviate..."
docker compose stop weaviate 2>/dev/null || true

echo "→ Recreating volume ${VOLUME}..."
docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
docker volume create "$VOLUME" >/dev/null

echo "→ Staging tarball into a managed volume (avoids path-translation issues)..."
docker volume create "$STAGE_VOL" >/dev/null
HELPER=$(docker create -v "${STAGE_VOL}:/in" alpine:3 true)
docker cp "${INPUT_FILE}" "${HELPER}:/in/snapshot.tar.gz"
docker rm "${HELPER}" >/dev/null

echo "→ Extracting into ${VOLUME}..."
docker run --rm \
    -v "${VOLUME}:/data" \
    -v "${STAGE_VOL}:/in:ro" \
    alpine:3 \
    sh -c "cd /data && tar xzf /in/snapshot.tar.gz"

echo "→ Starting weaviate..."
docker compose up -d weaviate

echo "→ Waiting for weaviate to be ready..."
attempts=0
until curl -sS http://localhost:8080/v1/.well-known/ready >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if (( attempts > 30 )); then
        echo "✗ Weaviate didn't become ready in 60s" >&2
        exit 1
    fi
    sleep 2
done

echo ""
echo "✓ Restored. Schema:"
curl -sS http://localhost:8080/v1/schema 2>/dev/null | \
    python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for c in d.get('classes', []):
        print(f\"  - {c['class']} ({len(c.get('properties', []))} properties)\")
except Exception as e:
    print(f'  (could not parse schema: {e})')
"
