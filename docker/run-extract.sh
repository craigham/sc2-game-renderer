#!/usr/bin/env bash
# Runs the `extract` stage (see cli_extract.py / docs/SPEC.md) in the sc2-extract:4.10
# image built from this directory's Dockerfile. Wraps the docker run invocation
# documented informally in docs/PLAN.md (slice 3) so callers don't have to
# reconstruct the mount layout by hand — this is the one thing test_lab's render
# view shells out to.
#
# Usage:
#   docker/run-extract.sh --replay REPLAY.SC2Replay --player ID --out OUT.frames.jsonl.gz --maps-dir DIR
#
# --maps-dir is the host's StarCraft II Maps directory (contains *.SC2Map files
# directly, not a parent). Mounted at /StarCraftII/Maps to match SC2PATH=/StarCraftII
# set in the Dockerfile (confirmed against the vendored sc2/paths.py: maps resolve at
# $SC2PATH/Maps when $SC2PATH/maps, lowercase, doesn't exist).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="sc2-extract:4.10"

replay=""
player=""
out=""
maps_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --replay) replay="$2"; shift 2 ;;
    --player) player="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --maps-dir) maps_dir="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$replay" || -z "$player" || -z "$out" || -z "$maps_dir" ]]; then
  echo "usage: $0 --replay REPLAY.SC2Replay --player ID --out OUT.frames.jsonl.gz --maps-dir DIR" >&2
  exit 1
fi

replay="$(cd "$(dirname "$replay")" && pwd)/$(basename "$replay")"
mkdir -p "$(dirname "$out")"
out_dir="$(cd "$(dirname "$out")" && pwd)"
out_basename="$(basename "$out")"
maps_dir="$(cd "$maps_dir" && pwd)"

docker run --rm \
  --platform=linux/amd64 \
  -v "$REPO_ROOT/src:/work/src:ro" \
  -e PYTHONPATH=/work/src \
  -v "$maps_dir:/StarCraftII/Maps:ro" \
  -v "$(dirname "$replay"):/replays:ro" \
  -v "$out_dir:/out" \
  -w /work \
  "$IMAGE" \
  -m sc2_game_renderer.cli_extract "/replays/$(basename "$replay")" --player "$player" --out "/out/$out_basename"
