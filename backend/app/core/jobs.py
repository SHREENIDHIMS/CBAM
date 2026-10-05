"""Celery app and beat schedule."""

import structlog
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

celery_app = Celery("cbam", broker=get_settings().redis_url, include=["app.modules.imports.jobs"])
_memory_kb = get_settings().celery_worker_max_memory_per_child_kb
if _memory_kb:  # recycle a worker process that grows too large instead of letting it be killed
    celery_app.conf.worker_max_memory_per_child = _memory_kb
celery_app.conf.beat_schedule = {
    "imports-sweep-stale-batches": {"task": "imports.sweep_stale_batches", "schedule": 300.0},
    "heartbeat": {"task": "app.core.jobs.heartbeat", "schedule": 300.0},
    "escalate-overdue-tasks": {
        "task": "app.core.jobs.escalate_overdue_tasks",
        "schedule": crontab(hour=6, minute=0),
    },
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


@celery_app.task(name="app.core.jobs.escalate_overdue_tasks")  # type: ignore[untyped-decorator]
def escalate_overdue_tasks() -> int:
    """Daily: raise the escalation level of overdue tasks in every tenant (R1-022)."""
    from uuid import UUID

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.core.clock import SystemClock
    from app.core.db import get_engine, run_as_tenant, tenant_session
    from app.modules.tasks.service import escalate_overdue

    engine, clock = get_engine(), SystemClock()
    thresholds = get_settings().task_escalation_overdue_days
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        tenant_ids = list(
            s.execute(text("select id from cbam.tenants where status = 'active'")).scalars()
        )
    total = 0
    for tenant_id in tenant_ids:

        def escalate(session: Session, tenant_id: UUID = tenant_id) -> int:
            return escalate_overdue(
                session,
                tenant_id=tenant_id,
                as_of=clock.today_uk(),
                thresholds_days=thresholds,
                now=clock.now(),
            )

        total += run_as_tenant(engine, tenant_id, escalate)
    return total
