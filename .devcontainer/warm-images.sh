#!/usr/bin/env bash
# Get the ~16 GB of workshop images into the prebuild snapshot. This is the
# whole point of running the workshop in Codespaces (issue #7): the images, not
# the 139 MB dataset, are what make local setup slow on conference wifi.
#
# updateContentCommand is the LAST hook a prebuild runs -- postCreateCommand
# does not run during prebuild creation -- so this is the final chance to put
# bytes in the snapshot.
#
# The catch: GitHub's docs say "Docker-in-Docker is not available during
# prebuild creation". The mechanism they give is that registry credentials are
# injected after onCreateCommand, which only matters for *private* images, and
# every workshop image is public. So the daemon may well be usable here. Rather
# than bet either way, probe it:
#
#   A. daemon up   -> docker compose pull + build. Real images in the snapshot.
#   B. no daemon   -> skopeo the public images down as tarballs. Still no wifi
#                     transfer for the attendee; post-create.sh loads them.
#
# Path B cannot cover the seven locally-built services (flink, superset, docs,
# prepare, and the three MCP servers, ~4.7 GB): building needs a daemon. If the
# probe reports B, the fix is to publish those to GHCR in CI so they become
# ordinary pulls -- see issue #7.
set -euo pipefail

cd "$(dirname "$0")/.."

CACHE_DIR=/var/cache/workshop-images

docker_ready() {
  # Give the DinD feature a moment; it starts asynchronously.
  for _ in $(seq 1 30); do
    docker info >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# Registry images, read from compose so this cannot drift from the stack.
registry_images() {
  grep -oE '^[[:space:]]+image:[[:space:]]+\S+' docker-compose.yml \
    | awk '{print $2}' | sort -u
}

# Spell out the registry so skopeo does not have to guess. Only the FIRST path
# segment can be a registry host -- testing the whole reference would trip over
# the colon and dots in a tag (mongo:7, postgres:18.4-alpine3.23).
qualify_ref() {
  local image="$1" first="${1%%/*}"
  if [ "${first}" = "${image}" ]; then
    printf 'docker.io/library/%s\n' "${image}"   # mongo:7
    return
  fi
  case "${first}" in
    *.*|*:*|localhost) printf '%s\n' "${image}" ;;            # ghcr.io/...
    *)                 printf 'docker.io/%s\n' "${image}" ;;  # trinodb/trino:482
  esac
}

if command -v docker >/dev/null 2>&1 && docker_ready; then
  echo "==> Docker is available; pulling and building into the snapshot"
  # --profile tools so the one-shot `prepare` image (417 MB, built at
  # `task data:prepare` time) is warmed too, not left for the attendee.
  docker compose --profile tools pull --ignore-buildable
  docker compose --profile tools build
  echo "==> images in the snapshot:"
  docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}'
  exit 0
fi

echo "==> no Docker daemon in this phase; caching public images with skopeo"
echo "    (built services are not covered -- see the header comment)"

command -v skopeo >/dev/null 2>&1 || {
  sudo apt-get update -qq && sudo apt-get install -y -qq skopeo
}

sudo mkdir -p "${CACHE_DIR}"
sudo chown "$(id -u):$(id -g)" "${CACHE_DIR}"

while read -r image; do
  [ -n "${image}" ] || continue
  ref="$(qualify_ref "${image}")"
  tar="${CACHE_DIR}/$(echo "${image}" | tr '/:' '--').tar"
  if [ -f "${tar}" ]; then
    echo "  cached  ${image}"
    continue
  fi
  echo "  fetch   ${image}"
  skopeo copy --quiet "docker://${ref}" "docker-archive:${tar}:${image}"
done < <(registry_images)

echo "==> cached $(ls -1 "${CACHE_DIR}" | wc -l) images, $(du -sh "${CACHE_DIR}" | cut -f1)"
