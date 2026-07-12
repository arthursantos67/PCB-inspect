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

**One-time technical setup** — done once by whoever installs the inspection station
(IT staff or the integrator), *not* the daily operator:

1. Install Docker Desktop (or Docker Engine + Compose plugin) on the machine.
2. Put the PCB-Inspect project directory somewhere permanent, e.g. `C:\PCB-Inspect\`
   (a checkout of this repo, or an install package containing the same files).
3. `cp .env.example .env` and fill in `POSTGRES_*`, `SECRET_KEY`, `WATCH_ROOT_HOST_PATH`,
   `LLM_*` — see the root README's "Required environment variables".
4. `docker compose build` once, so the daily `docker compose up -d` the launcher runs never
   has to rebuild images.
5. Install the launcher (run the installer from a packaged release, or build it yourself —
   see "Building" below) so `pcb-inspect-launcher.exe` sits **next to** `docker-compose.yml`
   and `.env` in the project directory from step 2. That's how the launcher finds the stack
   at daily-startup time (see "How it finds the stack" below) — no config file to fill in.

**Daily operation** — this is the entire operator workflow, every day:

1. Double-click the PCB-Inspect icon.
2. Wait a few seconds while it starts (or skip the wait if it's already running).
3. Use the dashboard.

No terminal, no command, no typed address, ever.

## How it finds the stack

`LauncherConfig::resolve` (`core/src/config.rs`) looks for `docker-compose.yml` in the
directory containing the launcher executable (overridable via `PCB_LAUNCHER_PROJECT_DIR`,
used for development — see "Building" below). If it's not there, the app still opens and
shows an actionable error instead of a silent hang or crash (Error Visibility AC).

## Startup flow

1. **Checking runtime** — runs `docker info`; a missing/stopped Docker daemon produces an
   actionable error state (with the retry button re-running the whole flow), not a hang.
2. **Cold vs warm start** — `docker compose ps --status running` is checked to decide which
   message to show ("Starting…" vs "Already running…"), but `docker compose up -d` always
   runs either way. Compose's own idempotency (not custom duplicate-detection) is what
   actually guarantees the Warm Start acceptance criterion — running `up -d` against an
   already-running stack is a safe no-op, so a wrong guess in step 2 can never create
   duplicate containers.
3. **Waiting for health** — polls `GET /health` (`backend/app/core/health.py`) every 1.5s up
   to a 120s timeout, until it reports `"status": "ok"` (an unconfigured LLM already reports
   `not_configured`, which the backend itself folds into `"ok"` — matching Phase 1's
   no-LLM-required demo).
4. **Ready** — the same window navigates directly to the running frontend
   (`http://127.0.0.1:3000`). No browser chrome at any point: Tauri windows never have an
   address bar or browser UI to begin with.

## Lifecycle

- **Closing the window** (the X button) hides it; it does **not** stop the backend stack or
  quit the launcher process. Rationale: an operator accidentally closing the window shouldn't
  interrupt an inspection run in progress. Re-opening from the tray icon is then instant
  (stack already up).
- **Tray icon** exposes three actions: **Show Dashboard** (re-show/focus the window),
  **Stop Stack** (`docker compose stop` — stops containers without removing them, so the next
  start is fast), and **Quit Launcher** (exits the app process; does *not* stop the stack —
  use "Stop Stack" first if that's what you want).

## Building

Requires a Rust toolchain. `core/` alone has no other system requirements. `src-tauri/` also
needs Tauri's platform prerequisites (WebView2 on Windows — already present on any modern
Windows install; `libwebkit2gtk-4.1-dev` and friends on Linux, see
[Tauri's prerequisites guide](https://v2.tauri.app/start/prerequisites/)).

```bash
cd launcher

# Orchestration logic only — no GUI deps, works anywhere with just `cargo`:
cargo test -p pcb-launcher-core

# Run the actual app against this repo checkout during development, without installing it
# next to docker-compose.yml first:
PCB_LAUNCHER_PROJECT_DIR=.. cargo run -p pcb-inspect-launcher

# Produce an installer (requires `cargo install tauri-cli --version "^2.0.0"`):
cargo tauri build --manifest-path src-tauri/Cargo.toml
```

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

**Compiled in CI, not run (`launcher-build` job, ubuntu-latest with the real Tauri Linux
deps):** the `src-tauri` crate — tray menu wiring, window events, Tauri commands — is
type-checked against the real `tauri` v2 API on every PR. This catches API-usage mistakes at
compile time but doesn't execute the app (no display in CI).

**Packaging (manually triggered — `.github/workflows/launcher-package.yml`,
`workflow_dispatch`):** builds an actual Windows installer (`cargo tauri build`) and uploads
it as a workflow artifact. Not run on every push (a full release build is too slow for that);
run it before cutting a release.

**Manually verified, not automated:** the actual double-click experience — splash animation,
window appearance with no browser chrome, tray icon interaction, closing/re-opening behavior,
and a real `/health` transition from a genuinely cold Docker Desktop. This needs a machine
with a display and Docker installed; do a real cold-start/warm-start/stop-Docker-and-retry
pass on the target OS before relying on this in production.
