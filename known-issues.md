# Known Issues

## `worker-inference` crashes on startup: missing `libxcb.so.1`

**Status:** resolved (issue #21)
**Found:** 2026-07-11, while smoke-testing the full `docker compose up` stack with real model weights (`weights/best.pt`, no `INFERENCE_BACKEND=fake`).
**Affected service:** `worker-inference` (backend Celery worker, `WORKER_ROLE=inference`)

### Symptom

The warm-start hook (`app/tasks/pipeline.py::_warm_start_inference_worker`) fails immediately on
container boot:

```
File "/usr/local/lib/python3.12/site-packages/ultralytics/utils/__init__.py", line 24, in <module>
    import cv2
File "/usr/local/lib/python3.12/site-packages/cv2/__init__.py", line 181, in <module>
    bootstrap()
File "/usr/local/lib/python3.12/site-packages/cv2/__init__.py", line 153, in bootstrap
    native_module = importlib.import_module("cv2")
ImportError: libxcb.so.1: cannot open shared object file: No such file or directory
app.tasks.errors.TransientProcessingError: Failed to load model weights: libxcb.so.1: cannot open shared object file: No such file or directory
```

`GET /health` correctly reflects the broken state (`worker.model_loaded: false`), but the worker
process itself stays up (Celery keeps accepting tasks), so any image scanned/imported gets stuck in
`QUEUED`/`PROCESSING` and never produces a detection.

### Root cause

`backend/Dockerfile` builds on `python:3.12-slim`, which ships no system graphics libraries. The
`ultralytics` dependency (`backend/pyproject.toml`) pulls in `opencv-python` (the full,
GUI-capable build) transitively, and that package's `cv2` native module requires `libGL.so.1`,
`libxcb.so.1`, `libglib2.0`, etc. at import time, even in a fully headless container. None of those
are installed, so `import cv2` fails as soon as ultralytics is imported.

### Why CI doesn't catch this

The e2e suite (`frontend/e2e/inspection-flow.spec.ts`) and CI's `e2e` job run
`worker-inference` with `INFERENCE_BACKEND=fake`, which never imports `ultralytics`/`cv2`. The bug
only surfaces when the real model path is exercised, i.e. real local usage with `weights/best.pt`.

### Fix applied

`backend/Dockerfile` now forces `opencv-python-headless` as the final installed `cv2` build
(uninstalling both possible variants first, then a clean headless install — `ultralytics` hard-depends
on plain `opencv-python`, and pip has no native way to substitute it in a single resolve, so the
uninstall-then-reinstall is what makes the outcome deterministic regardless of pip's install order).
`opencv-python-headless` is also declared directly in `backend/pyproject.toml` for visibility.

Regression coverage: the `docker-build` CI job now builds the backend image and runs
`python -c "from app.inference.model import _yolo_class; _yolo_class()"` inside it — the real
(non-fake) inference import path, without needing model weights or a GPU, since the crash happens
at `import cv2` time.
