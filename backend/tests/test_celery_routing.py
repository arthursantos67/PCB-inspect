"""Celery queue routing tests (issue #21, item 5): `poll_watch_root` (FR-03),
`evaluate_thresholds` (FR-19), and `purge_expired` (FR-17) must route to a queue independent
of `worker-agents` — previously they fell through `task_default_queue="agents"`, so a dead/
misconfigured agents worker silently took down watch-mode ingestion, alerting, and retention
too, not just LLM agent analysis.
"""

from app.tasks.celery_app import celery_app


def test_housekeeping_tasks_route_off_the_agents_queue() -> None:
    routes = celery_app.conf.task_routes
    assert routes["app.tasks.ingestion.poll_watch_root"]["queue"] == "housekeeping"
    assert routes["app.tasks.alert_monitor.evaluate_thresholds"]["queue"] == "housekeeping"
    assert routes["app.tasks.retention.purge_expired"]["queue"] == "housekeeping"
    # Report generation (FR-11, Issue 35) must survive a dead/misconfigured agents worker too.
    assert routes["app.tasks.reports.generate_report"]["queue"] == "housekeeping"


def test_inference_and_agents_routes_unchanged() -> None:
    routes = celery_app.conf.task_routes
    assert routes["app.tasks.pipeline.run_inference"]["queue"] == "inference"
    assert routes["app.tasks.pipeline.run_agent_analysis"]["queue"] == "agents"


def test_housekeeping_queue_is_declared() -> None:
    assert "housekeeping" in celery_app.conf.task_queues
