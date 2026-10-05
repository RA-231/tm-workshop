# Running this workshop on Windows

> **We haven't tried this, so no promises.** The workshop is built and rehearsed
> on macOS, and the task runner and helper scripts assume a Unix shell. What
> follows is the areas where you're most likely to run into trouble and what's
> commonly done to get past them. Some of it is informed guesswork rather than
> something we've watched work on a Windows laptop.
>
> If you get stuck, grab a facilitator. Give the section number below (such as
> **W.4**), the command you ran, and the error.

Sections here are numbered **W.n** so they don't collide with the workshop's own
numbering in [docs/](docs/00-overview.md).

## W.1 — The short version: run it inside WSL2

The containers themselves don't care what your host is — they're all Linux
images. What assumes Unix is the layer *driving* them: [Task](https://taskfile.dev)
shells out to `bash` for the setup scripts, and those scripts use `curl`, `awk`,
`tar`, and friends.

Inside [WSL2](https://learn.microsoft.com/windows/wsl/install) that layer is
simply Linux, so the repo should work unmodified. Docker Desktop on Windows
already runs on the WSL2 backend, so you very likely have it installed.

1. Install WSL2 with a distribution, then reboot if prompted.

   ```powershell
   wsl --install -d Ubuntu
   ```

2. In **Docker Desktop → Settings → Resources → WSL Integration**, enable
   integration for that distribution. Without this, `docker` isn't on your PATH
   inside the distro.

3. Open the Ubuntu terminal and confirm Docker is reachable from inside it.

   ```bash
   docker version
   ```

4. Install the workshop's two host-side tools.

   ```bash
   sudo apt update && sudo apt install -y python3 git
   sudo snap install task --classic
   ```

   If `snap` isn't available, see [taskfile.dev](https://taskfile.dev) for the
   other install methods.

5. Clone and run the workshop from the Ubuntu terminal, following
   [docs/00-overview.md](docs/00-overview.md) exactly as written. Read **W.2**
   first — *where* you clone matters more than you'd expect.

Everything below is a rough edge you may hit even after doing this.

## W.2 — Clone inside the Linux filesystem, not `/mnt/c`

This is the single highest-impact thing on this page.

WSL2 can reach your Windows drives at `/mnt/c/...`, but that path crosses a
filesystem translation boundary, and per-file operations across it are slow.
The workshop pushes a lot of small files across bind mounts: `task data:prepare`
writes one JSON file per channel, and Flink then reads that directory file by
file. On `/mnt/c` this can turn minutes into much longer.

Clone into your Linux home directory instead:

```bash
cd ~
git clone <this-repo>
```

Symptom if you get this wrong: nothing errors, `task data:prepare` and
`task flink:job` are just dramatically slower than the workshop allows for.

You can still edit the files from Windows — VS Code's
[WSL extension](https://code.visualstudio.com/docs/remote/wsl) opens the Linux
filesystem directly, and `\\wsl$\Ubuntu\home\<you>\` works in Explorer.

## W.3 — Give WSL2 enough memory

The workshop asks for about 8 GB of RAM available to Docker. On Windows that's
a WSL2 setting, not a Docker Desktop slider. WSL2 defaults to a fraction of
total RAM, which may be under what the full stack needs.

Create or edit `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=4
```

Then restart WSL from PowerShell:

```powershell
wsl --shutdown
```

Symptom if this is too low: containers are killed mid-run, most likely Flink
during `task flink:job` or Superset during `task up:query`.

## W.4 — Ports Windows has already reserved

Windows reserves blocks of TCP ports for its own use, and those blocks often
include ports this workshop wants — 8080 (Trino) and 3080 (LibreChat) are
common casualties.

This is **not** the same failure as the one in
[0.6 — Resolve a host-port conflict](docs/00-overview.md#06--resolve-a-host-port-conflict).
There, `docker ps` shows you the container holding the port. Here nothing holds
it and the error is a permissions message rather than `port is already
allocated`:

```
bind: An attempt was made to access a socket in a way forbidden by its access permissions
```

List the reserved ranges from PowerShell:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

Commonly done to get past it, roughly in order of preference:

1. Restart the Windows NAT service, which often releases the ranges. From an
   **administrator** PowerShell:

   ```powershell
   net stop winnat
   net start winnat
   ```

2. Reboot. The reserved ranges are chosen at boot and frequently differ after.
3. Change the host port in `docker-compose.yml` — edit only the left-hand side
   of a mapping such as `"8080:8080"`, and tell your facilitator so the URLs in
   the docs can be adjusted for you.

## W.5 — Line endings

The repo ships a [`.gitattributes`](.gitattributes) that forces LF on checkout,
so a fresh clone should be fine. This section is for the case where it isn't.

The failure is confusing rather than obvious: several scripts are copied into
container images and executed there, so a CRLF checkout bakes a carriage return
into the image. `superset/bootstrap.sh` is the Superset image's entrypoint, so
the symptom is a container that exits immediately at `task up:query` and
complains it can't find a file that is visibly present. Host-side scripts fail
with `$'\r': command not found`.

If you cloned before `.gitattributes` existed, the simplest fix is to delete the
clone and clone again. To repair the clone you have instead, re-checkout every
file with the new rules applied:

```bash
git rm --cached -r .
git reset --hard
```

That **discards any uncommitted edits to tracked files**, so check `git status`
first. Your `.env` is gitignored, so the workshop key you pasted in survives
either way.

Either way, rebuild the affected image afterwards so the CRLF copy baked into
it isn't reused:

```bash
docker compose build --no-cache superset
```

**Also: don't edit `.env` in Notepad.** It writes CRLF, and a trailing carriage
return on `LLM_API_KEY` travels into the HTTP `Authorization` header. The
result is a 401 that looks exactly like a bad key, which will send you chasing
the wrong problem in Step 3. Use the VS Code WSL extension, or `nano .env`
inside the distro.

## W.6 — `python3` vs `python`

The [Taskfile](Taskfile.yml) calls `python3` for `task data:download`,
`task up:chat`, and `task up`. In WSL2 Ubuntu that's the normal name and you
installed it in **W.1**. On native Windows, Python installs as `python.exe`
with a `py` launcher, and `python3` often doesn't resolve at all.

## W.7 — If you want to avoid WSL2 entirely

Running from Git Bash or MSYS2 on native Windows is not something we've tried,
and we'd steer you to WSL2 for a 3-hour workshop. If you want to attempt it
anyway, these are the places we expect you'd have to intervene:

1. **`bash` and the Unix utilities must be on PATH.** The Taskfile runs
   `bash scripts/*.sh` for Garage init, catalog creation, the table-loaded
   check, and checkpoints. Those scripts use `set -euo pipefail` plus `seq`,
   `awk`, `curl`, `tar`, `du`, and `cut`. Task parses POSIX shell syntax on its
   own, but it does not supply these binaries. Git Bash provides most of them.
2. **`python3`** — see **W.6**.
3. **`date -u +FORMAT`.** The ingest job stamps its provenance columns
   (`run_id`, `ingest_ts`) from `date` output. A `date` that doesn't accept
   GNU-style format strings will break `task flink:job`.
4. **Docker path translation.** `scripts/checkpoint.sh` passes `$PWD` into a
   `docker run -v` flag. MSYS rewrites Unix-looking paths on the way to
   `docker.exe`, which usually needs `MSYS_NO_PATHCONV=1` or `$(pwd -W)`. This
   affects `task checkpoint:restore`, the catch-up path if you fall behind.
5. **Interactive sessions.** `task trino` attaches to a container TTY. Under Git
   Bash this commonly needs a `winpty` prefix.

## W.8 — What should work the same as everywhere else

1. Every service in the stack — Garage, Polaris, Flink, Trino, Superset,
   LibreChat, LiteLLM, and the MCP servers — runs from a Linux container image
   and is unaffected by the host OS.
2. All the browser UIs. The links in [the service page](http://localhost:4321)
   and throughout the docs are plain `localhost` URLs.
3. The QR credential scanner at
   [http://localhost:4321/creds/](http://localhost:4321/creds/) used in
   [3.3.1](docs/03-chat.md). It decodes in the browser and works in Edge or
   Chrome; `localhost` counts as a secure context, so camera access is allowed.

## W.9 — Telling us it went wrong

If you hit something not covered here, we'd genuinely like to know — this page
is written from inspection rather than experience, and a Windows attendee's
account is worth more than our guesses. Tell a facilitator what you ran, what
you expected, and what you got.
