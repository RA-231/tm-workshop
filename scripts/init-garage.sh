#!/usr/bin/env bash
# One-time Garage initialization: assign the single node a storage layout,
# create the `warehouse` bucket, and install the fixed workshop access key.
# Idempotent — safe to re-run.
set -euo pipefail

g() { docker compose exec -T garage /garage "$@"; }

# Fixed credentials, shared by Polaris, Flink, and Trino. A workshop is not
# production: nothing here is secret, everything binds to localhost.
ACCESS_KEY="GK31c2f218a2e44f485b94239e"
SECRET_KEY="7d37d093435a41f2aab8f13c19ba067d9776c90215f56614adad6ece597dbb34"

echo "waiting for garage ..."
for i in $(seq 1 30); do
  g status >/dev/null 2>&1 && break
  sleep 1
  [ "$i" = 30 ] && { echo "garage did not come up"; exit 1; }
done

if g status | grep -q "NO ROLE ASSIGNED"; then
  node_id=$(g status | awk '/^[0-9a-f]{16}/ {print $1; exit}')
  echo "assigning layout to node ${node_id} ..."
  g layout assign -z dc1 -c 10G "${node_id}"
  g layout apply --version 1
fi

g bucket info warehouse >/dev/null 2>&1 || g bucket create warehouse

if ! g key info "${ACCESS_KEY}" >/dev/null 2>&1; then
  # `key import` lets us use fixed credentials instead of generated ones.
  g key import --yes -n workshop "${ACCESS_KEY}" "${SECRET_KEY}"
fi

g bucket allow --read --write --owner warehouse --key "${ACCESS_KEY}"
echo "garage ready: bucket 'warehouse', key ${ACCESS_KEY}"
