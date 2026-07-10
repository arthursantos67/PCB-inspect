# PCB-Inspect

Local, on-premise software for automated PCB defect inspection. A trained YOLO11x model detects six defect types on printed circuit boards (missing hole, mouse bite, open circuit, short, spur, spurious copper) directly from images saved locally by a production-line camera; an AI agent pipeline turns each detection into an interpreted technical analysis (cause, impact, suggested fix).

This is **not** a hosted web platform — it runs entirely on the machine(s) responsible for the inspection station, with every service bound to `localhost`. See section 3.1 of the PRD for the full rationale.

Full requirements, architecture, and data model: [pcb-inspect-product-requirements-document.md](pcb-inspect-product-requirements-document.md).
Phase 1 issue backlog (source for the GitHub issues): [issues-phase1.md](issues-phase1.md).

## Status

Portfolio project. The model has been trained and locally validated; implementation follows the phased plan in PRD section 15 (Phase 1: inspection core with no LLM required).

## Model weights

`weights/best.pt` is not tracked in this repository (114 MB, over GitHub's 100 MB limit — and model binaries generally don't belong in git history). To obtain it:

- Download directly: `gdown --fuzzy https://drive.google.com/file/d/1PmHc25ne_8U5Buoi5bvyq9G1K2jsAadz/view?usp=sharing -O weights/best.pt`
- Or retrain from scratch using the [training notebook](https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing).

## Training dataset

Based on the [PCB Defects dataset](https://www.kaggle.com/datasets/akhatova/pcb-defects) (Kaggle), augmented with Roboflow/Albumentations. See PRD section 4.1 and 4.3 for metrics and known limitations.
