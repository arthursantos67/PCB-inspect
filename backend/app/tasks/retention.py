from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.retention.purge_expired")
def purge_expired() -> None:
    """Archives/purges records past the retention window. Implemented in FR-17."""
    raise NotImplementedError
