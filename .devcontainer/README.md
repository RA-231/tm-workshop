# Running the workshop in GitHub Codespaces

Status: **unverified.** The config here is written but has never been run in a
real Codespace. Issue [#7](https://github.com/RA-231/tm-workshop/issues/7)
tracks the evaluation; this file is the procedure for doing it.

## Why

The slow part of local setup is pulling ~16 GB of container images, not the
139 MB dataset. At a conference every attendee pulls them at once over the same
wifi. A Codespace pulls over GitHub's network, and a *prebuild* bakes the images
into the snapshot so attendees pull nothing at session time.

## Prebuild settings to apply

Repo → Settings → Codespaces → Prebuilds → *Set up prebuild*:

| Setting | Value | Why |
|---|---|---|
| Configuration file | `.devcontainer/devcontainer.json` | the only one |
| Branch | `main` | |
| Trigger | *On configuration change* | the stack changes rarely; a push-triggered prebuild would rebuild 16 GB on every docs commit |
| Region availability | whichever region the venue is in | a prebuild only helps attendees in a region it exists in |
| Template history | 1 version | each version stores the full ~20 GB snapshot |
| Prebuild dev container | 4-core (the largest available) | |

Then **run the prebuild once manually** and read its workflow log — that log is
what answers the open question below.

## The open question: does Docker work during a prebuild?

GitHub's docs state, verbatim:

> This happens after the `onCreateCommand` lifecycle hook but before
> `postCreateCommand`, `postStartCommand`, and `postAttachCommand`. As a result,
> `postCreateCommand` will be able to use Docker-in-Docker to pull a Docker
> image into the codespace, but `onCreateCommand` will not. For this reason,
> Docker-in-Docker is not available during prebuild creation.

— [allowing-your-codespace-to-access-a-private-registry](https://docs.github.com/en/codespaces/reference/allowing-your-codespace-to-access-a-private-registry)

The *mechanism* given is registry credential injection, which only affects
private images. Every workshop image is public, and `updateContentCommand` runs
after `onCreateCommand` (where the docs say those credentials land) and still
runs during prebuild. So the daemon may well be usable. The docs' flat
conclusion and its stated mechanism disagree, and only a real prebuild settles
it.

`warm-images.sh` probes rather than assuming, and prints which path it took:

- **`Docker is available`** → `docker compose pull` + `build`. All 16 GB,
  including the seven locally-built services, land in the snapshot. Ideal.
- **`no Docker daemon in this phase`** → falls back to `skopeo`, caching the
  eight public registry images (~11.5 GB) as tarballs that `post-create.sh`
  loads. The bandwidth still moves off the wifi, but the ~4.7 GB of built
  images (`flink`, `superset`, `docs`, `prepare`, and the three MCP servers)
  are **not** covered, and their `pip`/`npm` installs still run per codespace.

**If the fallback path fires**, the fix is to build those seven in CI and push
them to `ghcr.io/ra-231/...`, turning them into ordinary pulls that skopeo can
cache too. That is a larger change than this directory and belongs in its own
issue.

## What is verified, and what is not

Verified locally:

- `devcontainer.json` parses; `forwardPorts` and `portsAttributes` agree
- all three scripts pass `bash -n`
- `qualify_ref()` resolves all eight compose images correctly, plus
  `localhost:5000/...` and registry-with-port edge cases
- `docker compose pull --ignore-buildable` is a real flag (Compose v2)
- `SUPERSET_PUBLIC_URL` honours an override and still defaults to localhost
- the `.env` rewrite replaces in place under GNU sed, stays at one line, and
  leaves `LLM_API_KEY` untouched
- skopeo `docker-archive` → `docker load` round-trips: correct repo:tag, image runs

## Machine size is a hard ceiling

`gh api /repos/RA-231/tm-workshop/codespaces/machines` returns exactly two
types: 2-core/8 GB/32 GB and **4-core/16 GB/32 GB**. There is no 8-core and no
64 GB disk. Asking for more than exists does not downgrade — codespace creation
fails outright with *"no machine types are available"*. `hostRequirements` is
therefore set to the 4-core ceiling.

If a bigger machine is wanted, it is an org policy change (Settings →
Codespaces → Machine types), not a config change here — and the prebuild and
`hostRequirements` would both need revisiting.

### 16 GB does not fit the laptop defaults

Two services size themselves far past what is left on a 16 GB box:

- **Trino** — its image sets `-XX:MaxRAMPercentage=80` and compose puts no
  limit on the container, so the JVM sizes against the whole host. Measured at
  **13.2 GB** on a 94 GB machine. On 16 GB it would claim ~12.8 GB.
- **Flink** — reserves 6 GB outright (2 GB jobmanager + 4 GB taskmanager).

`docker-compose.codespaces.yml` caps both, plus the other JVM and Node
services, to a ~14 GB budget leaving ~2 GB for the VS Code server and OS. It is
applied through `COMPOSE_FILE` in `remoteEnv`, so `task` needs no change and a
laptop never sees it (verified: `docker compose config` without `COMPOSE_FILE`
still has zero `mem_limit` entries and Flink at 2g/4g).

Flink needs both halves — a cgroup limit alone makes it OOM-kill, because it
sizes from its own `*.memory.process.size` property. Those properties move down
with the limits.

Not verified — needs a real Codespace:

1. Whether Docker is usable in `updateContentCommand` (above)
2. Whether the ~14 GB budget actually holds through Step 5, and whether
   Flink ingest still completes with 2560m across 4 slots
3. Whether ~19 GB of images and data fits the 32 GB disk
4. Whether Superset and LibreChat work behind the Codespaces auth proxy
5. Whether the QR scanner's `getUserMedia` works on the forwarded https origin
6. The ~51 `localhost` references in `docs/` and `site/src/content/docs/`, which
   still tell attendees the wrong URL — unaddressed here
7. Cost per attendee for a 4-core machine over a session

## Checklist for the trial run

```
Steps 0-2   task up:docs / up:ingest / data:prepare / catalog:create
            flink:job / up:query / trino:views
Step 3      paste LLM_API_KEY into .env, task llm:check, task up:chat
Steps 4-5   task up:mcp, then the agent exercises in docs/05-agent.md
```

Record wall-clock from *Create codespace* to a working Step 1, and compare it
against a cold laptop on conference-grade wifi. That number is the decision.
