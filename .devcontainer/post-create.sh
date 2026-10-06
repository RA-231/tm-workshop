#!/usr/bin/env bash
# Per-codespace setup. This does NOT run during prebuild creation, so keep it
# to things that depend on this particular codespace -- above all its forwarded
# hostname, which does not exist until the codespace does.
set -euo pipefail

cd "$(dirname "$0")/.."

CACHE_DIR=/var/cache/workshop-images

# --- Load any images warm-images.sh had to cache as tarballs ----------------
# Load-then-delete one at a time: the tarballs and the loaded images would
# otherwise both sit on disk at once, roughly doubling the peak.
if [ -d "${CACHE_DIR}" ] && [ -n "$(ls -A "${CACHE_DIR}" 2>/dev/null)" ]; then
  echo "==> loading cached images"
  for tar in "${CACHE_DIR}"/*.tar; do
    [ -f "${tar}" ] || continue
    echo "  load  $(basename "${tar}")"
    docker load -i "${tar}"
    rm -f "${tar}"
  done
fi

# --- Point browser-facing URLs at the forwarded host ------------------------
# Codespaces forwards each port to https://<codespace>-<port>.<domain>. Anything
# the browser or the agent follows has to use that, not localhost.
if [ -n "${CODESPACE_NAME:-}" ]; then
  PORT_DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  SUPERSET_PUBLIC_URL="https://${CODESPACE_NAME}-8088.${PORT_DOMAIN}"

  # docker compose reads .env from the project directory; `task setup` created
  # it in on-create.sh. Replace the line rather than appending a duplicate.
  touch .env
  if grep -q '^SUPERSET_PUBLIC_URL=' .env; then
    sed -i "s|^SUPERSET_PUBLIC_URL=.*|SUPERSET_PUBLIC_URL=${SUPERSET_PUBLIC_URL}|" .env
  else
    printf '\n# Set by .devcontainer/post-create.sh -- the forwarded Superset host.\nSUPERSET_PUBLIC_URL=%s\n' \
      "${SUPERSET_PUBLIC_URL}" >> .env
  fi

  cat <<EOF

  This codespace's service URLs (localhost in the docs maps to these):

    Docs + service links  https://${CODESPACE_NAME}-4321.${PORT_DOMAIN}
    Trino                 https://${CODESPACE_NAME}-8080.${PORT_DOMAIN}
    Flink UI              https://${CODESPACE_NAME}-8081.${PORT_DOMAIN}
    Superset              https://${CODESPACE_NAME}-8088.${PORT_DOMAIN}
    LibreChat             https://${CODESPACE_NAME}-3080.${PORT_DOMAIN}

  VS Code's Ports panel lists the rest. Paste your workshop model key into
  .env as LLM_API_KEY before Step 3.

EOF
fi

echo "==> post-create done. Start with: task up:docs"
