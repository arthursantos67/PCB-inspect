# PCB-Inspect — Product Requirements Document (PRD)

## AI-Agent-Powered PCB Defect Analysis System

**Project:** pcb-inspect
**Document type:** Product Requirements Document (PRD) — Local Software (Full-Stack)
**Version:** 2.0
**Last update:** 2026-07-10
**Source documents:** SRS "AI-Agent-Powered PCB Defect Analysis System"; trained YOLO11x model (notebook `PCB_Defect_Model.ipynb`); PRD v1.1 (hosted multi-user platform design — superseded by this version)
**Training notebook (Colab):** https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing

**v2.0 — architecture pivot.** The project is re-scoped from a hosted, multi-role web platform to **local, on-premise software** run by a single operator on one machine (optionally two, purely for throughput). The realistic deployment is a camera on the production line saving each captured board to a local folder, grouped by batch — the software processes that folder directly. This removes: multi-role RBAC (single local account model, section 2.2), cloud object storage (images are referenced from local disk, never copied, section 3.1), and browser-upload-first ingestion (directory watching/scanning is now primary, FR-03). Every network service binds to `localhost` only. Full rationale in section 3.1. A prior version of this document (v1.1) designed the system as a multi-tenant hosted platform; that direction was reconsidered and does not apply to this version.

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [System Context](#2-system-context)
3. [Architecture Overview](#3-architecture-overview)
4. [Computer Vision Model](#4-computer-vision-model)
5. [AI Agent Pipeline](#5-ai-agent-pipeline)
6. [Functional Requirements — Backend](#6-functional-requirements--backend)
7. [Functional Requirements — Frontend](#7-functional-requirements--frontend)
8. [Use Cases (1–10)](#8-use-cases-110)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Data Model and Integrity Rules](#10-data-model-and-integrity-rules)
11. [API Contract and Error Standard](#11-api-contract-and-error-standard)
12. [Frontend Component Specification](#12-frontend-component-specification)
13. [Security and Access Control](#13-security-and-access-control)
14. [Operational Requirements](#14-operational-requirements)
15. [Phased Delivery Plan](#15-phased-delivery-plan)
16. [Requirements Traceability Matrix](#16-requirements-traceability-matrix)
17. [Out of Scope](#17-out-of-scope)

---

## 1. Purpose and Scope

PCB-Inspect is local software for automated quality inspection of Printed Circuit Boards (PCBs), built to run on the machine (or two) physically responsible for an inspection station — not as a hosted service. A camera on the production line captures each board and saves it to local disk, grouped into batches; PCB-Inspect watches that directory, detects and classifies defects with a trained YOLO11x model, and runs each detection through a chain of AI agents that produces an interpreted technical analysis (description, probable causes, suggested solutions). Images, detections, and analyses are stored and searchable locally, and surfaced through a browser-based interface that runs entirely on the same machine: a dashboard, history, reports, and a natural-language chat.

**Scope covered by this document:**

Backend:
- Local, single-account authentication — no roles, no remote user administration (section 3.1)
- Image ingestion by watching a local directory (primary) or a one-off directory scan; batches and boards inferred from directory/file naming convention
- Asynchronous processing queue with a dedicated inference worker, decoupled from the API for responsiveness
- Defect detection with the trained YOLO11x model (6 classes)
- AI agent pipeline (Analyst → Reviewer → Summarizer) with a configurable, local-first LLM provider
- Persistence of images (referenced by local path, never copied), detections, and analyses, searchable by batch, board, defect type, date, and status
- Aggregated metrics and a production quality summary
- Chat with an AI agent that accesses analyses via tool-calling and streams responses
- Analysis and detection validation/feedback
- Report generation and export (CSV, XLSX, PDF) to local disk
- Feedback dataset export in YOLO format (data flywheel) and quality alerts
- Model version management with golden-set evaluation, dynamic configuration, audit trail, health check, and OpenAPI documentation

Frontend:
- Dashboard with stat cards, trend chart, and a list of recent analyses
- Analysis detail screen with an annotated image (zoom/pan) and the AI's textual analysis
- Search and history screen with combinable filters
- Ingestion screen: configure the watched directory, trigger a manual scan, and track processing progress
- Chat interface with the AI agent (streaming)
- Settings area (thresholds, LLM provider, watch directory, local accounts, model versions)
- Real-time dashboard updates via SSE — all served from `localhost`

---

## 2. System Context

### 2.1 Business Context

Manual PCB inspection is slow, prone to human error, and does not scale to mass production. Late defect detection generates rework, material waste, and delivery delays. PCB-Inspect automates visual inspection and — its core differentiator — translates each detection into actionable technical analysis generated by AI agents, without requiring the machine's operator to be a defect-analysis specialist. Because it runs entirely on hardware the line already owns, with no data leaving the premises by default, it also avoids the cost and exposure of shipping large volumes of proprietary board imagery to a cloud service.

The six defect types detected:

| Class | Name | Description |
|---|---|---|
| `missing_hole` | Missing Hole | Missing fixation/via hole in the circuit |
| `mouse_bite` | Mouse Bite | Small tears/gaps in the trace outline |
| `open_circuit` | Open Circuit | Trace interruption causing electrical failure |
| `short` | Short | Unwanted connection between conductors |
| `spur` | Spur | Unplanned copper protrusion |
| `spurious_copper` | Spurious Copper | Copper residue outside the design |

### 2.2 Actor

Unlike a shared enterprise system, PCB-Inspect is operated by one person — or a small team sharing the same machine — responsible for the inspection station. There is no scenario in this project's scope where different people need different permission levels on the same running instance, so the system deliberately has a single, flat actor:

| Actor | Description | Capabilities |
|---|---|---|
| Operator (`user`) | The person running the inspection station; full access to the software | Everything: configure ingestion and thresholds, review the dashboard and analyses, validate/reject detections and record board disposition, manage model versions, generate reports, use the chat, export data, manage local accounts |

More than one local account may exist on the same install (e.g., for shift handoff or per-person attribution in the audit trail, FR-16), but all accounts are equivalent — there is no role hierarchy or permission difference between them. A full multi-user, role-based permission system is explicitly out of scope for this project (section 17); it is the subject of a separate portfolio project.

---

## 3. Architecture Overview

### 3.1 Why Local Software, Not a Hosted Platform

The system runs on the machine (or two) physically responsible for the inspection station — a camera on the line saves each captured board to a local folder, grouped into batches, and PCB-Inspect processes that folder directly. This single fact shapes every architectural decision below:

- **No cloud/object storage.** Copying images that already exist on local disk into an object store (S3/MinIO) before processing them would double the storage footprint and add I/O for no benefit. Images are referenced by their local path; nothing is duplicated except the small annotated overlays the pipeline itself generates.
- **No multi-role access control.** The software runs on one or two machines under the responsibility of a single operator. A permission matrix designed for an organization with distinct Operator/Quality/Manager/Admin roles solves a problem this deployment does not have. A single local account — optionally a couple of named accounts for shift attribution, with **no** permission differences between them — is the honest fit (section 2.2).
- **No internet exposure by default.** All services bind to `localhost` only; nothing on the machine is reachable from the network. PCB imagery and defect data can be commercially sensitive, and a system with no listening network service has meaningfully smaller attack surface than any client-server system, on-premise or not. The AI agent pipeline defaults to a local LLM (LM Studio/Ollama) for the same reason — a cloud provider remains available, but only as an explicit, informed opt-in (section 5.2), never the default.
- **The UI is still browser-based — the browser just never leaves the machine.** Rich interaction (an annotated-image viewer, a live dashboard, a streaming chat) is naturally built with web technology, and there's no reason to give that up just because the deployment target is a single machine. The frontend is served locally and opened in the operator's own browser; it is never published to a network, so "uses a browser" does not imply "hosted service." Wrapping the same stack in a native desktop shell (e.g., Tauri) is a reasonable later step, noted as a future possibility (section 17), not a requirement now.
- **A task queue is kept, but for a different reason.** Celery and Redis remain in the architecture — not to serve multiple concurrent users, but to keep the API responsive while GPU-bound YOLO inference and LLM calls run in the background, and to leave the door open to a second machine running additional workers if throughput ever requires it. That two-machine option is a possibility to leave room for, not a commitment this project makes.

### 3.2 Architectural Style

- **Backend:** FastAPI (Python 3.12+), a local service bound to `127.0.0.1`, with dedicated inference and agent workers behind a queue
- **Frontend:** Next.js (App Router), served locally and opened in the operator's browser at `http://localhost:<port>`

**Rationale for FastAPI:** the trained model is Python/Ultralytics; keeping the API and inference in the same ecosystem removes serialization layers between services, native async support serves SSE/chat streaming, and OpenAPI documentation is auto-generated from Pydantic schemas.

### 3.3 Backend Components

| Component | Technology | Responsibility |
|---|---|---|
| HTTP API | FastAPI + Pydantic v2 | REST endpoints, validation, OpenAPI, SSE — bound to `127.0.0.1` only |
| Domain layer | SQLAlchemy 2 (async) + Alembic | Relational models, migrations |
| Task queue | Celery 5 + Redis 7 | Decouples the API from inference/agent work; enables optional second-machine scaling |
| Inference worker | Dedicated Celery worker (`--pool=solo`, 1 process per GPU) | Loads `best.pt` once (warm start) and runs detection directly against local image paths |
| Agent worker | I/O-bound Celery worker (`--pool=gevent` or threads) | Runs the LangGraph LLM analysis pipeline |
| Relational database | PostgreSQL 16 (local container) | Users, batches, boards, detections, analyses, chat, audit |
| Image storage | Local filesystem | Original images stay exactly where the camera saved them (referenced by path, never copied); annotated images and generated reports are written to a local app-data directory |
| Cache / locks / pub-sub | Redis 7 (local container) | Dashboard aggregate cache, Celery broker, SSE event channel |

### 3.4 Frontend Stack

- **Next.js 15** (App Router) + **React** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui** for the design system
- **TanStack Query** for data fetching, caching, and revalidation
- **Recharts** for dashboard charts
- Native SSE consumption (`EventSource`) for real-time events and chat streaming

### 3.5 Image Processing Flow

```
Ingestion (watch-folder scan / one-off directory scan)
   │  file discovered on local disk → InspectionImage record referencing its path (status QUEUED)
   ▼
Redis queue → Inference Worker (YOLO11x best.pt)
   │  detections persisted; annotated image written to a local app-data directory
   │  baseline analysis published (knowledge base, no LLM)
   │  status DETECTED; SSE event "detection.completed"
   ▼
Redis queue → Agent Worker (LangGraph — per FR-06 policy)
   │  Analyst → Reviewer → Summarizer (structured JSON output)
   │  Analysis enriched; status COMPLETED; SSE event "analysis.completed"
   ▼
Dashboard / search / chat / reports (all served from localhost)
```

A failure at any stage moves the record to status `FAILED` with the reason persisted. The original file on disk is only ever read — it is never moved, renamed, or deleted; the camera software (or the operator) owns that file, and ingestion state (ingested/failed, with the reason) is tracked entirely in the database against the file's path and checksum, not by relocating it. A failed file can be re-ingested once whatever caused the failure is fixed, simply by clearing its failure state and rescanning.

### 3.6 Redis Responsibilities

- Celery broker and result backend
- Dashboard aggregate cache (key `stats:summary:{period}`, TTL 60 s)
- Pub/sub channel for SSE events (`events:inspections`)

### 3.7 Error Handling Model

- Global exception handler on the backend with a consistent error envelope (section 11.4)
- The frontend maps `error.code` to localized messages; raw backend messages are never shown to the user
- Celery tasks use exponential retry for transient failures (LLM unavailable, disk I/O hiccup); maximum 3 attempts

---

## 4. Computer Vision Model

### 4.1 Trained Model (existing artifact)

| Item | Value |
|---|---|
| Architecture | YOLO11x (Ultralytics) |
| Weights | `weights/best.pt` (~114 MB), fine-tuned from `yolo11x.pt` |
| Classes | 6 (section 2.1) |
| Input resolution | 640×640 |
| Training | 200 effective epochs (early stop, patience 20), AdamW, lr0 1e-3 |
| mAP@50 (validation) | 0.99 |
| mAP@50-95 (validation) | 0.756 |
| mAP@50 (test) | 0.974 |
| Dataset | PCB Defects (Kaggle) + Roboflow/Albumentations augmentation — 3,524 images |
| Training notebook | [Google Colab — PCB_Defect_Model.ipynb](https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing) |

The model was validated locally (inference on dataset samples with 0.85–0.92 confidence and correct classes). The linked notebook documents the full training method: dataset preparation, conversion of Pascal VOC annotations to YOLO format, hyperparameters, and validation/test metrics.

### 4.2 Inference Requirements

- **RV-01** — The inference worker must load the model exactly once at process startup and reuse it (warm start). Cold start must never occur per request.
- **RV-02** — Inference must use GPU (CUDA) when available, with automatic fallback to CPU. The device in use must be exposed in the health check.
- **RV-03** — Every detection with confidence ≥ `min_confidence_store` (default 0.25) is persisted; only detections with confidence ≥ `min_confidence_report` (default 0.50) are reported in the interface and aggregates. Both thresholds are configurable at runtime (FR-13) — this allows later auditing of low-confidence detections without cluttering operations.
- **RV-04** — The annotated image (bounding boxes with class and confidence) must be generated by the worker and written to the local app-data directory.
- **RV-05** — Every detection must record the model version that produced it (`model_version_id`), ensuring traceability when the model is updated.
- **RV-06** *(optional optimization, post-MVP)* — Export the model to ONNX/TensorRT to reduce inference latency in production.

### 4.3 Known Model Limitations

The model was trained on an academic dataset (Kaggle PCB Defects): bare boards (no mounted components), simulated defects, and a limited variety of designs, captured under controlled lighting conditions. The metrics in section 4.1 hold for that distribution — against a real production-line camera (different optics, lighting, and board designs), performance is unpredictable without domain adaptation. This document treats that limitation as a design premise, not a footnote:

- Every metric shown on the platform declares the model version and the reference set that produced it (RV-05, FR-12).
- Per-detection human feedback (FR-10) and labeled dataset export (FR-18) exist specifically to enable adapting the model to real data from the deployment environment.
- Activating new weights requires a reproducible evaluation against a golden set, run by the system itself (FR-12), preventing silent regressions.

---

## 5. AI Agent Pipeline

### 5.1 Orchestration

The pipeline is implemented with **LangGraph** (a deterministic state graph with per-step checkpoints), executed on the agent worker. Every agent output is **structured** (JSON Schema via the provider's structured output), never free text that gets parsed.

### 5.2 Configurable LLM Provider — Local-First by Default

Consistent with section 3.1, the AI agent pipeline defaults to a **local** LLM so that no board imagery or defect data ever needs to leave the machine. A cloud provider remains available for operators who want it, but it is an explicit, informed opt-in — never the default. Configuration (FR-13) defines:

| Parameter | Description |
|---|---|
| `llm.provider` | `openai_compatible` (default target: LM Studio/Ollama running locally) \| `anthropic` \| `google` |
| `llm.base_url` | Endpoint for OpenAI-compatible providers; defaults to a local LM Studio/Ollama/vLLM instance |
| `llm.model` | Model identifier (e.g., a local model name, or `claude-sonnet-5`/`gemini-2.5-flash` if cloud is opted into) |
| `llm.api_key` | Credential, only relevant for cloud providers (stored encrypted, never exposed via the API — only `configured: true` + the last 4 characters) |
| `llm.timeout_s` | Timeout per call (default 60 s) |

The Settings UI (FE-08) makes the local/cloud distinction explicit — switching to a cloud provider surfaces a one-time notice that board images and derived text will be sent to that provider.

### 5.3 Agents

| Agent | Input | Structured output | Responsibility |
|---|---|---|---|
| **Analyst** | Image detections (class, bbox, confidence), board/batch metadata, cropped defect region | `description`, `probable_causes[]`, `suggested_solutions[]`, `severity` (`low`\|`medium`\|`high`\|`critical`), `functional_impact` | Technically interpret each detected defect |
| **Reviewer** | Analyst output + original detections | `approved` (bool), `corrections[]`, revised output | Verify technical consistency, correct hallucinations (e.g., a cause incompatible with the defect type), enforce adherence to the vocabulary of the 6 defect types |
| **Summarizer** | Reviewed output for all detections in the image | `executive_summary`, `disposition_recommendation` (`approve`\|`rework`\|`discard`), `priority` | Consolidate the board's analysis in plain, accessible language |

### 5.4 Chat Agent

A conversational agent separate from the pipeline, with **tool-calling** over real data (never inventing numbers):

| Tool | Function |
|---|---|
| `search_analyses` | Search analyses by batch, board, defect type, period, status |
| `get_analysis` | Full detail of a specific analysis |
| `get_defect_stats` | Aggregated statistics (counts, rates, trends) |
| `get_defect_knowledge` | Static knowledge base on the 6 defect types (definition, typical causes in the manufacturing process, standard solutions) |

- Responses streamed via **SSE** (token by token).
- Conversation history persisted per chat session.
- The agent responds in the operator's language and states limitations when a question falls outside its scope.

### 5.5 Pipeline Rules

- **RA-01** — Every analysis records execution metadata: provider, model, tokens consumed, duration, and prompt version.
- **RA-02** — A failure in the agent chain never discards detections: the analysis is left `FAILED` and can be reprocessed independently.
- **RA-03** — Agent prompts are versioned in the repository (not in the database), with a version identifier persisted on each analysis.
- **RA-04** — The Reviewer may reject an analysis at most once (one Analyst→Reviewer correction cycle); on a second rejection the analysis is marked `NEEDS_HUMAN_REVIEW`.
- **RA-05** — Chain execution follows the `agent_analysis_mode` policy (FR-06); images without an agent run keep the baseline analysis with `analysis_source = knowledge_base`.

---

## 6. Functional Requirements — Backend

### FR-01 Local Authentication

The system shall require a password-protected local login before any functionality is accessible. On first run, a setup step creates the local account (username/email + password); there is no public self-registration and no concept of remote account provisioning — the account exists only on the machine running the software. More than one local account may be created (e.g., for shift handoff); all accounts have identical, full access (section 2.2).

### FR-02 Local Account Management

The operator shall be able to add, rename, and remove local accounts, and change any account's password, from Settings. There is no separate "administrator" role: any account can manage any other account, consistent with FR-01. Removing an account does not delete records it created (FKs are preserved with the account reference retained for audit purposes, FR-16).

### FR-03 Directory-Based Image Ingestion

The system shall ingest PCB images primarily by reading them directly from local disk, in two modes:

- **Watch mode (continuous):** a configured root directory is monitored; new files are ingested automatically as the camera writes them.
- **One-off scan:** the operator points the software at a directory and triggers a full scan of its contents.

Batch and board identification follows a directory convention by default: each immediate subdirectory of the watch root is treated as one batch (`batch_number` = subdirectory name), and each image file within it as one board (`board_number` derived from the filename). The convention is configurable (FR-13) for cameras that produce a different layout.

A secondary import path remains available for ad hoc images that don't already sit under the watch root — e.g., a stray file dragged into the browser from elsewhere on the machine. This path does accept file bytes (the browser has no other way to read a file outside the watch root the backend already has permission to scan), unlike the primary flow, which never copies bytes and only ever references the original path.

Accepted formats: JPG, PNG, TIFF, BMP. Invalid/corrupted files are rejected with a descriptive error; in watch mode, the failure and its reason are recorded against the file's path in the database — the file itself is never moved, renamed, or deleted (section 3.5).

### FR-04 Asynchronous Processing

Every ingested file enqueues the image for asynchronous processing (status `QUEUED` → `PROCESSING` → `DETECTED` → `ANALYZING` → `COMPLETED` | `FAILED`; the `ANALYZING` stage only occurs when the agent chain is triggered — FR-06). Ingestion responds immediately with the created record(s); progress is queryable by polling and notified via SSE (FR-14).

### FR-05 Defect Detection

The inference worker shall run the YOLO11x model on every queued image, persist the detections (class, normalized bbox, confidence, model version), and generate the annotated image locally. Threshold rules per RV-03. Images with no reportable detection are marked `COMPLETED` with the result "no defects detected" — and count positively toward the quality rate.

### FR-06 Two-Tier Defect Analysis (Knowledge Base + AI Agents)

Text analysis operates at two tiers:

- **Baseline analysis (always, instant):** for every reportable detection, the system immediately publishes an analysis derived from a curated knowledge base per defect type — description, typical causes, standard solutions, and a default severity per class. It does not consume the LLM: this guarantees no inspection is ever left without an analysis, and that the main flow's latency does not depend on the provider — including a local LLM that may be slow or momentarily unavailable.
- **In-depth agent analysis (conditional):** the Analyst → Reviewer → Summarizer chain (section 5) runs according to the `agent_analysis_mode` policy (FR-13): `conditional` (default — triggers when a board has N+ reportable defects, contains a configurable critical class, or baseline severity ≥ high), `always`, or `on_demand` (only when requested from the interface). Once complete, it enriches/replaces the baseline and is marked `analysis_source = agents`.

The analysis is 1:1 with the inspection image.

**Rationale:** for 6 fixed classes, knowledge of causes/solutions is largely static; running a 3-agent LLM chain per image at high throughput (NFR-02) would be the system's latency bottleneck without a proportional gain — especially against a local model, which is typically much slower than the YOLO detector itself. The conditional policy preserves generative AI where it differentiates (complex boards, executive summary, chat) and keeps the core inspection flow fast and dependency-free — including allowing a full MVP demo with no LLM configured at all.

### FR-07 Analysis Query and Search

The system shall expose a paginated listing of inspections/analyses with combinable filters: defect type, batch number, board number, date range, processing status, review status, severity, and disposition recommendation. Sortable by date (default desc) and by severity.

### FR-08 Global Summary and Metrics

The system shall provide dashboard aggregates: total PCBs inspected, total with defects, quality rate, count by defect type, defect time series (day/week/month), top batches by defect count, and severity distribution. Results cached in Redis (TTL 60 s) and recomputable by date range.

### FR-09 Chat with AI Agent

The system shall expose persistent chat sessions per local account. Messages are answered by the chat agent (section 5.4) with SSE streaming. Session history is retrievable. The agent uses tools exclusively to assert facts about production data.

### FR-10 Validation and Feedback (Analysis and Detection)

The operator shall be able to validate or reject an analysis, with an optional comment, and to record a board's final disposition (`approved`, `rework`, `discarded`). Both actions are audited (FR-16) and feed system precision metrics (rate of validated vs. rejected analyses).

Additionally, the operator shall be able to record **per-detection** feedback — marking each bounding box as `confirmed` or `false_positive` — and **annotate undetected defects** by drawing a bbox + class directly in the image viewer. This detection-level feedback feeds the model's real-world precision metrics and is the input for dataset export (FR-18).

### FR-11 Reports and Export

The system shall generate reports on demand: **individual** (one analysis, PDF), **consolidated** (search filters, CSV/XLSX/PDF), and **executive summary** (period aggregates, PDF). Generation is asynchronous via Celery; the resulting file is written to a local, configurable reports directory and indexed in the database so it can be found and re-opened later from the interface.

### FR-12 Model Version Management with Golden-Set Evaluation

The operator shall be able to register new weight versions (pointing at a local `.pt` file), list versions, and activate a version. Registering new weights triggers an **automatic evaluation against the reference test set (golden set)** — images and labels versioned locally alongside the application data; the metrics persisted in `ModelVersion.metrics` (mAP@50, mAP@50-95, per class) are **computed by the system itself, never self-reported**. Activation is blocked while the evaluation is incomplete, and when mAP@50 falls below the floor (NFR-05), unless the operator provides an explicit, audited override.

Only one version is active at a time; switching reloads the inference worker without API downtime (rolling worker restart). Every detection references the version that produced it (RV-05).

### FR-13 Dynamic System Configuration

The operator shall be able to read and change at runtime: confidence thresholds (RV-03), LLM configuration (section 5.2), the agent analysis policy (`agent_analysis_mode` and its criteria, FR-06), quality alert thresholds (FR-19), the watch root path and its batch/board naming convention (FR-03), data retention, and the reports/exports output directory. Sensitive values (cloud LLM API keys) are stored encrypted and never returned in cleartext.

### FR-14 Real-Time Events (SSE)

The system shall expose an authenticated SSE stream with events: `inspection.created`, `detection.completed`, `analysis.completed`, `inspection.failed`, `alert.defect_rate`. The frontend uses this stream to update the dashboard and lists without a refresh.

### FR-15 Health Check and Documentation

- `GET /health` — checks connectivity to PostgreSQL, Redis, inference worker state (model loaded, GPU/CPU device), watch-root path accessibility, and LLM provider reachability.
- OpenAPI schema and Swagger UI exposed (`/api/schema`, `/api/docs`).

### FR-16 Audit

Sensitive actions generate an immutable `AuditLog` record: login, configuration change, model activation, analysis validation/rejection, board disposition, data deletion, account added/removed. Audit records are queryable with filters by account, action, and period.

### FR-17 Data Retention

Analyses, detections, and image references shall be retained for at least **2 years** (configurable). A periodic Celery task (beat) archives/purges records past retention — including old generated reports and dataset exports past their own retention window — with an audit record of the purge. Original camera-captured files on disk are never touched by retention; only the application's own records and derived artifacts are affected.

### FR-18 Feedback Dataset Export (Data Flywheel)

The system shall export, on demand, a labeled dataset in **YOLO format** composed of: images with confirmed detections (labels preserved), false-positive corrections (labels removed), and manual annotations of undetected defects (FR-10). Filters: period, defect types, and review status. The package — a ZIP with `images/`, `labels/`, and a JSON manifest (statistics, applied filters, source model version) — is generated asynchronously and written to the local exports directory, indexed for later retrieval.

This requirement closes the continuous-improvement loop: retraining stays external to the software (section 17), but the labeled input from real deployment-environment data comes out ready — this is what makes the limitation in section 4.3 addressable over time.

### FR-19 Quality Alerts

The system shall monitor the defect rate per batch and per time window against configurable thresholds (FR-13). When a threshold is exceeded, the system persists an alert, emits the `alert.defect_rate` SSE event, and displays it as a dashboard banner until acknowledged by the operator. Acknowledgments are audited (FR-16).

---

## 7. Functional Requirements — Frontend

### FE-01 Authentication

Login screen; on first run, it doubles as account setup. Session kept in memory; no `localStorage` token storage. Because the app never leaves `localhost`, the login screen is primarily a lightweight gate against casual access to sensitive board/defect data on a shared machine, not a defense against network attackers — see section 13. No email-based "forgot password" flow (no mail server involved); password reset is a local, in-app recovery path available to any other existing account.

### FE-02 Dashboard

Home page after login, with:
- **Stat cards**: total PCBs inspected, defects detected, quality rate (%), inspections in the last 24 h;
- **Trend chart** of defects over time with a period selector (7d / 30d / 90d) and breakdown by defect type;
- **Distribution by defect type** (bar chart);
- **Recent analyses list** (paginated table) with severity and status badges;
- **Active quality alerts banner** (FR-19), with an acknowledge action;
- Real-time updates via SSE (FE-09).

### FE-03 Analysis Detail

Reached from any listing:
- **Image viewer** with the annotated PCB — zoom, pan, and original/annotated toggle; numbered bounding boxes color-coded by class, with a confidence tooltip;
- **Detections panel**: list synchronized with the viewer (hover highlights the matching bbox);
- **AI analysis**: description, probable causes, suggested solutions, severity, executive summary, and disposition recommendation;
- **Metadata**: board, batch, date, model version, processing duration;
- **Actions**: validate/reject the analysis, per-detection feedback (confirm / false positive), annotate undetected defects by drawing a bbox in the viewer, request an in-depth agent analysis when in `on_demand` mode, record board disposition, open the generated report file, open chat with this analysis as context.

### FE-04 Search and History

Screen with combinable filters (defect type, batch, board, dates, status, severity, review), paginated results in table or thumbnail-grid view, and export of filtered results (CSV/XLSX/PDF via FR-11).

### FE-05 Ingestion Settings and Monitor

Because the frontend runs as a regular page in the operator's browser, it cannot open a native OS folder picker on its own — a plain web page has no standing access to the local filesystem beyond what the user explicitly hands it. The watch root directory is therefore configured as a **path field** in Settings: the operator types or pastes an absolute path, and the backend — which does run on the same machine and does have filesystem access — validates that the path exists and is readable before accepting it. (If the app is later wrapped in a native shell, per section 17, a real folder-picker dialog becomes available as an enhancement; it is not the baseline here.)

The ingestion screen shows live watch-mode status (watching / paused, files discovered), a "scan directory now" action for a one-off path, and a small drag-and-drop area for importing a handful of stray files that aren't already under the watch root (FR-03). Real-time processing status tracking (queue → detection → analysis → completed) as the files move through the pipeline.

### FE-06 Chat with AI Agent

Conversation interface with a session history sidebar, streaming responses, contextual suggestions for frequent questions ("How do I interpret this defect?", "Which batches had the most defects this week?"), and the ability to open the chat already scoped to a given analysis (FE-03).

### FE-07 Reports

Screen to request reports (individual, consolidated, executive summary), track generation, and open the resulting local file (or reveal it in the reports folder). List of previously generated reports, subject to the retention window configured in FR-13/FR-17.

### FE-08 Settings Area

- **Accounts** — add, rename, remove local accounts, change passwords; no role concept (FR-02).
- **Ingestion** — watch root path, batch/board naming convention, one-off scan trigger (FR-03, FE-05).
- **Detection & Analysis** — confidence thresholds, agent analysis policy, LLM provider (local vs. cloud, with the disclosure notice from section 5.2), quality alert thresholds.
- **Models** — weight versions, golden-set evaluation results, activation.
- **Audit** — audit trail with filters.

### FE-09 Real-Time Updates

The frontend subscribes to the SSE stream (FR-14) and updates the dashboard, lists, and progress screens without a manual refresh. Automatic reconnection with backoff on disconnect.

### FE-10 Accessibility and Responsiveness

Responsive interface (desktop and tablet), keyboard-navigable, with adequate contrast, text labels for color indicators (defect classes), and ARIA roles on the interactive elements of the image viewer.

---

## 8. Use Cases (1–10)

### UC-1 Log In

**Actor:** any local account (first run: account setup)
**Main flow:** submits credentials; the system validates and starts a session.
**Alternative:** invalid credentials → `INVALID_CREDENTIALS` error; no account exists yet → the login screen offers first-run setup instead.

### UC-2 Configure and Run Directory Ingestion

**Actor:** Operator
**Precondition:** logged in
**Main flow:** the operator sets the watch root path (validated by the backend) or triggers a one-off scan of a chosen path; the system discovers image files, validates format, creates `QUEUED` records per file, and the UI tracks progress via SSE.
**Alternative:** invalid path (doesn't exist / not readable) → rejected with a descriptive error before any scan runs.

### UC-3 Continuous Watch-Mode Ingestion

**Actor:** System
**Precondition:** watch root configured and reachable
**Main flow:** the camera saves a new file under the watch root; the service detects it, validates it, and ingests it automatically, without any file being moved.
**Alternative:** invalid/corrupted file → recorded as failed with a reason; the file is left untouched on disk for later re-ingestion once fixed.

### UC-4 Process Image (Detection + Analysis)

**Actor:** System (workers)
**Main flow:** the inference worker consumes the queue, runs YOLO, persists detections, the annotated image, and the knowledge-base baseline analysis (status `DETECTED`); if the `agent_analysis_mode` policy triggers (FR-06), the agent worker runs Analyst → Reviewer → Summarizer and enriches the analysis (status `COMPLETED`); SSE events are emitted at each transition.
**Alternatives:** no reportable detections → `COMPLETED` with no defect analysis; policy does not trigger agents → `COMPLETED` with the baseline analysis (`analysis_source = knowledge_base`); LLM failure after retries → detections and baseline preserved, `analysis_status = FAILED`, reprocessable; inference failure → `FAILED` with a reason.

### UC-5 View Defect Analysis

**Actor:** Operator
**Main flow:** the operator opens an analysis from the dashboard; the system displays the interactive annotated image, detections, text analysis, and recommendation; the operator records the board's disposition.
**Alternative:** analysis still processing → screen shows the current state and updates via SSE.

### UC-6 Search Historical Analyses

**Actor:** Operator
**Main flow:** the operator combines filters; the system returns a paginated list; the operator opens details or exports results.
**Alternative:** no results → an informational message suggesting broader filters.

### UC-7 Interact with the AI Chat

**Actor:** Operator
**Main flow:** the operator asks a natural-language question (e.g., "which batches had the most shorts this month?"); the agent calls tools against the local database and streams a response with real data.
**Alternatives:** LLM unavailable → temporary-unavailability message, session preserved; question out of scope → the agent states its limitation.

### UC-8 Validate Analysis and Record Feedback

**Actor:** Operator
**Main flow:** the operator reviews an analysis, validates or rejects it with a comment; the system audits the action and updates reliability metrics.

### UC-9 Generate Consolidated Report

**Actor:** Operator
**Main flow:** the operator defines filters/period and format; the system generates it asynchronously; the operator is notified and opens the resulting local file.

### UC-10 Update Model Version

**Actor:** Operator
**Main flow:** the operator registers new weights, the system evaluates them against the golden set and produces metrics, the operator activates the version; workers reload without API downtime; new detections reference the new version.
**Alternative:** invalid weights file or metrics below the floor → activation blocked with a descriptive error, unless explicitly overridden.

---

## 9. Non-Functional Requirements

### NFR-01 Processing Performance

- Detection (YOLO inference): p95 ≤ 5 s per image on GPU; ≤ 20 s on CPU.
- Baseline analysis published together with the detection (knowledge base, no perceptible added latency); the agent chain, when run, p95 ≤ 30 s per image with a responsive LLM. Detections and the baseline are visible immediately, without waiting for the agents.
- Listing endpoints: p95 ≤ 500 ms; dashboard aggregates: p95 ≤ 800 ms (with cache).
- First chat response (first token): ≤ 5 s.

### NFR-02 Throughput and Scalability

- Support **1,000 images/hour** on a single, adequately provisioned machine (GPU present) without degradation. The inference and agent workers are decoupled from the API by the task queue specifically so this target doesn't require the API itself to do any heavy lifting.
- If throughput needs ever exceed one machine, a second machine may run additional `worker-inference`/`worker-agents` processes pointed at the same Postgres/Redis instance over the local network — a possibility the architecture leaves room for, not a requirement this project commits to delivering.
- In `conditional` mode (default, FR-06), throughput does not depend on the LLM provider: the agent chain runs only for the fraction of boards that meet the criteria, and the baseline analysis covers the rest instantly.

### NFR-03 Availability and Recovery

- Failure recovery ≤ 15 min: containers with automatic restart, Celery tasks with `acks_late` (a task in progress on a dead worker returns to the queue).
- Automated local backup of the PostgreSQL database and the app-data directory (annotated images, reports, exports) — original camera-captured files are the camera software's responsibility, not this system's.

### NFR-04 Security

- **No network exposure by default.** All services (API, frontend, database, Redis) bind to `127.0.0.1`. Nothing on the machine is reachable from the network unless the operator explicitly reconfigures it — an unsupported opt-in, not the default (section 13).
- TLS is not required for the default localhost-only deployment, since traffic never leaves the machine.
- JWT Bearer (or an equivalent local session token) on all protected operations; passwords hashed with Argon2; cloud LLM API keys encrypted at rest.
- The AI pipeline defaults to a local LLM so board imagery and defect data never leave the machine unless the operator explicitly opts into a cloud provider (section 5.2).

### NFR-05 AI Precision and Reliability

- The active model shall maintain mAP@50 ≥ 0.95 on the reference test set (golden set), evaluated by the system itself when the version is registered (FR-12); versions below this cannot be activated without an explicit, audited override.
- Agent analyses are always structured and reviewed (Reviewer agent); chat statements about production data come exclusively from tools.
- The rate of analyses rejected during review is monitored as a pipeline quality metric.

### NFR-06 Operability and Observability

- Structured (JSON) logging with a correlation ID per request and per task.
- Prometheus metrics: inference latency, queue depth, LLM tokens consumed, error rate per stage.
- Aggregated health check (FR-15) covering the watch-root path, not just service connectivity.

### NFR-07 Usability

- An operator without prior software experience shall be able to run the system after 2 h of basic training.
- Actionable error messages; skeleton loaders during requests.

### NFR-08 Testability

- Backend: an integration test suite covering business flows and error contracts; pipeline tests with a mocked LLM (structured-output fixtures); ingestion tests against a temporary local directory fixture (no real camera required).
- Frontend: component and E2E tests (Playwright) covering ingestion → processing → visualization and the chat flow.
- CI runs the suites on every push/PR (section 14.2).

---

## 10. Data Model and Integrity Rules

### 10.1 Primary Entities

- `User`
- `Batch`
- `Board`
- `InspectionImage`
- `Detection`
- `Analysis`
- `AnalysisReview`
- `BoardDisposition`
- `ManualAnnotation`
- `ChatSession` / `ChatMessage`
- `Report`
- `DatasetExport`
- `QualityAlert`
- `ModelVersion`
- `SystemConfig`
- `AuditLog`

### 10.2 Definitions

#### User

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `email` | CITEXT (unique) | Local login identifier |
| `password_hash` | Text | Argon2 |
| `full_name` | Varchar | — |
| `created_at` / `updated_at` | Timestamptz | — |

No `role` field — every account has identical, full access (section 2.2).

#### Batch

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `batch_number` | Varchar (unique) | Human-readable batch identifier; defaults to the watch-root subdirectory name (FR-03) |
| `created_at` | Timestamptz | — |

#### Board

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `board_number` | Varchar | Human-readable board identifier; defaults to the source filename (FR-03) |
| `batch_id` | FK → Batch (nullable) | — |

Unique constraint: `(batch_id, board_number)`.

#### InspectionImage

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `board_id` | FK → Board (nullable) | — |
| `source` | Enum | `watch_folder` \| `directory_scan` \| `manual_import` |
| `original_path` | Varchar | Absolute local filesystem path to the camera-captured file; never copied |
| `annotated_path` | Varchar (nullable) | Local filesystem path to the generated annotated image (app-data directory) |
| `checksum_sha256` | Char(64) | Integrity and deduplication |
| `width` / `height` | Integer | — |
| `status` | Enum | `QUEUED` \| `PROCESSING` \| `DETECTED` \| `ANALYZING` \| `COMPLETED` \| `FAILED` |
| `failure_reason` | Text (nullable) | Populated on `FAILED` |
| `created_by` | FK → User (nullable) | Null for watch-folder/scan ingestion; set for manual import |
| `created_at` / `processed_at` | Timestamptz | — |

#### Detection

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `image_id` | FK → InspectionImage | Cascade delete |
| `defect_type` | Enum | 6 classes (section 2.1) |
| `bbox` | JSONB | `{x1,y1,x2,y2}` normalized [0,1] |
| `confidence` | Numeric(4,3) | [0,1] |
| `is_reported` | Boolean | `confidence ≥ min_confidence_report` at detection time |
| `model_version_id` | FK → ModelVersion | Traceability |
| `review` | Enum | `unreviewed` (default) \| `confirmed` \| `false_positive` — feedback (FR-10) |
| `reviewed_by` | FK → User (nullable) | Who recorded the feedback |

#### Analysis

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `image_id` | FK → InspectionImage (unique) | 1:1 |
| `status` | Enum | `PENDING` \| `RUNNING` \| `COMPLETED` \| `FAILED` \| `NEEDS_HUMAN_REVIEW` |
| `source` | Enum | `knowledge_base` \| `agents` — the current analysis tier (FR-06) |
| `per_defect` | JSONB | List: description, causes, solutions, severity per detection |
| `executive_summary` | Text | Summarizer output |
| `disposition_recommendation` | Enum | `approve` \| `rework` \| `discard` |
| `severity_max` | Enum | `low` \| `medium` \| `high` \| `critical` |
| `llm_provider` / `llm_model` | Varchar | Execution metadata (RA-01) |
| `prompt_version` | Varchar | RA-03 |
| `tokens_used` / `duration_ms` | Integer | — |
| `review_status` | Enum | `PENDING` \| `VALIDATED` \| `REJECTED` |
| `created_at` | Timestamptz | — |

#### AnalysisReview

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `analysis_id` | FK → Analysis | — |
| `reviewer_id` | FK → User | — |
| `action` | Enum | `validated` \| `rejected` |
| `comment` | Text (nullable) | — |
| `created_at` | Timestamptz | — |

#### BoardDisposition

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `image_id` | FK → InspectionImage (unique) | One disposition per inspection |
| `decision` | Enum | `approved` \| `rework` \| `discarded` |
| `decided_by` | FK → User | — |
| `created_at` | Timestamptz | — |

#### ManualAnnotation

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `image_id` | FK → InspectionImage | Defect not detected by the model (FR-10) |
| `defect_type` | Enum | 6 classes |
| `bbox` | JSONB | `{x1,y1,x2,y2}` normalized [0,1] |
| `created_by` | FK → User | — |
| `created_at` | Timestamptz | — |

#### ChatSession / ChatMessage

| Field | Type | Notes |
|---|---|---|
| `ChatSession.id` | UUID | PK |
| `ChatSession.user_id` | FK → User | Sessions kept per local account |
| `ChatSession.title` | Varchar | Generated from the first message |
| `ChatSession.context_analysis_id` | FK → Analysis (nullable) | Context-scoped chat (FE-03) |
| `ChatMessage.session_id` | FK → ChatSession | Cascade delete |
| `ChatMessage.role` | Enum | `user` \| `assistant` |
| `ChatMessage.content` | Text | — |
| `ChatMessage.tool_calls` | JSONB (nullable) | Tools called and summarized results |

#### Report

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `type` | Enum | `individual` \| `consolidated` \| `executive` |
| `format` | Enum | `csv` \| `xlsx` \| `pdf` |
| `filters` | JSONB | Criteria used |
| `status` | Enum | `PENDING` \| `COMPLETED` \| `FAILED` |
| `file_path` | Varchar (nullable) | Local filesystem path |
| `requested_by` | FK → User | — |
| `created_at` | Timestamptz | Subject to the retention window (FR-17) |

#### DatasetExport

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `filters` | JSONB | Period, classes, review status (FR-18) |
| `status` | Enum | `PENDING` \| `COMPLETED` \| `FAILED` |
| `manifest` | JSONB | Image/label counts, source model version |
| `file_path` | Varchar (nullable) | Local filesystem path of the ZIP |
| `requested_by` | FK → User | — |
| `created_at` | Timestamptz | Subject to the retention window (FR-17) |

#### QualityAlert

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `type` | Enum | `defect_rate_batch` \| `defect_rate_window` |
| `context` | JSONB | Batch/window, observed rate, configured threshold |
| `acknowledged_by` | FK → User (nullable) | Null = active alert |
| `acknowledged_at` | Timestamptz (nullable) | — |
| `created_at` | Timestamptz | — |

#### ModelVersion

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `version` | Varchar (unique) | E.g., `v1.0.0` |
| `weights_path` | Varchar | Local filesystem path of the `.pt` file |
| `metrics` | JSONB | mAP@50, mAP@50-95, per class |
| `is_active` | Boolean | At most one `true` (partial unique index) |
| `activated_at` / `created_at` | Timestamptz | — |

#### SystemConfig

| Field | Type | Notes |
|---|---|---|
| `key` | Varchar (unique) | E.g., `min_confidence_report`, `llm.provider`, `agent_analysis_mode`, `watch_root_path` |
| `value` | JSONB | — |
| `is_secret` | Boolean | Encrypted values (cloud LLM API keys); the API returns only status |
| `updated_by` / `updated_at` | FK → User / Timestamptz | — |

#### AuditLog

| Field | Type | Notes |
|---|---|---|
| `id` | BigSerial | PK |
| `actor_id` | FK → User (SET NULL) | — |
| `action` | Varchar | E.g., `config.updated`, `model.activated`, `analysis.validated`, `account.created` |
| `entity_type` / `entity_id` | Varchar / UUID | Target of the action |
| `payload` | JSONB | Delta/context (no secrets) |
| `created_at` | Timestamptz | Immutable — no UPDATE/DELETE |

### 10.3 Integrity and Business Rules

- **RN-01** — `Detection.confidence ∈ [0,1]` (check constraint); bbox normalized with `x1<x2`, `y1<y2`.
- **RN-02** — At most one `ModelVersion.is_active = true` (partial unique index).
- **RN-03** — `Analysis` is 1:1 with `InspectionImage`; reprocessing replaces the previous analysis while preserving the old one in the audit history.
- **RN-04** — A duplicate image (same `checksum_sha256` in the same batch) is rejected at ingestion with `DUPLICATE_IMAGE`.
- **RN-05** — A failure in the agent pipeline never deletes detections (RA-02).
- **RN-06** — `AuditLog` is append-only (UPDATE/DELETE revoked at the database level).
- **RN-07** — Only detections with `is_reported = true` feed dashboard aggregates and reports.
- **RN-08** — Minimum 2-year retention for inspections, detections, analyses, and audit records (FR-17).
- **RN-09** — Board disposition (`BoardDisposition`) is unique per inspection; a change creates a new audit entry with the previous value.
- **RN-10** — `ModelVersion.metrics` is only populated by the internal golden-set evaluation (FR-12); activating a version without a completed evaluation is blocked.

---

## 11. API Contract and Error Standard

### 11.1 Conventions

- Prefix `/api/v1/`; JSON in snake_case; dates in ISO 8601 UTC.
- Paginated listings: `?page=&page_size=` (default 20, max 100), response with `count`, `next`, `previous`, `results`.
- Ingestion/generation-triggering endpoints respond `202 Accepted`; created resources respond `201`.

### 11.2 Endpoints

Support and documentation:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/health` | DB, Redis, worker (model/device), watch-root path, and LLM state | Public (localhost only) |
| `GET` | `/api/schema` | OpenAPI schema | Public (localhost only) |
| `GET` | `/api/docs` | Swagger UI | Public (localhost only) |
| `GET` | `/metrics` | Prometheus metrics | Internal |

Authentication and accounts:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/auth/setup` | First-run: create the initial local account | Public, disabled once any account exists |
| `POST` | `/api/v1/auth/login` | Authenticate and start a session | Public |
| `POST` | `/api/v1/auth/refresh` | Refresh the session token | Public |
| `GET` | `/api/v1/users/me` | Current account profile | Auth |
| `GET`, `POST` | `/api/v1/users` | List or add a local account | Auth |
| `PATCH`, `DELETE` | `/api/v1/users/{id}` | Update (name/password) or remove a local account | Auth |

Inspections:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/inspections/scan` | Trigger a one-off scan of a given local directory path → 202 | Auth |
| `POST` | `/api/v1/inspections/import` | Import a small number of ad hoc files by upload (files not already under the watch root) → 202 | Auth |
| `GET` | `/api/v1/inspections` | Paginated listing with filters (section 11.3) | Auth |
| `GET` | `/api/v1/inspections/{id}` | Detail: status, detections, analysis | Auth |
| `GET` | `/api/v1/inspections/{id}/image?variant=original\|annotated` | Serves the image directly from local disk | Auth |
| `POST` | `/api/v1/inspections/{id}/reprocess` | Re-enqueue (full detection or `?stage=analysis`) | Auth |
| `POST` | `/api/v1/inspections/{id}/disposition` | Record board disposition | Auth |
| `POST` | `/api/v1/inspections/{id}/agent-analysis` | Request an in-depth agent analysis (`on_demand` mode) → 202 | Auth |
| `POST` | `/api/v1/inspections/{id}/annotations` | Annotate an undetected defect (bbox + class) | Auth |

Analyses:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/analyses/{id}` | Analysis detail | Auth |
| `POST` | `/api/v1/analyses/{id}/review` | Validate/reject with a comment | Auth |
| `POST` | `/api/v1/detections/{id}/feedback` | Mark a detection as `confirmed` or `false_positive` | Auth |

Statistics:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/stats/summary?from=&to=` | Dashboard cards | Auth |
| `GET` | `/api/v1/stats/trends?granularity=day\|week\|month` | Time series by defect type | Auth |
| `GET` | `/api/v1/stats/by-defect-type` | Distribution by class | Auth |
| `GET` | `/api/v1/stats/by-batch?limit=` | Top batches by incidence | Auth |

Chat:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET`, `POST` | `/api/v1/chat/sessions` | List or create a session (accepts `context_analysis_id`) | Auth |
| `GET`, `DELETE` | `/api/v1/chat/sessions/{id}` | Session history or deletion | Auth (owner) |
| `POST` | `/api/v1/chat/sessions/{id}/messages` | Send a message; response as an SSE stream | Auth (owner) |

Reports:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/reports` | Request generation (type, format, filters) → 202 | Auth |
| `GET` | `/api/v1/reports` | List generated reports | Auth |
| `GET` | `/api/v1/reports/{id}/download` | Streams the file from local disk | Auth |

Dataset and alerts:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/dataset-exports` | Request a YOLO export with filters (FR-18) → 202 | Auth |
| `GET` | `/api/v1/dataset-exports` | List exports with status and manifest | Auth |
| `GET` | `/api/v1/dataset-exports/{id}/download` | Streams the ZIP from local disk | Auth |
| `GET` | `/api/v1/alerts?acknowledged=` | List quality alerts | Auth |
| `POST` | `/api/v1/alerts/{id}/ack` | Acknowledge an alert | Auth |

Settings:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET`, `PATCH` | `/api/v1/settings/config` | Read/change dynamic configuration | Auth |
| `GET`, `POST` | `/api/v1/settings/models` | List/register model versions (registration triggers golden-set evaluation) | Auth |
| `GET` | `/api/v1/settings/models/{id}/evaluation` | Golden-set evaluation status/result | Auth |
| `POST` | `/api/v1/settings/models/{id}/activate` | Activate a version (reloads workers; blocked without evaluation, RN-10) | Auth |
| `GET` | `/api/v1/settings/audit` | Audit trail with filters | Auth |

Real time:

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/events` | SSE stream of inspection events | Auth |

### 11.3 Filter Parameters — `GET /api/v1/inspections`

| Parameter | Type | Description |
|---|---|---|
| `defect_type` | string (multi) | One or more of the 6 classes |
| `batch_number` | string | Batch number |
| `board_number` | string | Board number |
| `status` | string | Processing status |
| `review_status` | string | `PENDING` \| `VALIDATED` \| `REJECTED` |
| `severity` | string | `low`..`critical` |
| `disposition` | string | `approved` \| `rework` \| `discarded` |
| `date_from` / `date_to` | datetime | Creation date range |
| `ordering` | string | `-created_at` (default) \| `severity` |

### 11.4 Standardized Error Envelope

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "status": 400,
    "details": {}
  }
}
```

| Code | HTTP | Trigger |
|---|---|---|
| `VALIDATION_FAILED` | 400 | Invalid payload |
| `INVALID_CREDENTIALS` | 401 | Wrong email/password |
| `NOT_AUTHENTICATED` | 401 | Missing/expired session |
| `PERMISSION_DENIED` | 403 | Action attempted on another account's private resource (e.g., someone else's chat session) |
| `RESOURCE_NOT_FOUND` | 404 | Entity does not exist |
| `PATH_NOT_FOUND` | 422 | Configured/requested local directory or file path does not exist |
| `PATH_NOT_READABLE` | 422 | Local path exists but the process lacks read permission |
| `UNSUPPORTED_MEDIA` | 415 | Unaccepted image format |
| `FILE_TOO_LARGE` | 413 | Above the configured limit (manual import only) |
| `DUPLICATE_IMAGE` | 409 | Repeated checksum in the same batch (RN-04) |
| `INSPECTION_NOT_READY` | 409 | Action requires completed processing |
| `MODEL_ACTIVATION_FAILED` | 422 | Invalid weights or metrics below the floor (NFR-05) |
| `LLM_UNAVAILABLE` | 503 | LLM provider unreachable after retries |
| `INTERNAL_SERVER_ERROR` | 500 | Unhandled error |

### 11.5 Example — Inspection Detail (excerpt)

```json
{
  "id": "9f6a…",
  "board": { "board_number": "3012225", "batch_number": "2628878" },
  "status": "COMPLETED",
  "detections": [
    {
      "id": "d1…",
      "defect_type": "mouse_bite",
      "bbox": { "x1": 0.503, "y1": 0.734, "x2": 0.518, "y2": 0.762 },
      "confidence": 0.872,
      "is_reported": true,
      "model_version": "v1.0.0"
    }
  ],
  "analysis": {
    "status": "COMPLETED",
    "source": "agents",
    "severity_max": "medium",
    "disposition_recommendation": "rework",
    "executive_summary": "3 mouse bite defects were identified…",
    "per_defect": [
      {
        "detection_id": "d1…",
        "description": "…",
        "probable_causes": ["…"],
        "suggested_solutions": ["…"],
        "severity": "medium"
      }
    ],
    "review_status": "PENDING"
  }
}
```

---

## 12. Frontend Component Specification

### 12.1 Page Inventory

| Page | Route |
|---|---|
| Login / First-Run Setup | `/login` |
| Dashboard | `/` |
| Analysis Detail | `/inspections/{id}` |
| Search and History | `/inspections` |
| Ingestion Settings & Monitor | `/ingestion` |
| AI Chat | `/chat` (and `/chat/{sessionId}`) |
| Reports | `/reports` |
| Settings — Accounts | `/settings/accounts` |
| Settings — Detection & Analysis | `/settings/detection` |
| Settings — Models | `/settings/models` |
| Settings — Audit | `/settings/audit` |

All routes beyond `/login` require an authenticated local session; there is no per-page role gating (section 2.2).

### 12.2 Shared Components

- **`AppShell`** — layout with a navigation sidebar, SSE connection indicator, and account menu.
- **`StatCard`** — dashboard metric card with variation vs. the previous period.
- **`DefectTrendChart`** — line chart by defect type with a period selector.
- **`AnnotatedImageViewer`** — viewer with zoom/pan, an SVG bounding-box overlay synchronized with the detections list, an original/annotated toggle, and a class legend (color + text, FE-10). Images are fetched from the local-disk-serving endpoint (section 3.1) — no expiring-URL handling needed.
- **`DefectBadge`** — defect-class badge (consistent color across the app) and **`SeverityBadge`**.
- **`InspectionTable`** — paginated table reused across the dashboard and search.
- **`PathField`** — validated local-path input (FE-05) with inline existence/readability feedback from the backend.
- **`ProcessingStatusStepper`** — Queue → Detection → Analysis → Completed steps, driven by SSE.
- **`ChatWindow`** — message stream with incremental rendering (SSE), a tool-in-progress indicator, and contextual suggestions.
- **`FilterBar`** — combinable filters persisted in the URL (shareable).
- **`ErrorToast`** — maps `error.code` to a localized message.
- **`AuthGuard`** — route protection requiring a logged-in session (no role variants, section 2.2).

### 12.3 State Management

- Session token in memory (auth context); silent refresh before expiry; logout on refresh failure.
- TanStack Query as the source of truth for server data; SSE events invalidate the affected queries (`stats`, `inspections`).
- Ingestion state local to the flow; reloading the page does not lose records already accepted by the backend (202).

---

## 13. Security and Access Control

- **Localhost-only by default.** Every service (API, frontend, database, Redis) binds to `127.0.0.1`; nothing on the machine is reachable from the network out of the box. This is the system's primary security property (section 3.1) — a system with no listening network service on the LAN/internet has meaningfully less attack surface than any client-server system, on-premise or not.
- Exposing the interface beyond `localhost` (e.g., to reach it from another device on the same LAN) is an explicit, unsupported opt-in the operator may configure; TLS and network-level access control become the operator's responsibility if they do so.
- Session authentication via a Bearer token; short-lived access token with refresh; the frontend never stores it in `localStorage`.
- Passwords: Argon2id; minimum 10-character policy; progressive lockout after failed attempts.
- No role hierarchy — any authenticated local account can perform any action (section 2.2); the only per-resource check is ownership for private data like chat sessions.
- Cloud LLM API keys (when opted into, section 5.2) encrypted at rest (Fernet/AES-GCM with a key from env); the API exposes only `configured` + the last 4 characters.
- Immutable audit trail for configuration changes, model activation, analysis review, board disposition, and account management (FR-16, RN-06).
- Ad hoc file imports (FR-03) are validated by magic bytes (not just extension); the primary directory-scan/watch-folder flow never accepts arbitrary uploaded bytes, only local path references the backend itself validates for existence and readability.

---

## 14. Operational Requirements

### 14.1 Deployment / Runtime

- **Docker Compose** stack: `api` (FastAPI), `worker-inference` (GPU access via `deploy.resources` / NVIDIA Container Toolkit when available), `worker-agents`, `beat` (periodic tasks: retention purge), `db` (PostgreSQL 16), `redis`, `frontend` (Next.js). Every service's published port is bound to `127.0.0.1` — none are exposed to the LAN by default.
- Environment variables control: connections (DB/Redis), the secret-encryption key, session token lifetimes, the app-data/reports/exports directories, and LLM defaults (overridable via FR-13, local by default).
- Model weights and the golden-set reference data are mounted from a local volume; the active version is resolved at worker startup.
- The watch root is mounted **read-only** into the `api`/`worker-inference` containers (they only ever read from it, section 3.5); the app-data directory (annotated images, reports, exports, database volume) is a separate, writable local volume.
- Logs to stdout (JSON); local log retention ≥ 90 days.

### 14.2 CI (GitHub Actions)

- Backend: lint (ruff), type-check (mypy), migrations, test suite with ephemeral Postgres/Redis, Docker image build.
- Frontend: dependency install, lint, type-check, unit tests, production build, Playwright E2E against the Compose stack.
- `docker-compose.yml` validation and build of every image on each PR.
- AI pipeline tests with a mocked LLM — CI does not depend on an external provider.
- Ingestion tests run against a temporary directory fixture standing in for the watch root — no real camera or network storage involved.

### 14.3 Development Environment

- `docker compose up` brings up the full stack with seeds (an initial dev account, default config, model v1.0.0 registered from `weights/best.pt`, a sample watch-root fixture with a handful of dataset images for local testing).
- A local LLM via LM Studio/Ollama is the documented default; no cloud API key is required to run or evaluate the project.

---

## 15. Phased Delivery Plan

The system is delivered in three incremental phases; each phase ends with the system usable end-to-end within its scope. Phase 1 operates **with no LLM configured at all** — the knowledge-base baseline analysis covers 100% of inspections — which allows a complete offline demo from day one.

| Phase | Name | Deliverables | Requirements covered | Completion criterion |
|---|---|---|---|---|
| 1 | Inspection Core (MVP) | Local auth (single account), directory-based ingestion (watch mode + one-off scan), YOLO detection pipeline with baseline analysis, dashboard, analysis detail with annotated viewer, search/history, status SSE, health and OpenAPI | FR-01, FR-02, FR-03, FR-04, FR-05, FR-06 (baseline), FR-07, FR-08, FR-14, FR-15; FE-01–FE-05, FE-09, FE-10 | An operator logs in, points the app at a folder of PCB images, and views detections + baseline analysis end-to-end, with no LLM configured |
| 2 | Intelligence | Agent chain (Analyst → Reviewer → Summarizer), chat with tool-calling and streaming, analysis validation and per-detection feedback, manual annotation, LLM configuration (local-first) | FR-06 (agents), FR-09, FR-10, FR-13 (LLM/policy); FE-06, feedback actions in FE-03 | In-depth analysis generated in `conditional` and `on_demand` modes; chat answers with real data via tools, using a local LLM by default |
| 3 | Mature Operation | Reports (CSV/XLSX/PDF), model versioning with golden set, quality alerts, dataset export, full audit, retention, complete settings area | FR-11, FR-12, FR-16, FR-17, FR-18, FR-19; FE-07, FE-08 | A new model version is registered, evaluated, and activated with no downtime; a feedback dataset is exported in YOLO format |

---

## 16. Requirements Traceability Matrix

| Requirement | Implementation artifact (planned) |
|---|---|
| FR-01 | `app/auth/router.py`, `app/auth/service.py` |
| FR-02 | `app/users/router.py`, `app/users/models.py` |
| FR-03 | `app/inspections/router.py::{scan,import}`, `app/ingestion/watcher.py`, `app/ingestion/naming.py` (batch/board convention) |
| FR-04 | `app/tasks/pipeline.py`, `app/inspections/state.py` (state machine) |
| FR-05 | `app/inference/worker.py`, `app/inference/annotator.py` |
| FR-06 | `app/knowledge/defects.py` (knowledge base), `app/agents/graph.py` (LangGraph), `app/agents/prompts/`, `app/agents/policy.py` (conditional mode) |
| FR-07 | `app/inspections/router.py::list`, `app/inspections/filters.py` |
| FR-08 | `app/stats/router.py`, `app/stats/service.py` (+ Redis cache) |
| FR-09 | `app/chat/router.py`, `app/chat/agent.py`, `app/chat/tools.py` |
| FR-10 | `app/analyses/router.py::review`, `app/detections/router.py::feedback`, `app/inspections/router.py::{disposition,annotations}` |
| FR-11 | `app/reports/router.py`, `app/reports/generators/{csv,xlsx,pdf}.py` |
| FR-12 | `app/settings/models_router.py`, `app/inference/loader.py`, `app/inference/golden_set.py` (evaluation) |
| FR-13 | `app/settings/config_router.py`, `app/core/config_store.py` |
| FR-14 | `app/events/sse.py` (Redis pub/sub → SSE) |
| FR-15 | `app/core/health.py`, FastAPI OpenAPI |
| FR-16 | `app/audit/service.py`, `app/audit/models.py` |
| FR-17 | `app/tasks/retention.py` (Celery beat) |
| FR-18 | `app/datasets/exporter.py` (YOLO format), `app/datasets/router.py` |
| FR-19 | `app/alerts/service.py`, `app/alerts/router.py`, `app/tasks/alert_monitor.py` (Celery beat) |
| FE-01 | `src/app/login/page.tsx`, `src/contexts/AuthContext.tsx` |
| FE-02 | `src/app/page.tsx`, `src/components/dashboard/*` |
| FE-03 | `src/app/inspections/[id]/page.tsx`, `src/components/viewer/AnnotatedImageViewer.tsx` |
| FE-04 | `src/app/inspections/page.tsx`, `src/components/filters/FilterBar.tsx` |
| FE-05 | `src/app/ingestion/page.tsx`, `src/components/ingestion/PathField.tsx`, `src/components/ingestion/ProcessingStatusStepper.tsx` |
| FE-06 | `src/app/chat/*`, `src/components/chat/ChatWindow.tsx` |
| FE-07 | `src/app/reports/page.tsx` |
| FE-08 | `src/app/settings/*`, `src/components/auth/AuthGuard.tsx` |
| FE-09 | `src/hooks/useEventStream.ts` |
| FE-10 | Cross-cutting patterns (ARIA, color legend, responsiveness) |

---

## 17. Out of Scope

Not covered in this project's scope:

- **Hosted/cloud deployment of the service.** This is local software by design (section 3.1); running it as a remotely accessible service is not a goal of this project.
- **Multi-user role-based access control and permission administration.** Deliberately out of scope here — the author addresses that domain in a separate portfolio project; PCB-Inspect intentionally stays a single-account, full-access tool (section 2.2).
- **Remote/internet access to a running instance.** The interface binds to `localhost` only by default; LAN exposure, if ever desired, is an explicit, unsupported opt-in for the operator (section 13).
- **Native camera integration.** The camera's own software is responsible for capturing and saving images to disk; PCB-Inspect only consumes the resulting files.
- **Native desktop packaging (Tauri/Electron).** The browser-based UI running locally is the baseline for this project; wrapping the same stack in a native shell — including a real OS folder picker for FE-05 — is a reasonable future enhancement, not a requirement now.
- Model retraining/fine-tuning within the software (the training cycle stays external; the software only versions and activates weights)
- Detecting defects outside the 6 trained classes
- Multi-tenancy (multiple isolated inspection stations sharing one instance)
- Predictive process-failure analysis (only descriptive trends and threshold-based alerts in this version)
- Active learning / assisted annotation (annotating undetected defects is manual; retraining consumes the dataset exported by FR-18 externally)
- External notifications (email/Slack/WhatsApp) — in-app SSE events only
