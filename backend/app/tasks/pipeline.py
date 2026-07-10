from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.pipeline.run_inference")
def run_inference(inspection_image_id: str) -> None:
    """Runs YOLO detection for an ingested image. Implemented in FR-05 (issue 5)."""
    raise NotImplementedError


@celery_app.task(name="app.tasks.pipeline.run_agent_analysis")
def run_agent_analysis(inspection_image_id: str) -> None:
    """Runs the Analyst/Reviewer/Summarizer chain. Implemented in FR-06 (issue 6+)."""
    raise NotImplementedError
