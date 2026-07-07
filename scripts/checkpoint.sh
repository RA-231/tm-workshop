#!/usr/bin/env bash
# Checkpoint helper: save or restore the Iceberg warehouse (the Garage S3
# volumes) so attendees who fall behind can skip straight to a known-good
# state.
#
#   scripts/checkpoint.sh save <name>     -> checkpoints/<name>.tar.gz
#   scripts/checkpoint.sh restore <name>  <- checkpoints/<name>.tar.gz,
#                                            or $CHECKPOINT_BASE_URL/<name>.tar.gz
#
# NOTE: Polaris uses an in-memory metastore, so restoring the Garage data is
# only half the picture — after a restore you must also re-create the catalog
# (`task catalog:create`) and re-submit the Flink job so Polaris re-registers
# the table against the restored files. The `restore` path does the catalog
# step for you; re-run `task flink:job` afterwards.
#
# Instructors: run `save` after finishing each step during prep, then host
# the checkpoints/ directory anywhere attendees can reach and set
# CHECKPOINT_BASE_URL.
set -euo pipefail

cmd="${1:?usage: checkpoint.sh {save|restore} <name>}"
name="${2:?usage: checkpoint.sh {save|restore} <name>}"
mkdir -p checkpoints

# Tar/untar the two Garage docker volumes via a throwaway busybox container.
VOLUMES="tm-tutorial_garage-meta tm-tutorial_garage-data"

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
    echo "restored Garage volumes from checkpoint '${name}'"
    echo "now run: task catalog:create && task flink:job"
    ;;
  *)
    echo "unknown command: $cmd" >&2; exit 1 ;;
esac
