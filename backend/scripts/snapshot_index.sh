#!/usr/bin/env bash
# Snapshot the Weaviate data volume into a portable tarball.
#
# Usage:
#   ./backend/scripts/snapshot_index.sh <repo-tag>
#
# Example:
#   ./backend/scripts/snapshot_index.sh flask-v1
#
# Produces: indexes/<repo-tag>.tar.gz
#
# Cross-platform note: uses a docker-managed staging volume + docker cp to
# avoid host bind-mount path-translation issues (Git Bash on Windows, etc).

set -euo pipefail

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
    echo "usage: $0 <repo-tag>   (e.g. flask-v1)" >&2
    exit 2
fi

PROJECT="ajentica"
VOLUME="${PROJECT}_weaviate_data"
OUTPUT_DIR="$(cd "$(dirname "$0")/../.." && pwd)/indexes"
OUTPUT_FILE="${OUTPUT_DIR}/${TAG}.tar.gz"
STAGE_VOL="${PROJECT}_snapshot_stage_$$"

mkdir -p "$OUTPUT_DIR"

cleanup() {
    docker volume rm -f "$STAGE_VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "→ Stopping weaviate for a clean snapshot..."
docker compose stop weaviate

echo "→ Creating staging volume ${STAGE_VOL}..."
docker volume create "$STAGE_VOL" >/dev/null

echo "→ Tarring ${VOLUME} → staging volume..."
docker run --rm \
    -v "${VOLUME}:/data:ro" \
    -v "${STAGE_VOL}:/out" \
    alpine:3 \
    sh -c "cd /data && tar czf /out/snapshot.tar.gz . && ls -lh /out/snapshot.tar.gz"

echo "→ Copying snapshot from staging volume → ${OUTPUT_FILE}..."
HELPER=$(docker create -v "${STAGE_VOL}:/out:ro" alpine:3 true)
docker cp "${HELPER}:/out/snapshot.tar.gz" "${OUTPUT_FILE}"
docker rm "${HELPER}" >/dev/null

echo "→ Restarting weaviate..."
docker compose start weaviate

echo ""
echo "✓ Snapshot written: ${OUTPUT_FILE}"
ls -lh "$OUTPUT_FILE"
