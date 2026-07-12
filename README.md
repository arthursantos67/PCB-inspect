# PCB-Inspect

Local, on-premise software for automated PCB defect inspection. A trained YOLO11x model detects six defect types on printed circuit boards (missing hole, mouse bite, open circuit, short, spur, spurious copper) directly from images saved locally by a production-line camera; an AI agent pipeline turns each detection into an interpreted technical analysis (cause, impact, suggested fix).

This is **not** a hosted web platform — it runs entirely on the machine(s) responsible for the inspection station, with every service bound to `localhost`. See section 3.1 of the PRD for the full rationale.

Full requirements, architecture, and data model: [pcb-inspect-product-requirements-document.md](pcb-inspect-product-requirements-document.md).

## Status

Portfolio project. The model has been trained and locally validated; implementation follows the phased plan in PRD section 15 (Phase 1: inspection core with no LLM required).

## Getting started

Requires Docker and Docker Compose. Everything below is local-only: every published port binds to `127.0.0.1`, nothing is exposed to the network.

```bash
cp .env.example .env   # adjust WATCH_ROOT_HOST_PATH, POSTGRES_*, LLM_* as needed
docker compose up
```

For the target production-line persona (NFR-07), this `docker compose up` step is a one-time
technical setup detail, not something the daily operator ever types — see
[launcher/README.md](launcher/README.md) for the native launcher (FR-20) that turns daily
operation into a single double-click.

This brings up eight services: `api` (FastAPI, `127.0.0.1:8000`), `frontend` (Next.js, `127.0.0.1:3000`), `worker-inference`, `worker-agents`, and `worker-housekeeping` (Celery workers — housekeeping covers watch-mode ingestion, alerting, and retention, kept independent from the LLM-dependent agents worker), `beat` (Celery periodic tasks), `db` (PostgreSQL 16, `127.0.0.1:5432`), and `redis` (`127.0.0.1:6379`).

Once running:
- `http://localhost:3000` — dashboard placeholder
- `http://localhost:8000/health` — per-dependency status (db, redis, worker, watch-root, llm)
- `http://localhost:8000/api/docs` — Swagger UI (`/api/schema` for the raw OpenAPI document)

### Required environment variables

See `.env.example` for the full list and defaults. The ones you're most likely to change:

| Variable | Purpose |
|---|---|
| `WATCH_ROOT_HOST_PATH` | Host directory the camera/production line writes images to (mounted read-only) |
| `APP_DATA_HOST_PATH` | Host directory for the database volume, annotated images, reports, exports (writable) |
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

`weights/best.pt` is not tracked in this repository (114 MB, over GitHub's 100 MB limit — and model binaries generally don't belong in git history). To obtain it:

- Download directly: `gdown --fuzzy https://drive.google.com/file/d/1PmHc25ne_8U5Buoi5bvyq9G1K2jsAadz/view?usp=sharing -O weights/best.pt`
- Or retrain from scratch using the [training notebook](https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing).

## Training dataset

Based on the [PCB Defects dataset](https://www.kaggle.com/datasets/akhatova/pcb-defects) (Kaggle), augmented with Roboflow/Albumentations. See PRD section 4.1 and 4.3 for metrics and known limitations.
