# PCB-Inspect Native Launcher

Implements FR-20 / PRD section 3.8: the daily operator never types a command, opens a
terminal, or navigates a browser. They double-click one icon and land on the dashboard.

The launcher is a thin native shell — it does not reimplement the backend. It always shells
out to the same `docker compose` stack described in the root [README](../README.md) and
`docker-compose.yml`.

```
launcher/
  core/       pcb-launcher-core — orchestration logic (Docker checks, compose up/stop,
              /health polling, state machine). No GUI dependency; plain `cargo test`.
  src-tauri/  pcb-inspect-launcher — the Tauri v2 app: splash/error window, tray menu,
              wires launcher-core into an actual desktop window.
```

## Two separate moments (NFR-07)

**One-time technical setup** — two steps, neither of which involves a terminal:

1. Install a container runtime: Docker Desktop on Windows, Docker Engine + the Compose plugin
   on Linux. NFR-07 explicitly excludes this one-time runtime install from the zero-command
   criterion, and PRD section 15 keeps the container runtime out of scope for removal.
2. Run the PCB-Inspect installer for the OS (`.exe`/`.msi` on Windows, `.deb`/`.AppImage` on
   Linux) from the [releases page](https://github.com/arthursantos67/PCB-inspect/releases).

Everything the old setup list asked for — placing a project directory, copying `.env.example`,
inventing a `SECRET_KEY` and a database password, `docker compose build`, downloading the
114 MB model weight, putting the binary next to `docker-compose.yml` — is done by the launcher
itself on first run (`core/src/bootstrap.rs`).

**Daily operation** — this is the entire operator workflow, every day:

1. Double-click the PCB-Inspect icon.
2. Wait a few seconds while it starts (or skip the wait if it's already running).
3. Use the dashboard.

No terminal, no command, no typed address, ever.

## First run: what the launcher provisions

On the first launch (and idempotently on every one after), the launcher creates its own
install directory — `~/.local/share/PCB-Inspect` on Linux, `%LOCALAPPDATA%\PCB-Inspect` on
Windows — and fills it in:

```
PCB-Inspect/
  docker-compose.yml   embedded in the binary (`include_str!`), written out verbatim
  .env                 generated once, chmod 0600: random SECRET_KEY (64 hex) and database
                       password (32 hex), ports, paths, LLM defaults
  app-data/            APP_DATA_HOST_PATH — images, reports, exports
  watch-root/          WATCH_ROOT_HOST_PATH — the default watched folder
  weights/best.pt      downloaded from the `model-v1` release asset (~114 MB, once)
```

Then it pulls `pcb-inspect-backend`/`pcb-inspect-frontend` at the launcher's own version from
GHCR (nothing is ever built on the operator's machine) and starts the stack. The splash shows
each of these as its own state, with a real progress bar for the model download.

`.env` belongs to the operator from the moment it is written: an upgrade fills in keys a newer
version added, but only ever rewrites `PCB_INSPECT_REGISTRY` and `PCB_INSPECT_VERSION`, so a
changed port or LLM endpoint survives. Set `PCB_INSPECT_WEIGHTS_URL` to point the download at
a local mirror for an offline install.

## How it finds the stack

Two modes, decided by where the executable finds itself (`resolve_layout` in
`core/src/bootstrap.rs`):

- **Managed** — nothing next to the executable, which is the case for every real installation.
  The launcher owns the install directory described above and generates what is missing.
- **External** — `PCB_LAUNCHER_PROJECT_DIR` is set, or `docker-compose.yml` already sits next
  to the executable. Those files belong to whoever put them there, so the launcher reads them
  and writes nothing: this is what keeps a developer checkout (and the pre-installer layout,
  where the binary was copied next to the compose file) working unchanged. A checkout is also
  detected as building from source — `COMPOSE_FILE` includes `docker-compose.build.yml` — so
  no image pull is attempted there.

Either way a missing `docker-compose.yml` produces an actionable error in the window instead
of a silent hang or crash (Error Visibility AC).

## Update and uninstall

**Update:** install the newer release over the old one. The version is compiled into the
binary and rewritten into `.env` on the next launch, so the launcher pulls the matching images
itself; the install directory, the database volume and `.env` are untouched. Migrations run at
API startup as usual.

**Uninstall:** removing the package (`apt remove pcb-inspect-launcher`, deleting the AppImage,
or Windows' Apps & features) removes the application only. It deliberately leaves behind:

- the install directory, with `.env`, `app-data/`, `watch-root/` and the model weight;
- the `db_data` Docker volume holding the Postgres database.

Inspection history and reports outlive the application, and an uninstall is not the operator's
way of saying "delete the production data". To also discard those, after uninstalling:

```bash
cd ~/.local/share/PCB-Inspect   # %LOCALAPPDATA%\PCB-Inspect on Windows
docker compose down -v          # containers + database volume
cd .. && rm -rf PCB-Inspect     # data, reports, .env, weights
```

## Startup flow

1. **Preparing install** — creates/refreshes the install directory described above. A failure
   here (no disk space, an unwritable data directory) is a terminal state with a retry button
   that re-runs provisioning too, not just the start.
2. **Checking runtime** — runs `docker info`; a missing/stopped Docker daemon produces an
   actionable error state (with the retry button re-running the whole flow), not a hang.
3. **Downloading the model** — only when `weights/best.pt` isn't there yet. Streams to a
   `.part` file and renames on success, so an interrupted download never leaves a truncated
   weight that the inference worker would load and fail on. Reports byte progress to the
   splash; a failure is terminal (`ModelUnavailable`) and stops before anything is started.
4. **Pulling images** — only when an image the compose file references is missing locally
   (`docker image inspect`), so a warm start never touches the network. Skipped entirely in a
   checkout, which builds from source.
5. **Cold vs warm start** — `docker compose ps --status running` is checked to decide which
   message to show ("Starting…" vs "Already running…"), but `docker compose up -d` always
   runs either way. Compose's own idempotency (not custom duplicate-detection) is what
   actually guarantees the Warm Start acceptance criterion — running `up -d` against an
   already-running stack is a safe no-op, so a wrong guess in step 5 can never create
   duplicate containers.
6. **Waiting for health** — polls `GET /health` (`backend/app/core/health.py`) every 1.5s up
   to a 120s timeout, until it reports `"status": "ok"` (an unconfigured LLM already reports
   `not_configured`, which the backend itself folds into `"ok"` — matching Phase 1's
   no-LLM-required demo).
7. **Ready** — the same window navigates directly to the running frontend
   (the `FRONTEND_PORT` from `.env`, `http://127.0.0.1:3000` by default). No browser chrome at any point: Tauri windows never have an
   address bar or browser UI to begin with.

## Webview constraints the app has to design around

The window is a real webview (WebView2 on Windows, WebKitGTK on Linux), not a browser tab, and
two things behave differently there:

- **Drag and drop** is intercepted by Tauri's own native file-drop handler by default, which
  swallows the HTML `drop` event entirely. `dragDropEnabled: false` in `tauri.conf.json` turns
  that off so the ingestion dropzone receives web drops as it does in a browser. Changing this
  requires rebuilding the launcher binary — it is compiled into the app, not read at runtime.
- **Folder picking via `<input webkitdirectory>` can't be relied on**: WebKitGTK exposes the
  attribute but its native chooser still offers files only, so a "choose folder" button built
  that way silently degrades to picking individual images. This is why ad hoc folder import
  goes through the backend instead (`POST /api/v1/inspections/import-folder` + the host folder
  browser), reading the folder in place off the host mount.
- **There is no reload of the webview's own**: no address bar, no context-menu entry, no
  default F5 binding, so a window that loaded the dashboard before a `docker compose up -d
  --build` keeps showing the previous version. The launcher supplies its own: **Ctrl+R** or
  **F5** inside the window (injected on every page load by `on_page_load`), and **Reload
  Dashboard** in the tray menu. Prefer the keyboard one when reporting steps to a user: GNOME
  hides tray icons unless an AppIndicator extension is installed, which makes the whole tray
  menu unreachable there.

## Lifecycle

- **Closing the window** (the X button) hides it; it does **not** stop the backend stack or
  quit the launcher process. Rationale: an operator accidentally closing the window shouldn't
  interrupt an inspection run in progress. Re-opening from the tray icon is then instant
  (stack already up).
- **Tray icon** exposes four actions: **Show Dashboard** (re-show/focus the window),
  **Reload Dashboard** (re-navigates the window to the frontend URL, for picking up a rebuilt
  frontend), **Stop Stack** (`docker compose stop` — stops containers without removing them, so
  the next start is fast), and **Quit Launcher** (exits the app process; does *not* stop the
  stack — use "Stop Stack" first if that's what you want). On desktops that hide tray icons
  (GNOME without an AppIndicator extension) none of these are reachable, so the window's own
  Ctrl+R/F5 is the reliable reload.

## Building

Requires a Rust toolchain. `core/` alone has no other system requirements. `src-tauri/` also
needs Tauri's platform prerequisites (WebView2 on Windows — already present on any modern
Windows install; `libwebkit2gtk-4.1-dev` and friends on Linux, see
[Tauri's prerequisites guide](https://v2.tauri.app/start/prerequisites/)).

```bash
cd launcher

# Orchestration logic only — no GUI deps, works anywhere with just `cargo`:
cargo test -p pcb-launcher-core

# Run the actual app against this repo checkout (external mode: reads the checkout's
# docker-compose.yml and .env, provisions nothing, pulls nothing):
PCB_LAUNCHER_PROJECT_DIR=.. cargo run -p pcb-inspect-launcher

# Exercise the real first-run provisioning without touching your own install directory:
XDG_DATA_HOME=/tmp/pcb-launcher-demo cargo run -p pcb-inspect-launcher

# Produce the installers for the current OS (requires
# `cargo install tauri-cli --version "^2.0.0" --locked`). The v2 CLI has no
# --manifest-path, so it is run from the Tauri crate:
cd src-tauri && cargo tauri build
```

`cargo tauri build` writes to `launcher/target/release/bundle/` (the cargo *workspace* target
directory, not `src-tauri/target/`) — `deb/` and `appimage/` on Linux, `nsis/` and `msi/` on
Windows. Cross-compiling is not attempted: each OS's bundle is
built on its own runner in `.github/workflows/release.yml`.

The AppImage target is the fussy one: `linuxdeploy` and `appimagetool` are themselves
AppImages, so they need FUSE 2 (`libfuse2` on Debian/Ubuntu, `fuse-libs` on Fedora) or
`APPIMAGE_EXTRACT_AND_RUN=1` to run at all, and on distributions with very recent binutils
their strip pass can fail, which `NO_STRIP=1` skips. The release workflow installs `libfuse2`
and sets the first variable; the `.deb` target needs neither.

The `.deb` deliberately declares **no dependency on Docker**. The package name differs per
distribution and installation method (`docker-ce`, `docker.io`, `docker-desktop`,
`moby-engine`), so a hard dependency would make the package uninstallable on perfectly valid
machines. The launcher detects the runtime at startup and says exactly what is missing
instead.

## What's tested automatically vs. manually verified

Native GUI shells are inherently harder to unit-test than backend logic — there's no display
in most CI runners, and no way to script "does the tray menu look right." Coverage here is
split deliberately along that line:

**Automated (`cargo test`, runs in CI on every PR — `.github/workflows/ci.yml`'s
`launcher-core-test` job):**
- Cold start reaching `Ready` when Docker and `/health` both succeed.
- Warm start (`docker compose ps` already reports running) still calls `up -d` (the actual
  duplicate-container guard) and skips straight past the "starting" message.
- Missing Docker binary and a stopped Docker daemon both surface as `RuntimeUnavailable`
  with an actionable message (Error Visibility).
- `docker compose up -d` failing (non-zero exit) is reported and short-circuits before any
  health polling.
- `/health` retries (unreachable → degraded → ok) before reaching `Ready`.
- `/health` never succeeding within the timeout produces `HealthTimedOut`, not an infinite
  hang.
- `docker compose stop` (the tray's Stop Stack action) succeeding and failing.
- First run in an empty data directory writes `docker-compose.yml` and a `.env` whose
  `SECRET_KEY` and database password are random, distinct per install, and threaded into
  `DATABASE_URL`.
- A second launch keeps an operator's edited `.env` values but re-pins the image version.
- A checkout (compose file next to the executable, `PCB_LAUNCHER_PROJECT_DIR`) is detected as
  external and nothing is generated or overwritten.
- Images are pulled only when missing, and a failed pull stops before `up -d`.
- The model weight is downloaded once with progress; an existing file is never re-downloaded,
  and a failed download is terminal and stops before `up -d`.
- The embedded compose file is the one this repo ships, and carries no `build:` section (the
  guard against an install pointing at images that were never published).

**Compiled in CI, not run (`launcher-build` job, ubuntu-latest with the real Tauri Linux
deps):** the `src-tauri` crate — tray menu wiring, window events, Tauri commands — is
type-checked against the real `tauri` v2 API on every PR. This catches API-usage mistakes at
compile time but doesn't execute the app (no display in CI).

**Packaging (`.github/workflows/release.yml`, on a `v*` tag or `workflow_dispatch`):** builds
the Linux and Windows installers on their own runners, publishes the two container images to
GHCR under the same version, and attaches the bundles to the GitHub release. A manual run
builds and uploads the bundles as artifacts without creating a release, which is the way to
smoke-test packaging changes before tagging.

**Manually verified, not automated:** the actual double-click experience — splash animation,
window appearance with no browser chrome, tray icon interaction, closing/re-opening behavior,
and a real `/health` transition from a genuinely cold Docker Desktop. This needs a machine
with a display and Docker installed; do a real cold-start/warm-start/stop-Docker-and-retry
pass on the target OS before relying on this in production. The same applies to a real first
install: run the built installer on a machine that has never had PCB-Inspect, with the images
actually published, and confirm the operator gets from double-click to dashboard without a
terminal.
