#!/usr/bin/env bash
# Checkpoint helper: save or restore the warehouse so attendees who fall behind
# can skip straight to a known-good state.
#
#   scripts/checkpoint.sh save <name>     -> data/checkpoints/<name>.tar.gz
#   scripts/checkpoint.sh restore <name>  <- data/checkpoints/<name>.tar.gz,
#                                            or $CHECKPOINT_BASE_URL/<name>.tar.gz
#
# This snapshots the Garage volumes (the Iceberg data + metadata files) AND the
# Polaris Postgres volume (the catalog registration that points at them). They
# are coupled — the catalog references specific metadata files — so both must
# be captured and restored together. A restore is then complete: no re-create,
# no re-ingest. Restore stops Garage, Polaris and its Postgres first so nothing
# writes mid-swap; stop the stack yourself before a save for the same reason.
#
# Instructors: run `save` after finishing each step during prep. Checkpoints
# live under data/ so they travel with the dataset: copy data/ to the USB
# drives, or host data/checkpoints/ and set CHECKPOINT_BASE_URL.
set -euo pipefail

cmd="${1:?usage: checkpoint.sh save|restore <name>}"
name="${2:?usage: checkpoint.sh save|restore <name>}"
DIR=data/checkpoints
mkdir -p "$DIR"

# Tar/untar the coupled state volumes via a throwaway busybox container.
VOLUMES="tm-tutorial_garage-meta tm-tutorial_garage-data tm-tutorial_polaris-pg"

case "$cmd" in
  save)
    mounts=""
    for v in $VOLUMES; do mounts="$mounts -v ${v}:/vol/${v#tm-tutorial_}"; done
    docker run --rm $mounts -v "$PWD/$DIR:/out" busybox \
      tar -czf "/out/${name}.tar.gz" -C /vol .
    echo "saved $DIR/${name}.tar.gz ($(du -h "$DIR/${name}.tar.gz" | cut -f1))"
    ;;
  restore)
    if [ ! -f "$DIR/${name}.tar.gz" ]; then
      base="${CHECKPOINT_BASE_URL:?checkpoint not found in $DIR and CHECKPOINT_BASE_URL is not set}"
      curl -fL -o "$DIR/${name}.tar.gz" "${base}/${name}.tar.gz"
    fi
    # Replacing files under a running Postgres or Garage corrupts them.
    docker compose stop polaris polaris-postgres garage
    mounts=""
    for v in $VOLUMES; do mounts="$mounts -v ${v}:/vol/${v#tm-tutorial_}"; done
    # Empty each volume, not /vol/* itself: those are mount points, so rm
    # would clear them and then fail on the mount, skipping the extract.
    docker run --rm $mounts -v "$PWD/$DIR:/out" busybox \
      sh -c "find /vol -mindepth 2 -maxdepth 2 -exec rm -rf {} + && tar -xzf /out/${name}.tar.gz -C /vol"
    echo "restored warehouse + catalog from checkpoint '${name}' — start the stack and query"
    ;;
  *)
    echo "unknown command: $cmd" >&2; exit 1 ;;
esac
