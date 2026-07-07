#!/usr/bin/env bash
# Checkpoint helper: save or restore the warehouse so attendees who fall behind
# can skip straight to a known-good state.
#
#   scripts/checkpoint.sh save <name>     -> checkpoints/<name>.tar.gz
#   scripts/checkpoint.sh restore <name>  <- checkpoints/<name>.tar.gz,
#                                            or $CHECKPOINT_BASE_URL/<name>.tar.gz
#
# This snapshots the Garage volumes (the Iceberg data + metadata files) AND the
# Polaris Postgres volume (the catalog registration that points at them). They
# are coupled — the catalog references specific metadata files — so both must
# be captured and restored together. A restore is then complete: no re-create,
# no re-ingest. (Stop the stack before restoring so nothing writes mid-swap.)
#
# Instructors: run `save` after finishing each step during prep, then host
# the checkpoints/ directory anywhere attendees can reach and set
# CHECKPOINT_BASE_URL.
set -euo pipefail

cmd="${1:?usage: checkpoint.sh {save|restore} <name>}"
name="${2:?usage: checkpoint.sh {save|restore} <name>}"
mkdir -p checkpoints

# Tar/untar the coupled state volumes via a throwaway busybox container.
VOLUMES="tm-tutorial_garage-meta tm-tutorial_garage-data tm-tutorial_polaris-pg"

case "$cmd" in
  save)
    mounts=""
    for v in $VOLUMES; do mounts="$mounts -v ${v}:/vol/${v#tm-tutorial_}"; done
    docker run --rm $mounts -v "$PWD/checkpoints:/out" busybox \
      tar -czf "/out/${name}.tar.gz" -C /vol .
    echo "saved checkpoints/${name}.tar.gz ($(du -h "checkpoints/${name}.tar.gz" | cut -f1))"
    ;;
  restore)
    if [ ! -f "checkpoints/${name}.tar.gz" ]; then
      base="${CHECKPOINT_BASE_URL:?checkpoint not found locally and CHECKPOINT_BASE_URL is not set}"
      curl -fL -o "checkpoints/${name}.tar.gz" "${base}/${name}.tar.gz"
    fi
    mounts=""
    for v in $VOLUMES; do mounts="$mounts -v ${v}:/vol/${v#tm-tutorial_}"; done
    docker run --rm $mounts -v "$PWD/checkpoints:/out" busybox \
      sh -c "rm -rf /vol/* && tar -xzf /out/${name}.tar.gz -C /vol"
    echo "restored warehouse + catalog from checkpoint '${name}' — start the stack and query"
    ;;
  *)
    echo "unknown command: $cmd" >&2; exit 1 ;;
esac
