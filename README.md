# PCB-Inspect

Local, on-premise software for automated PCB defect inspection. A trained YOLO11x model detects six defect types on printed circuit boards (missing hole, mouse bite, open circuit, short, spur, spurious copper) directly from images saved locally by a production-line camera; an AI agent pipeline turns each detection into an interpreted technical analysis (cause, impact, suggested fix).

This is **not** a hosted web platform — it runs entirely on the machine(s) responsible for the inspection station, with every service bound to `localhost`. See section 3.1 of the PRD for the full rationale.

Full requirements, architecture, and data model: [pcb-inspect-product-requirements-document.md](pcb-inspect-product-requirements-document.md).

## Status

Portfolio project. The model has been trained and locally validated; implementation follows the phased plan in PRD section 15 (Phase 1: inspection core with no LLM required).

## Installing (inspection station)

Install a container runtime — Docker Desktop on Windows, Docker Engine + the Compose plugin on Linux — then run the installer for the machine's OS from the [releases page](https://github.com/arthursantos67/PCB-inspect/releases):

| OS | File |
|---|---|
| Windows 10/11 | `.exe` (recommended) or `.msi` |
| Debian/Ubuntu | `.deb` |
| Other Linux | `.AppImage` |

That is the entire setup. On its first launch the launcher creates its own install directory, generates `.env` with random secrets, downloads the inspection model, pulls the published images and starts the stack — nothing is built on the operator's machine, and no file is edited by hand. Daily operation is one double-click; see [launcher/README.md](launcher/README.md) (FR-20, NFR-07).

Everything is local-only either way: every published port binds to `127.0.0.1`, nothing is exposed to the network.

## Getting started (development)

Requires Docker and Docker Compose.

```bash
cp .env.example .env   # adjust WATCH_ROOT_HOST_PATH, POSTGRES_*, LLM_* as needed
docker compose up --build
```

`.env.example` sets `COMPOSE_FILE` so a checkout automatically layers three files:

| File | Role |
|---|---|
| `docker-compose.yml` | the stack an installed machine runs: published images, no `build:` sections. Embedded in the launcher binary and written out on install, so it is the single source of truth |
| `docker-compose.build.yml` | adds `build:` to every service, so a checkout builds from source instead of pulling |
| `docker-compose.dev.yml` | runs the frontend from the `dev` stage with the source bind-mounted — edits hot-reload, no image rebuild |

Drop `docker-compose.dev.yml` from `COMPOSE_FILE` to run the production frontend image (a `next build` standalone server) locally instead.

This brings up eight services: `api` (FastAPI, `127.0.0.1:8000`), `frontend` (Next.js, `127.0.0.1:3000`), `worker-inference`, `worker-agents`, and `worker-housekeeping` (Celery workers — housekeeping covers watch-mode ingestion, alerting, and retention, kept independent from the LLM-dependent agents worker), `beat` (Celery periodic tasks), `db` (PostgreSQL 16, `127.0.0.1:5432`), and `redis` (`127.0.0.1:6379`).

Once running:
- `http://localhost:3000` — dashboard placeholder
- `http://localhost:8000/health` — per-dependency status (db, redis, worker, watch-root, llm)
- `http://localhost:8000/api/docs` — Swagger UI (`/api/schema` for the raw OpenAPI document)

### Required environment variables

See `.env.example` for the full list and defaults. The ones you're most likely to change:

| Variable | Purpose |
|---|---|
| `WATCH_ROOT_HOST_PATH` | Host directory the camera/production line writes images to (mounted read-only). Only the initial default — the operator changes the watch root from Settings > Ingestion, no restart or `.env` edit needed |
| `HOST_FS_SOURCE` / `HOST_FS_ROOT` / `HOST_FS_MOUNT` | Host filesystem exposed read-only to the backend containers, so any folder on the machine can be chosen as the watch root from the UI. `HOST_FS_SOURCE` is the bind source in the host's own path syntax (`/` on Linux, `C:/Users/<you>` on Windows); `HOST_FS_ROOT` is the POSIX prefix the backend maps that mount back to when displaying paths. Narrow `HOST_FS_SOURCE` (e.g. to `/home`) to restrict what the containers can read |
| `PCB_INSPECT_REGISTRY` / `PCB_INSPECT_VERSION` | Which published images the stack runs. Only used when `docker-compose.build.yml` is out of `COMPOSE_FILE`; the launcher rewrites these to match its own version on every launch |
| `APP_DATA_HOST_PATH` | Host directory for the database volume, annotated images, reports, uploaded model weights (writable) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | PostgreSQL credentials |
| `SECRET_KEY` | Session/token signing key — set to a random value outside of local dev |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | AI agent pipeline provider (local LM Studio/Ollama by default, section 5.2 of the PRD); no key is required to run or evaluate the project |

GPU passthrough for `worker-inference` (NVIDIA Container Toolkit) is documented but commented out in `docker-compose.yml` — optional locally, the worker falls back to CPU.

## Database

The `api` container applies Alembic migrations and runs the dev seed automatically on startup (a local dev account, default `SystemConfig` values, and `ModelVersion v1.0.0` registered from `weights/best.pt` — PRD section 14.3). To run either manually against a running stack:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m app.db.seed
```

To create a new migration after changing a model in `backend/app/models/`:

```bash
docker compose exec api alembic revision --autogenerate -m "describe the change"
```

## Model weights

`weights/best.pt` is not tracked in this repository (114 MB, over GitHub's 100 MB limit — and model binaries generally don't belong in git history). An installed system downloads it on first launch from the `model-v1` release asset, so this section only concerns a checkout. To obtain it:

- Download directly: `gdown --fuzzy https://drive.google.com/file/d/1PmHc25ne_8U5Buoi5bvyq9G1K2jsAadz/view?usp=sharing -O weights/best.pt`
- Or retrain from scratch using the [training notebook](https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing).

The running application never needs this file replaced by hand: a `.pt` produced by the notebook is uploaded from Settings > Models, which copies it into the app-data volume, evaluates it against the golden set, and only then lets it be activated (FR-12). The AI model screen (`/model`) explains what the model detects and how it was trained, and links back to the notebook.

## Training dataset

Based on the [PCB Defects dataset](https://www.kaggle.com/datasets/akhatova/pcb-defects) (Kaggle), augmented with Roboflow/Albumentations. See PRD section 4.1 and 4.3 for metrics and known limitations.

## Releasing

`.github/workflows/release.yml` runs on a `v*` tag and produces everything an install needs:

1. `ghcr.io/<owner>/pcb-inspect-backend` and `-frontend`, tagged with the release version and `latest`.
2. The Linux (`.deb`, `.AppImage`) and Windows (`.exe`, `.msi`) installers, each built on its own runner, with the tag's version stamped into the launcher so it pulls the images published in step 1.
3. A GitHub release with the installers attached.

```bash
git tag v1.0.0 && git push origin v1.0.0
```

A `workflow_dispatch` run builds the same bundles as workflow artifacts without creating a release — use it to smoke-test packaging changes. The model weight is published separately and by hand, as an asset of the `model-v1` release, because it changes on a retraining schedule rather than an application one.
