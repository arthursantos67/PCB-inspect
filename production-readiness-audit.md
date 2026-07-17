# Production Readiness Audit — Pre-Pilot Verification (2026-07-17)

Scope: verify the current state of the codebase (branch `feature/39-data-retention-purge`,
already merged to `main` via PR #49) against the PRD, run the full automated test suite, and
exercise a real end-to-end cycle — ingest a batch of boards, run detection, get an analysis
back — against the actual production Docker Compose stack (real `python:3.12-slim` images,
the real trained `weights/best.pt` model) ahead of a first single-cycle pilot (operator shows
the software a batch of boards, reviews the analysis/summary it returns).

## Method

- Backend: `pytest` (383 tests), `ruff check .`, `mypy app` — run against the local
  Postgres/Redis containers (`pcb-defect-db-1`, `pcb-defect-redis-1`).
- Frontend: `eslint`, `tsc --noEmit`, `vitest run` (9 tests), `next build` — Node 22.
- PRD section 16 (Requirements Traceability Matrix) checked file-by-file against the repo.
- A real ingestion → detection → analysis cycle run twice: once against bare backend
  processes on the host (Python 3.14, no Docker), then again — after rebuilding the images
  from current source — against the actual `docker compose` stack (`api`,
  `worker-inference`, `worker-agents`, `worker-housekeeping`, `beat`), which is what the
  native launcher (FR-20) actually runs in production.

## Findings

### 1. `worker-agents` crashes and silently strands boards in `ANALYZING` when two agent analyses overlap

**Status: fixed on `fix/40-agent-worker-gevent-asyncio-crash`, re-verified against the real Docker images.**

Ingesting a batch of 3 boards where more than one qualifies for the in-depth agent tier
(default `agent_analysis_mode=conditional`, PRD 5.3/FR-06) left 1 of the 3 stuck in
`ANALYZING` forever. Container log (`worker-agents`):

```
File "/srv/app/tasks/pipeline.py", line 180, in run_agent_analysis
    asyncio.run(_run_agent_analysis_async(inspection_image_id))
  File "/usr/local/lib/python3.12/asyncio/runners.py", line 191, in run
    raise RuntimeError(
RuntimeError: asyncio.run() cannot be called from a running event loop
```

**Root cause:** `worker-agents` runs `--pool=gevent --concurrency=4`
(`docker-compose.yml`), which executes up to 4 "concurrent" tasks as greenlets inside a
single OS thread. `run_agent_analysis` (`backend/app/tasks/pipeline.py:180`) calls bare
`asyncio.run(...)` per task — which is not safe against overlapping calls on the same OS
thread. As soon as a second `run_agent_analysis` task starts while a first one's
`asyncio.run()` call is still active (very likely — each task does real I/O: an LLM call or
its timeout), the second crashes immediately.

**Why it's worse than a normal task failure:** `PipelineTask.on_failure`
(`backend/app/tasks/base.py:50`) also calls `asyncio.run(_mark_failed_async(...))` — and
fails with the *same* error. So the image is never marked `FAILED`, no
`inspection.failed` SSE event is emitted, and nothing is written to the audit log. The board
just stays `ANALYZING` indefinitely with no error surfaced anywhere. The task also isn't
retried — `autoretry_for = (TransientProcessingError,)` doesn't cover a bare `RuntimeError`,
so this is a single unhandled failure, not a transient one that self-heals.

**Why the existing test suite doesn't catch it:** the Playwright E2E spec
(`frontend/e2e/inspection-flow.spec.ts`) ingests exactly one board per run, so two
`run_agent_analysis` executions never overlap in CI. Backend `pytest` exercises the task
function directly/serially, not under a real multi-greenlet worker. The gap is specific to
processing more than one board at a time — i.e., exactly the "show it a batch of boards"
pilot scenario.

**Fix applied:** switched `worker-agents` from `--pool=gevent` to `--pool=threads` in
`docker-compose.yml` (and the equivalent worker-start step in `.github/workflows/ci.yml`'s
`e2e` job). PRD section 3.3 already lists `--pool=gevent` *or* `--pool=threads` as valid for
this worker. `--pool=threads` gives each concurrent task a real OS thread, so
`asyncio.run()` per task is safe (event-loop state is OS-thread-local), while preserving the
I/O-bound concurrency the architecture wants.

That change alone surfaced a second, previously-masked bug: `app/tasks/db.py` built one
module-level `AsyncEngine` at import time and reused it across every task invocation. Under
`--pool=gevent` all "concurrent" tasks share a single OS thread, so this was safe; under real
`--pool=threads`, two different OS threads touching the same engine's internal
`asyncio.Lock`s (created lazily, bound to whichever event loop first used them) crashed with
`RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop`. Fixed by making
the engine/session-factory thread-local (`threading.local()`, built lazily per OS thread,
reused for that thread's lifetime) — same "build once, reuse for the worker's life" property,
now scoped correctly per thread.

Re-verified against the real Docker stack: 12 concurrent `run_agent_analysis` invocations
against `worker-agents` (real `--pool=threads --concurrency=4`) all succeeded with no crash,
and the 6 boards left stranded in `ANALYZING` by the original repro were re-enqueued and all
reached a terminal status (`COMPLETED`, degraded to baseline — no LLM configured on this
host). `0` inspections remain in `ANALYZING`. Full backend suite re-run green: `pytest`
383/383, `ruff`, `mypy` clean.

**Impact if not fixed:** during a real batch run, any two boards whose agent-tier analysis
windows overlap will silently strand one of them in `ANALYZING` forever, with zero operator
visibility. Reproduced at a ~33% hit rate on a 3-board batch in testing.

### 2. `LLM_BASE_URL=http://host.docker.internal:1234/v1` doesn't resolve on Linux Docker hosts

`.env.example`'s default for a local LM Studio/Ollama server assumes `host.docker.internal`
resolves inside the containers, which Docker Desktop (Mac/Windows) provides automatically but
plain Docker Engine on Linux does not, unless `extra_hosts: ["host.docker.internal:host-gateway"]`
is added per service in `docker-compose.yml` (currently absent). Confirmed via `/health`:
`"llm":{"status":"error","detail":"...unreachable: [Errno -2] Name or service not known"}` on
this machine (Fedora Linux).

**Impact:** only relevant once the operator wants real agent-tier analysis via a local LLM on
a Linux inspection-station machine. A cycle with no LLM configured at all (baseline
knowledge-base analysis only, PRD's Phase 1 "no LLM configured" mode) is unaffected.

**Status: fixed on `fix/40-agent-worker-gevent-asyncio-crash`.** Added
`extra_hosts: ["host.docker.internal:host-gateway"]` to the shared backend service definition
in `docker-compose.yml`. Re-verified via `/health`: the DNS error is gone (
`"...unreachable: [Errno -2] Name or service not known"` →
`"...unreachable: All connection attempts failed"`, i.e. the name now resolves and the
remaining error is just "nothing listening on that port," expected with no local LLM server
running on this machine).

## Verified as already correct (no fix needed)

- **PRD scope coverage:** every FR-01→FR-20 and FE-01→FE-10 in the section 16 traceability
  matrix maps to a real implementation file (some under slightly different names than
  planned — e.g. `app/agents/chain.py` instead of `graph.py` — functionally equivalent).
  Phases 1–3 of the delivery plan (PRD section 15) are all present in `main`.
- **Automated suites:** backend `pytest` (383/383), `ruff`, `mypy` all clean; frontend
  `eslint`, `tsc --noEmit`, `vitest` (9/9), and `next build` all clean; recent GitHub Actions
  CI runs green.
- **Core pipeline happy path:** verified against the real Docker stack with the real
  `weights/best.pt` model — ingestion → YOLO detection → knowledge-base baseline analysis
  (description, probable causes, suggested solutions, severity) → `COMPLETED`, exactly the
  "show it a batch, get an analysis and summary back" flow, works correctly whenever finding
  #1 above doesn't trigger.
- **`/health` worker check:** reports `"worker":{"status":"ok"}` correctly on the real
  Docker Compose stack (each service gets a distinct container hostname). A hostname
  collision that makes this check flaky only shows up when running multiple Celery workers
  as bare processes on the same host outside Docker — not a production configuration, so not
  tracked as a fix here.
- **`RN-04` duplicate-image rejection**, one-off directory scan (`FR-03`), and login/session
  (`FR-01`) all behaved as specified during manual verification.

## Resolution

Both findings fixed on `fix/40-agent-worker-gevent-asyncio-crash` (branched from `main` post-PR
#49) and re-verified against the real Docker stack — see the **Status: fixed** notes under each
finding above. Backend `pytest` (383/383), `ruff`, and `mypy` all re-run clean after the fix.

Not yet re-run: the frontend Playwright E2E spec and a real multi-board batch through the actual
`/scan` → YOLO → agent-tier pipeline with genuine PCB defect images (the re-verification above
drove `run_agent_analysis` directly against the real worker/DB to isolate and confirm the
concurrency fix, plus reprocessed the 6 boards the original repro had stranded — it did not
re-run a fresh end-to-end ingestion with new images). Worth doing once real defect imagery is
on hand, before the pilot.
