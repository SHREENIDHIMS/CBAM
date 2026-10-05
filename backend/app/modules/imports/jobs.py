"""Celery task for processing an import batch (R1-025, R1-003).

The task is idempotent: it takes only ids, resumes after the last committed chunk, and does
nothing for a finished batch, so a redelivery (acks_late) or a retry is safe. Transient
failures retry with exponential backoff; when retries run out the batch is marked `failed` with
a short code. A failed batch is final: retrying it from the API creates a new batch.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Engine, text

from app.core.clock import Clock, SystemClock
from app.core.config import get_settings
from app.core.db import get_engine, tenant_session
from app.core.jobs import celery_app
from app.core.storage import get_object_store
from app.modules.imports import service
from app.modules.imports.processing import process_batch

MAX_RETRIES = 5
_BACKOFF_SECONDS = 10
_BACKOFF_CAP_SECONDS = 600

log = structlog.get_logger()

# Sends a batch to the queue. A function so the API can swap it in tests.
Enqueuer = Callable[[UUID, UUID], None]


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.modules.imports.jobs.process_batch",
    bind=True,
    acks_late=True,
    max_retries=MAX_RETRIES,
    reject_on_worker_lost=False,  # a task that kills its worker must not be redelivered forever
)
def process_batch_task(self: Any, tenant_id: str, batch_id: str) -> str:
    final = self.request.retries >= MAX_RETRIES
    try:
        return process_batch(
            get_engine(),
            get_object_store(),
            SystemClock(),
            UUID(tenant_id),
            UUID(batch_id),
            final_attempt=final,
        )
    except Exception as exc:
        if final or getattr(exc, "permanent", False):
            raise
        countdown = min(_BACKOFF_SECONDS * 2**self.request.retries, _BACKOFF_CAP_SECONDS)
        raise self.retry(exc=exc, countdown=countdown) from None


def enqueue_batch(tenant_id: UUID, batch_id: UUID) -> None:
    """Queue processing for a batch. Call it after the batch's transaction has committed."""
    process_batch_task.apply_async(
        args=[str(tenant_id), str(batch_id)],
        task_id=f"import:{batch_id}",
        # A broker outage must not hold the upload request open for long.
        retry=True,
        retry_policy={"max_retries": 2, "interval_start": 0.1, "interval_step": 0.2},
    )


def get_enqueuer() -> Enqueuer:
    """FastAPI dependency; tests override it."""
    return enqueue_batch


def safe_enqueue(enqueue: Enqueuer, tenant_id: UUID, batch_id: UUID) -> bool:
    """Enqueue without ever failing the request: the batch is already saved, so a broker
    outage leaves it `received` (logged by id) instead of turning an accepted upload into a 500."""
    try:
        enqueue(tenant_id, batch_id)
    except Exception as exc:
        log.error("import_enqueue_failed", batch_id=str(batch_id), error=type(exc).__name__)
        return False
    return True


def sweep_stale(engine: Engine, clock: Clock, enqueue: Enqueuer, *, minutes: int) -> int:
    """Re-queue batches whose job was lost: `received`/`queued` for `minutes`, or working with
    an expired lease. Safe to repeat: the job does nothing for a finished batch or one with a
    fresh lease, and takes over only an expired one (counting an attempt).

    A system job. It reads only the ids of active tenants (`cbam.tenants`, platform mode, no
    business tables) and then queries batches per tenant under row-level security. Suspended
    or closed tenants are not swept."""
    cutoff = clock.now() - timedelta(minutes=minutes)
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        tenants = list(
            s.execute(text("select id from cbam.tenants where status = 'active'")).scalars()
        )
    sent = 0
    for tenant_id in tenants:
        with tenant_session(engine, tenant_id=tenant_id) as s:
            batch_ids = service.stale_batch_ids(s, tenant_id, older_than=cutoff, now=clock.now())
        sent += sum(safe_enqueue(enqueue, tenant_id, b) for b in batch_ids)
    return sent


@celery_app.task(name="imports.sweep_stale_batches")  # type: ignore[untyped-decorator]
def sweep_stale_batches() -> int:
    return sweep_stale(
        get_engine(),
        SystemClock(),
        enqueue_batch,
        minutes=get_settings().import_stale_batch_minutes,
    )
