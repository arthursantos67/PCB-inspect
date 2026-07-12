FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./

# `ultralytics` hard-depends on the GUI-capable `opencv-python` (needs libGL/libxcb/etc. at
# import time, even headless — see known-issues.md history). `python:3.12-slim` has none of
# those system libs, so `import cv2` crashes on boot. pip has no way to tell it "install
# opencv-python-headless instead of opencv-python" in one pass — both can end up installed,
# shadowing each other's files non-deterministically — so the fix is a clean uninstall of
# both first, then a fresh install of only the headless build.
RUN pip install --no-cache-dir . \
    && pip uninstall -y opencv-python opencv-python-headless \
    && pip install --no-cache-dir --no-deps opencv-python-headless \
    && chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
