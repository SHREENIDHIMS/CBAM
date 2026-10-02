"""Celery app and beat schedule. One no-op task proves worker and beat run."""

from celery import Celery

from app.core.config import get_settings

celery_app = Celery("cbam", broker=get_settings().redis_url)
celery_app.conf.beat_schedule = {
    "heartbeat": {"task": "app.core.jobs.heartbeat", "schedule": 300.0},
}


@celery_app.task(name="app.core.jobs.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    return "ok"
