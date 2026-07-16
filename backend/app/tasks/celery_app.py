from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "pcb_inspect",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.pipeline",
        "app.tasks.retention",
        "app.tasks.alert_monitor",
        "app.tasks.ingestion",
        "app.tasks.models",
    ],
)

celery_app.conf.update(
    # NFR-03: a task in progress when its worker dies returns to the queue instead of
    # being lost, rather than being acked (and dropped) the moment it's picked up.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="agents",
    task_queues={
        "inference": {"exchange": "inference", "routing_key": "inference"},
        "agents": {"exchange": "agents", "routing_key": "agents"},
        # Housekeeping (ingestion polling, alerting, retention) must survive a dead/misconfigured
        # agents worker or LLM connection — routed off "agents" so it never shares fate with it.
        "housekeeping": {"exchange": "housekeeping", "routing_key": "housekeeping"},
    },
    task_routes={
        "app.tasks.pipeline.run_inference": {"queue": "inference"},
        "app.tasks.pipeline.run_agent_analysis": {"queue": "agents"},
        "app.tasks.ingestion.poll_watch_root": {"queue": "housekeeping"},
        "app.tasks.alert_monitor.evaluate_thresholds": {"queue": "housekeeping"},
        "app.tasks.retention.purge_expired": {"queue": "housekeeping"},
        # Both share the inference worker's queue (FR-12) — see app/tasks/models.py's module
        # docstring for why that's what makes the no-downtime activation switch safe.
        "app.tasks.models.run_model_evaluation": {"queue": "inference"},
        "app.tasks.models.reload_inference_model": {"queue": "inference"},
    },
    beat_schedule={
        "retention-purge": {
            "task": "app.tasks.retention.purge_expired",
            "schedule": 86400.0,  # once a day; see FR-17
        },
        "alert-monitor": {
            "task": "app.tasks.alert_monitor.evaluate_thresholds",
            "schedule": 300.0,  # every 5 minutes; see FR-19
        },
        "watch-root-poll": {
            "task": "app.tasks.ingestion.poll_watch_root",
            "schedule": 5.0,  # watch mode (continuous), see FR-03
        },
    },
)
