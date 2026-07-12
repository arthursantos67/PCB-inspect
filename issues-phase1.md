# Phase 1 Issue Backlog — Local Software Architecture (PRD v2.0)

This file replaces the Phase-1 issue set that existed on the old GitHub repository (issues #1–#10),
adapted for the v2.0 architecture pivot: local, single-account software instead of a hosted
multi-role platform (see PRD section 3.1). Same template as before (Summary / Scope / Acceptance
Criteria), renumbered 1–10 for a fresh repository.

**What changed vs. the old issues, in one line each:**
- Issue 1 (scaffolding): drop MinIO and the nginx proxy; every service binds to `127.0.0.1` only.
- Issue 2 (data model): drop `User.role`/`is_active`; `InspectionImage` references local paths, not MinIO keys.
- Issue 3 (auth): collapses the old "JWT auth + RBAC + admin user management" issue into a much
  smaller "local account, no roles" issue.
- Issue 4 (ingestion): the biggest content change — rebuilt around directory watching/scanning
  instead of browser multipart upload, which was the old Phase-1 ingestion path.
- Issues 5–10: same shape as before, with MinIO/pre-signed-URL and role-gating language replaced by
  local-file and single-account language.

Nothing here is marked done — the previous implementation (old issues #1–#3 closed, #4 in progress)
targeted the hosted-platform architecture and does not carry over; this is a fresh Phase-1 backlog
for the new repository.

---

## Issue 1 — [Chore] Project scaffolding, Docker Compose stack, and health check

### Summary
Stand up the base repository structure for backend (FastAPI) and frontend (Next.js), wire the
Docker Compose stack for local development — bound to `127.0.0.1` only, nothing exposed to the
network — and expose a health check endpoint so every later issue has a runnable environment to
build on.

### Scope

**1. Backend Skeleton**
Initialize the FastAPI app (Python 3.12+) with the project layout implied by the PRD's
traceability matrix (`app/core`, `app/auth`, etc.), Pydantic v2 settings, and `ruff`/`mypy` config.

**2. Frontend Skeleton**
Initialize Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui, with the base `AppShell`
layout placeholder.

**3. Docker Compose Stack**
Compose services per PRD section 14.1: `api`, `worker-inference`, `worker-agents`, `beat`, `db`
(PostgreSQL 16), `redis`, `frontend`. No `minio`, no reverse proxy — every published port bound to
`127.0.0.1`. GPU passthrough for `worker-inference` documented but optional locally. The
(to-be-configured) watch root is mounted read-only; a separate writable volume holds app data
(database, annotated images, reports, exports).

**4. Health Check & OpenAPI (FR-15)**
`GET /health` checks DB, Redis, worker/model state, watch-root path accessibility, and LLM
reachability (stub LLM check acceptable at this stage). `/api/schema` and `/api/docs` exposed
automatically.

**5. CI Bootstrap (section 14.2)**
GitHub Actions workflow: backend lint (ruff) + type-check (mypy), frontend lint + type-check,
Docker image build validation for every service.

### Acceptance Criteria
- [ ] **Compose Up:** `docker compose up` brings up all services without manual steps.
- [ ] **Localhost-Only:** none of the services' ports are reachable from another machine on the
      network by default (verified by binding to `127.0.0.1`, not `0.0.0.0`).
- [ ] **Health Endpoint:** `/health` reports per-dependency status (db, redis, worker, watch-root
      path, llm).
- [ ] **OpenAPI:** `/api/schema` and `/api/docs` are reachable and reflect the current app.
- [ ] **Frontend Boots:** Next.js dev server renders a placeholder shell with no console errors.
- [ ] **CI Green:** lint/type-check/build jobs run on push/PR and pass on a clean checkout.
- [ ] **Docs:** a `README` section documents `docker compose up` and required env vars.

---

## Issue 2 — [Feature] Core data model and database migrations

### Summary
Create the SQLAlchemy 2 (async) models and Alembic migrations for the entities required by
Phase 1, so subsequent features (auth, ingestion, pipeline) have a persistence layer to build on —
`User` with no role field, and `InspectionImage` referencing local filesystem paths rather than
object-storage keys.

### Scope

**1. Phase-1 Entities**
Model `User` (no `role`, no `is_active` — section 2.2), `Batch`, `Board`, `InspectionImage`
(`original_path`/`annotated_path`, not MinIO keys), `Detection`, `Analysis`, `ModelVersion`
(`weights_path`), `SystemConfig`, `AuditLog` per PRD section 10.2. Entities needed only from
Phase 2+ (`AnalysisReview`, `BoardDisposition`, `ManualAnnotation`, `ChatSession`/`ChatMessage`,
`Report`, `DatasetExport`, `QualityAlert`) are out of scope here but should not require a breaking
schema change later.

**2. Integrity Rules**
Enforce RN-01 (confidence range, bbox ordering), RN-02 (single active `ModelVersion`), RN-03
(1:1 `Analysis`↔`InspectionImage`), RN-06 (append-only `AuditLog`, revoked UPDATE/DELETE at the DB
level) via constraints/triggers, not just application code.

**3. Migrations**
Alembic migration chain, runnable via `docker compose` and CI, idempotent on repeated
`upgrade head`.

**4. Seed Data**
Seed script for the dev environment: one local dev account, default `SystemConfig` values
(thresholds, `agent_analysis_mode=conditional`, a sample `watch_root_path`), and
`ModelVersion v1.0.0` registered from `weights/best.pt` (per section 14.3).

### Acceptance Criteria
- [ ] **Models Match PRD:** field types/nullability match section 10.2 for the Phase-1 entities.
- [ ] **No Role Field:** `User` has no `role`/`is_active` column; nothing in the schema implies a
      permission tier.
- [ ] **Local Paths, Not Object Keys:** `InspectionImage.original_path`/`annotated_path` and
      `ModelVersion.weights_path` are plain filesystem paths, with no MinIO/S3 concept anywhere in
      the schema.
- [ ] **Constraints Enforced:** DB rejects out-of-range confidence, malformed bbox, and a second
      active `ModelVersion` (RN-01, RN-02).
- [ ] **Audit Immutability:** `AuditLog` UPDATE/DELETE are rejected at the database level (RN-06).
- [ ] **Migrations Run Clean:** `alembic upgrade head` succeeds on an empty database in CI.
- [ ] **Seed Works:** dev seed creates a working local login and an active model version.
- [ ] **Tests:** constraint violations are covered by integration tests.

---

## Issue 3 — [Feature] Local authentication and account management

### Summary
Implement password-protected local login with a first-run setup flow that creates the initial
account, per FR-01/FR-02 — no roles, no admin-only provisioning, no remote registration. Any
account can manage any other account.

### Scope

**1. First-Run Setup and Login**
`POST /api/v1/auth/setup` (disabled once any account exists), `POST /api/v1/auth/login`,
`POST /api/v1/auth/refresh`, `GET /api/v1/users/me`. Passwords hashed with Argon2id; short-lived
session token with refresh (section 13).

**2. Account Management**
`GET`/`POST /api/v1/users`, `PATCH`/`DELETE /api/v1/users/{id}` — list, add, rename/change
password, and remove local accounts. No role concept anywhere; every account has identical
capabilities. Removing an account preserves the historical records it created (FK reference kept
for audit purposes, FR-16).

**3. Frontend Auth Flow**
Login screen that doubles as first-run setup when no account exists yet (FE-01); session token
kept in memory only (never `localStorage`); silent refresh before expiry; unauthenticated access
to any route beyond `/login` redirects there, preserving the originally requested path.

### Acceptance Criteria
- [ ] **First-Run Setup:** with no account in the database, `/login` offers account creation
      instead of a login form; the setup endpoint is rejected once an account exists.
- [ ] **Login:** valid credentials start a session; invalid credentials return
      `INVALID_CREDENTIALS` (401).
- [ ] **No Role Gating Anywhere:** every protected endpoint accepts any authenticated account
      equally — there is no endpoint that a valid account can be rejected from by permission tier.
- [ ] **Account Management:** any authenticated account can list, add, rename, and remove other
      accounts.
- [ ] **Audit Trail:** account creation/removal produces an immutable `AuditLog` record.
- [ ] **Frontend Guard:** unauthenticated access to a protected route redirects to `/login` and
      returns to the original path after login.
- [ ] **Tests:** setup, login, and account management have integration test coverage.

---

## Issue 4 — [Feature] Directory-based image ingestion (watch mode + one-off scan)

### Summary
Ingest PCB images primarily by reading them directly from local disk — the realistic production
scenario is a camera saving each captured board under a batch folder — instead of browser upload,
per FR-03. This replaces the old "multipart upload" issue entirely; upload is now a small secondary
path for stray files only.

### Scope

**1. Watch-Root Configuration**
A validated path field (`PathField`, FE-05) in Settings: the operator enters an absolute directory
path; the backend checks it exists and is readable before accepting it (`PATH_NOT_FOUND` /
`PATH_NOT_READABLE` otherwise). No native OS folder-picker dialog — a plain browser page cannot
open one on its own (see PRD FE-05 for why).

**2. Watch Mode (Continuous)**
A filesystem watcher on the configured root; new files are detected and ingested automatically as
the camera writes them. The convention: each immediate subdirectory of the root is one batch
(`batch_number` = subdirectory name), each image file within it is one board (`board_number` from
the filename). The original file is never moved, renamed, or deleted — ingestion state
(ingested/failed) is tracked in the database against the file's path and checksum.

**3. One-Off Directory Scan**
`POST /api/v1/inspections/scan` with an arbitrary local path: scans it once, applying the same
batch/board convention, without enabling continuous watching.

**4. Ad Hoc Import (Secondary Path)**
`POST /api/v1/inspections/import`: a small multipart endpoint for stray files not already under
the watch root (e.g., dragged in from elsewhere on the machine). Validated by magic bytes, 25 MB
max size (configurable).

**5. Validation and Deduplication**
Accepted formats JPG/PNG/TIFF/BMP; duplicate rejection via `checksum_sha256` within the same batch
(`DUPLICATE_IMAGE`, RN-04).

**6. Ingestion Frontend**
Ingestion screen (FE-05): watch-mode status (watching/paused, files discovered so far), a
"scan directory now" action, and a small drag-and-drop area for the ad hoc import path.

### Acceptance Criteria
- [ ] **Watch-Root Validation:** an invalid path (missing or unreadable) is rejected with a
      descriptive error before anything is scanned.
- [ ] **Convention Applied:** subdirectory-as-batch / filename-as-board inference is correct for a
      sample fixture directory tree.
- [ ] **No File Mutation:** after watch-mode ingestion (success or failure), every original file
      on disk is byte-for-byte unchanged, unmoved, and unrenamed.
- [ ] **Zero-Copy:** `InspectionImage.original_path` points at the file's actual location; no copy
      of the original is made anywhere on disk.
- [ ] **One-Off Scan Works:** `POST /api/v1/inspections/scan` against a fixture directory ingests
      every valid image in it.
- [ ] **Ad Hoc Import Works:** dragging a file not under the watch root into the ingestion screen
      uploads and registers it correctly.
- [ ] **Duplicate Detection:** re-ingesting the same checksum in the same batch returns
      `DUPLICATE_IMAGE` (409) / is skipped.
- [ ] **Invalid File Handling:** an unsupported/corrupted file is recorded as failed with a reason,
      without affecting ingestion of the rest of the directory.
- [ ] **Tests:** watch-mode, one-off scan, ad hoc import, and dedup all have integration coverage
      against a temporary directory fixture (no real camera required, per NFR-08).

---

## Issue 5 — [Feature] Asynchronous processing queue and state machine

### Summary
Wire the Celery/Redis task queue and the `InspectionImage` status state machine so ingested images
move through `QUEUED → PROCESSING → DETECTED → ANALYZING → COMPLETED | FAILED`, per FR-04 — the
backbone that the inference worker (Issue 6) plugs into. Unchanged in shape from the original
design; the queue exists to keep the API responsive under GPU-bound work, not for multi-user
concurrency (PRD section 3.1).

### Scope

**1. Celery Infrastructure**
Redis as broker/result backend; task definitions with `acks_late` (NFR-03) and exponential retry
(max 3 attempts) for transient failures (section 3.7).

**2. State Machine**
Enforce valid status transitions in `app/inspections/state.py`; a stage failure sets `FAILED` with
`failure_reason` persisted, and never touches the original file on disk (section 3.5).

**3. Progress Query**
`GET /api/v1/inspections/{id}` exposes current status for polling as a fallback to SSE.

**4. Worker Skeleton**
`worker-inference` and `worker-agents` Celery workers wired into Compose (from Issue 1), consuming
the queue with no-op task bodies to be filled in by Issues 6–7.

### Acceptance Criteria
- [ ] **Enqueue on Ingestion:** every file accepted by Issue 4 (watch mode, scan, or ad hoc
      import) is enqueued and reaches `PROCESSING` without manual intervention.
- [ ] **Invalid Transition Blocked:** the state machine rejects out-of-order status transitions.
- [ ] **Failure Isolation:** a forced task failure sets `FAILED` with a persisted reason; the
      original file on disk is untouched.
- [ ] **Retry Behavior:** a transient failure retries up to 3 times with backoff before marking
      `FAILED`.
- [ ] **Worker Restart Safety:** killing a worker mid-task returns the task to the queue
      (`acks_late`) instead of losing it.
- [ ] **Tests:** state transitions and retry/failure paths are covered.

---

## Issue 6 — [Feature] YOLO11x inference worker with warm start

### Summary
Run the trained YOLO11x model (`weights/best.pt`) on queued images inside the dedicated inference
worker, persist detections and the annotated image locally, per FR-05 and PRD section 4.2 (RV-01
through RV-05). Unchanged in shape from the original design.

### Scope

**1. Warm-Start Model Loading**
Load `best.pt` exactly once at worker process startup (RV-01); expose the loaded state and device
(CUDA/CPU, RV-02) via the health check (Issue 1).

**2. Detection and Persistence**
Run inference on each queued image (read directly from `InspectionImage.original_path`); persist
every detection with `confidence ≥ min_confidence_store` (default 0.25); set `is_reported = true`
for `confidence ≥ min_confidence_report` (default 0.50); both thresholds read from `SystemConfig`
(RV-03). Every `Detection` records `model_version_id` (RV-05).

**3. Annotated Image Generation**
Generate the annotated image (bounding boxes with class + confidence) and write it to the local
app-data directory, setting `InspectionImage.annotated_path` (RV-04); transition status to
`DETECTED`.

**4. No-Defect Path**
Images with no reportable detection are marked `COMPLETED` directly with "no defects detected"
(FR-05) and count positively toward the quality rate.

### Acceptance Criteria
- [ ] **Warm Start:** the model loads once per worker process; `/health` reports
      `model_loaded: true` and the active device.
- [ ] **Detections Persisted:** running inference on a known sample image persists detections
      matching the model's expected classes/confidence.
- [ ] **Threshold Behavior:** detections below `min_confidence_store` are not persisted; those
      between the two thresholds are persisted but `is_reported=false`.
- [ ] **Annotated Image:** the annotated image is written locally and retrievable, with boxes
      matching persisted detections.
- [ ] **Model Version Traceability:** every `Detection.model_version_id` matches the currently
      active `ModelVersion`.
- [ ] **No-Defect Handling:** an image with zero reportable detections reaches `COMPLETED` with an
      empty defect result.
- [ ] **Performance:** p95 inference latency meets NFR-01 (≤5s GPU / ≤20s CPU) on the dev sample
      set.
- [ ] **Tests:** inference persistence and threshold logic covered with a fixture image.

---

## Issue 7 — [Feature] Knowledge-base baseline analysis

### Summary
Publish an instant, LLM-free analysis for every reportable detection from a curated knowledge base
per defect type, per FR-06's baseline tier — the piece that lets Phase 1 run a complete demo with
no LLM configured at all. Unchanged from the original design.

### Scope

**1. Defect Knowledge Base**
Curated static content per class (`missing_hole`, `mouse_bite`, `open_circuit`, `short`, `spur`,
`spurious_copper`): description, typical causes, standard solutions, default severity
(`app/knowledge/defects.py`).

**2. Baseline Analysis Generation**
On detection completion (Issue 6), synchronously create the `Analysis` record with
`source = knowledge_base`, populating `per_defect` from the knowledge base and computing
`severity_max`; status transitions to `COMPLETED` (no `ANALYZING` stage for baseline-only per
FR-06/FR-04).

**3. Analysis Retrieval**
`GET /api/v1/analyses/{id}` and inclusion of `analysis` in `GET /api/v1/inspections/{id}`
(matching the example in section 11.5).

### Acceptance Criteria
- [ ] **Instant Availability:** every image with a reportable detection has a `COMPLETED` analysis
      with no added perceptible latency (NFR-01).
- [ ] **Correct Source Tag:** `Analysis.source = knowledge_base` when no agent chain has run.
- [ ] **Content Accuracy:** `per_defect` content matches the knowledge base entry for each
      detected class.
- [ ] **1:1 Constraint:** exactly one `Analysis` exists per `InspectionImage` (RN-03).
- [ ] **No-Defect Path:** images with no reportable detection produce no defect analysis entries.
- [ ] **API Shape:** `GET /api/v1/analyses/{id}` response matches the documented shape
      (section 11.5).
- [ ] **Tests:** baseline generation covered for each of the 6 defect classes plus the no-defect
      case.

---

## Issue 8 — [Feature] Inspection search API and real-time SSE events

### Summary
Expose paginated, filterable inspection listings (FR-07) and an authenticated SSE stream (FR-14)
so the frontend can list history and update live without polling — required by the dashboard
(Issue 9) and detail screen (Issue 10). Unchanged in shape from the original design.

### Scope

**1. Listing and Filters**
`GET /api/v1/inspections` with filters per section 11.3 (defect type, batch, board, status,
severity, date range) and default `-created_at` ordering; pagination per section 11.1 (`page`,
`page_size`, `count`/`next`/`previous`/`results`).

**2. SSE Event Stream**
`GET /api/v1/events`: authenticated stream emitting `inspection.created`, `detection.completed`,
`analysis.completed`, `inspection.failed` (the Phase-1 subset of FR-14; `alert.defect_rate` is
Phase 3). Backed by Redis pub/sub (`events:inspections`, section 3.6).

**3. Frontend SSE Hook**
`useEventStream` hook (FE-09) with automatic reconnection and backoff; SSE events invalidate the
relevant TanStack Query caches (`inspections`, `stats`).

### Acceptance Criteria
- [ ] **Filter Combinations:** each documented filter narrows results correctly, alone and
      combined.
- [ ] **Pagination:** `page`/`page_size` behave correctly at boundaries (empty page, last page).
- [ ] **Performance:** listing p95 ≤ 500 ms on the dev dataset (NFR-01).
- [ ] **SSE Auth:** unauthenticated clients cannot open the event stream.
- [ ] **Event Delivery:** ingesting an image and letting it process emits the expected event
      sequence over SSE.
- [ ] **Reconnection:** simulating a dropped SSE connection triggers automatic reconnect with
      backoff on the frontend.
- [ ] **Tests:** filter/pagination logic covered by integration tests.

---

## Issue 9 — [Feature] Dashboard with live stats and recent analyses

### Summary
Build the post-login dashboard (FE-02) backed by aggregated metrics (FR-08), giving the operator
an at-a-glance production quality view updated in real time. Unchanged from the original design.

### Scope

**1. Aggregates API**
`GET /api/v1/stats/summary`, `/stats/trends`, `/stats/by-defect-type` — total inspected, total
with defects, quality rate, count by defect type, time series by day/week/month. Cached in Redis
(`stats:summary:{period}`, TTL 60s, section 3.6); only `is_reported=true` detections feed
aggregates (RN-07).

**2. Dashboard Layout**
`StatCard` row (total inspected, defects detected, quality rate %, last-24h count),
`DefectTrendChart` (period selector 7d/30d/90d, breakdown by class), distribution bar chart,
`InspectionTable` of recent analyses with severity/status badges.

**3. Live Updates**
Dashboard queries invalidate/refresh on relevant SSE events (Issue 8) without a manual reload.

### Acceptance Criteria
- [ ] **Correct Aggregates:** stat card and chart values match a manually computed count on seed
      data.
- [ ] **RN-07 Respected:** unreported (low-confidence) detections do not affect aggregates.
- [ ] **Cache Behavior:** repeated requests within the TTL hit the Redis cache; values are
      recomputed after expiry or new data.
- [ ] **Period Selector:** switching 7d/30d/90d updates the trend chart correctly.
- [ ] **Live Update:** completing a new inspection updates the dashboard without a page refresh.
- [ ] **Performance:** aggregates endpoint p95 ≤ 800 ms with cache warm (NFR-01).
- [ ] **Accessibility:** stat cards and charts meet FE-10 baseline (contrast, text labels,
      keyboard nav).

---

## Issue 10 — [Feature] Analysis detail screen with annotated image viewer

### Summary
Build the inspection detail screen (FE-03) so the operator can open any analysis from the
dashboard or search results and inspect the annotated PCB image alongside its baseline text
analysis — closing the Phase-1 MVP loop end-to-end. Adapted from the original design: images now
serve directly from local disk instead of a pre-signed MinIO URL.

### Scope

**1. Local Image Serving**
`GET /api/v1/inspections/{id}/image?variant=original|annotated`: streams the file directly from
local disk (original path or the generated annotated path), gated only by an authenticated
session — no expiring-URL mechanism needed (section 3.1).

**2. Annotated Image Viewer**
`AnnotatedImageViewer`: zoom, pan, original/annotated toggle, numbered bounding boxes color-coded
by class with a confidence tooltip, class legend (color + text for FE-10).

**3. Detections Panel and Analysis Display**
Detections list synchronized with the viewer (hover highlights the matching bbox); baseline
analysis section showing description, probable causes, suggested solutions, severity, and
metadata (board, batch, date, model version, processing duration).

**4. Processing State Handling**
While an inspection is still `QUEUED`/`PROCESSING`/`DETECTED`, the screen shows current state and
updates live via SSE (Issue 8) instead of a static "not found."

### Acceptance Criteria
- [ ] **Viewer Renders:** zoom/pan/toggle work and bounding boxes align with detection
      coordinates.
- [ ] **Hover Sync:** hovering a detection row highlights the corresponding bbox and vice versa.
- [ ] **Analysis Content:** baseline `per_defect` content and metadata render correctly for a
      completed inspection.
- [ ] **In-Progress State:** opening a not-yet-completed inspection shows the correct stage and
      updates live without a refresh when it completes.
- [ ] **Local Serving Works:** both `variant=original` and `variant=annotated` return the correct
      file content directly from disk; the endpoint requires an authenticated session.
- [ ] **Accessibility:** ARIA roles present on interactive viewer elements; class colors have text
      labels (FE-10).
- [ ] **E2E Coverage:** a Playwright test covers directory ingestion → processing → viewing the
      completed analysis (NFR-08).

---

## Issue 11 — [Bug] Fix worker-inference startup crash (missing system libraries for opencv-python)

### Summary
`worker-inference` crashes at boot when loading the real model weights (`weights/best.pt`): `import
cv2` (pulled in transitively by `ultralytics`) fails with `ImportError: libxcb.so.1: cannot open
shared object file`, because the `python:3.12-slim` base image in `backend/Dockerfile` has none of
the system graphics libraries `opencv-python` needs at import time, even headless. `/health` reports
`model_loaded: false`, and every image scanned/imported with real weights gets stuck in
`QUEUED`/`PROCESSING` forever. CI's e2e suite doesn't catch this because it runs with
`INFERENCE_BACKEND=fake`, which never imports `ultralytics`. This blocks Issue 6's actual production
behavior — detected during a manual smoke test of the full stack (see `known-issues.md`).

### Scope

**1. Fix the Root Cause**
Swap `opencv-python` for `opencv-python-headless` in the backend's dependencies (preferred — no GUI
bindings, no `libGL`/`libxcb` dependency, smaller image), or add the missing system libraries to
`backend/Dockerfile` if a transitive dependency still requires them.

**2. Regression Coverage**
Add a CI check that exercises the real inference import/boot path (not `INFERENCE_BACKEND=fake`),
so this class of failure can't silently reappear — at minimum, a smoke step that builds
`worker-inference` and imports `app.inference.model` (or boots the container and polls `/health`)
with real weights mounted.

**3. Verify**
Confirm `/health` reports `worker.model_loaded: true` and the correct device with real weights, and
that a scanned image reaches `COMPLETED` through the real (non-fake) inference path.

### Acceptance Criteria
- [ ] **Clean Boot:** `worker-inference` starts with `weights/best.pt` mounted, no `ImportError`.
- [ ] **Health Reflects Reality:** `/health` reports `model_loaded: true` and the active device.
- [ ] **Real Pipeline Works:** a directory scan against a real image reaches `COMPLETED` using the
      real model, not `INFERENCE_BACKEND=fake`.
- [ ] **Regression Guard:** CI fails if this class of import/startup failure reappears.
- [ ] **Docs:** the `known-issues.md` entry for this bug is removed or marked resolved.

---

## Issue 12 — [Feature] Native launcher and zero-command startup (FR-20)

### Summary
Per PRD section 3.8 / FR-20 — now part of Phase 1's own completion criterion (section 15) — the
daily operator should never run a command or navigate a browser manually to use PCB-Inspect.
Today, "running the system" means typing `docker compose up` in a terminal every single time, which
is disqualifying for the target non-technical plant-administrator persona (NFR-07) and was never
actually built despite being scoped as part of Phase 1.

### Scope

**1. Launcher Application**
A thin native shell (e.g., Tauri), packaged per OS, that: checks whether the backend stack is
running; starts it (`docker compose up -d`) if not; waits for `/health` to report ready; opens the
interface in its own application window — no browser chrome, no address bar, no visible terminal.

**2. Startup and Error States**
A loading/splash state while the backend starts; a clear, actionable error state if the container
runtime isn't installed or isn't running (rather than a silent hang).

**3. Lifecycle**
Stop/status actions exposed from the launcher; document the chosen behavior for what happens to the
running stack when the launcher window is closed.

**4. Packaging**
A build artifact for at least one OS (Windows recommended — most likely production-line PC),
documenting the one-time technical setup (section 14.1) as clearly separate from, and shorter than,
daily double-click operation (NFR-07).

### Acceptance Criteria
- [ ] **Cold Start:** double-clicking the launcher icon with the stack stopped starts it and opens
      the dashboard automatically, with no terminal involved.
- [ ] **Warm Start:** double-clicking the launcher icon with the stack already running just opens
      the dashboard — no duplicate containers.
- [ ] **Error Visibility:** a missing/stopped container runtime produces a clear error state, not a
      silent hang.
- [ ] **No Browser Chrome:** the launcher window has no visible address bar.
- [ ] **Setup vs. Operation Documented:** one-time technical setup steps are documented separately
      from, and are clearly shorter than, the daily launch flow.
- [ ] **Tests:** launcher start/detect-running/error-state behavior covered where practical (native
      shells vary in testability — document what's covered vs. manually verified).

---

## Issue 13 — [Feature] Search and history screen (FE-04)

### Summary
`GET /api/v1/inspections` (FR-07) was built in Issue 8, and FE-04 is explicitly part of Phase 1's
frontend scope (section 15), but no dedicated screen was ever built for it — there is no
`/inspections` route today, only the dashboard's fixed "recent analyses" table (10 most recent) and
the per-inspection detail page. Operators currently have no way to search or filter historical
inspections at all.

### Scope

**1. `/inspections` Route**
A dedicated page consuming the existing search API with its full filter set (defect type, batch,
board, date range, status, severity — section 11.3).

**2. `FilterBar` Component**
Combinable filters persisted in the URL (shareable/bookmarkable), per section 12.2.

**3. Results Display**
Paginated table (reusing `InspectionTable`), consistent with the dashboard's styling; a clear
empty-state message when no results match.

**4. Navigation**
A nav entry into this screen (e.g., "Inspections"), plus a "view all" link from the dashboard's
recent-analyses table.

Export of filtered results (CSV/XLSX/PDF) is FR-11 (Phase 3) — explicitly out of scope here; this
issue only covers browsing, filtering, and opening a detail from search results.

### Acceptance Criteria
- [ ] **Route Renders:** `/inspections` shows a paginated, filterable list backed by the existing
      search API.
- [ ] **Filters Work:** each documented filter narrows results correctly, alone and combined.
- [ ] **Shareable State:** filter state is reflected in the URL and restorable via direct link or
      refresh.
- [ ] **Detail Navigation:** selecting a row opens the existing analysis detail screen (Issue 10).
- [ ] **Empty State:** no-results is handled with a clear message, not a blank table.
- [ ] **Tests:** Playwright coverage for at least one filter combination, plus component tests for
      `FilterBar`.

---

## Issue 14 — [Feature] Full accessibility pass across Phase-1 screens (FE-10)

### Summary
FE-10 (responsive, keyboard-navigable, adequate contrast, text labels for color indicators, ARIA
roles) is part of Phase 1's own completion criterion, and each prior issue's acceptance criteria
included a narrow accessibility check scoped to its own screen — but no pass has verified the
requirement holistically across the full Phase-1 surface (login, dashboard, ingestion, detail, and
now search/history from Issue 13). This was explicitly flagged as an undrafted candidate on the
original backlog.

### Scope

**1. Keyboard Navigation Audit**
Every interactive element (nav, filters, table rows, image viewer zoom/pan/toggle, bbox selection)
reachable and operable via keyboard alone, across all Phase-1 screens.

**2. Color Contrast Audit**
Text/background contrast ratios meet WCAG AA, particularly for defect-class and severity badges.

**3. Text Labels for Color-Coded Indicators**
Confirm every defect-class/severity color also carries a text label, not color alone — already
partially done per-component; verify comprehensively.

**4. ARIA Roles**
Verify roles/labels on custom interactive components (`AnnotatedImageViewer` bbox overlay,
`ProcessingStatusStepper`, `FilterBar`, tables) with a screen-reader spot check.

**5. Responsive Check**
Desktop and tablet breakpoints render usably (no clipped/overlapping content) on all Phase-1
screens.

### Acceptance Criteria
- [ ] **Keyboard-Only Golden Path:** login → ingest → dashboard → search/filter → detail completes
      with no dead ends, keyboard only.
- [ ] **Contrast Check:** an automated check (e.g., axe/Lighthouse) passes with no critical
      violations on all Phase-1 screens.
- [ ] **Text Labels:** every color-coded UI element (defect class, severity, status) has an
      accompanying text label.
- [ ] **ARIA Coverage:** roles present and correct on custom interactive components, verified with a
      screen-reader spot check.
- [ ] **Responsive:** desktop and tablet viewport widths render without clipped/overlapping content.
- [ ] **Regression Guard:** findings/fixes documented; automated checks added to CI where practical.

---

## Not Yet Drafted (Phase 2 / Phase 3)

Everything under Phase 2 (agent chain, chat, feedback/annotation UI, LLM settings) and Phase 3
(reports, model versioning with golden set, quality alerts, dataset export, full settings area) per
PRD section 15 — to be drafted once Phase 1 (issues 1–14) is stable.
