from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.alert_monitor.evaluate_thresholds")
def evaluate_thresholds() -> None:
    """Evaluates defect-rate thresholds and raises alerts. Implemented in FR-19."""
    raise NotImplementedError
