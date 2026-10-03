"""Celery app and beat schedule."""

import structlog
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

celery_app = Celery("cbam", broker=get_settings().redis_url)
celery_app.conf.beat_schedule = {
    "heartbeat": {"task": "app.core.jobs.heartbeat", "schedule": 300.0},
    "audit-verify-chains": {
        "task": "app.core.jobs.verify_audit_chains",
        "schedule": crontab(hour=2, minute=30),
    },
}


class AuditChainBrokenError(RuntimeError):
    """A tenant's audit hash chain no longer verifies. This must page someone."""


@celery_app.task(name="app.core.jobs.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    return "ok"


@celery_app.task(name="app.core.jobs.verify_audit_chains")  # type: ignore[untyped-decorator]
def verify_audit_chains() -> str:
    """Nightly: recompute every audit chain (R1-023). Fails loudly if any is broken."""
    from app.core.audit import verify_all_chains
    from app.core.db import get_engine

    broken = verify_all_chains(get_engine())
    if broken:
        structlog.get_logger().error("audit_chain_broken", chains=broken)
        raise AuditChainBrokenError(f"audit chain broken for: {sorted(broken)}")
    return "ok"
