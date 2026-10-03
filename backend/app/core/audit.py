"""Append-only audit events (R1-023, CLAUDE.md rule 8).

Every business state change records who, when, before, after and why. The hash chain is
computed inside PostgreSQL (see migration 0003), so the app cannot forge or reorder it.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.core.ids import uuid7
from app.core.money import dumps

ActorType = Literal["user", "supplier", "system", "job"]


def record(
    session: Session,
    *,
    tenant_id: UUID | None,
    actor_type: ActorType,
    actor_id: UUID | None,
    action: str,
    object_type: str,
    object_id: UUID,
    occurred_at: datetime,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | None = None,
) -> UUID:
    """Write one audit event in the caller's transaction.

    `occurred_at` comes from the injected clock, not from now(). `tenant_id` must match the
    session's tenant (row-level security refuses anything else); use None only for platform
    events written in platform mode. Never put personal data in before/after: log IDs.
    """
    if occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    event_id = uuid7()
    session.execute(
        text(
            """
            insert into cbam.audit_events
              (id, tenant_id, occurred_at, actor_type, actor_id, action, object_type,
               object_id, before, after, reason, request_id)
            values
              (:id, :tenant_id, :occurred_at, :actor_type, :actor_id, :action, :object_type,
               :object_id, cast(:before as jsonb), cast(:after as jsonb), :reason, :request_id)
            """
        ),
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "occurred_at": occurred_at,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "before": None if before is None else dumps(before),
            "after": None if after is None else dumps(after),
            "reason": reason,
            "request_id": request_id,
        },
    )
    return event_id


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    first_bad_chain_seq: int | None = None


def verify_chain(session: Session, tenant_id: UUID | None) -> ChainResult:
    """Recompute the hash chain for one tenant (None = platform chain)."""
    bad = session.execute(
        text("select bad_chain_seq from cbam.audit_verify_chain(:t)"), {"t": tenant_id}
    ).scalar_one_or_none()
    return ChainResult(ok=bad is None, first_bad_chain_seq=bad)


def verify_all_chains(engine: Engine) -> dict[str, list[int]]:
    """Nightly job body: verify every tenant chain and the platform chain.

    Returns {tenant_id or 'platform': [first bad chain_seq]} for broken chains only.
    """
    broken: dict[str, list[int]] = {}
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        tenant_ids = list(s.execute(text("select id from cbam.tenants")).scalars().all())
        platform_result = verify_chain(s, None)
        if not platform_result.ok and platform_result.first_bad_chain_seq is not None:
            broken["platform"] = [platform_result.first_bad_chain_seq]
    for tenant_id in tenant_ids:
        with tenant_session(engine, tenant_id=tenant_id) as s:
            result = verify_chain(s, tenant_id)
            if not result.ok and result.first_bad_chain_seq is not None:
                broken[str(tenant_id)] = [result.first_bad_chain_seq]
    return broken


def to_json(value: Any) -> str:
    """Helper for tests/tools: the canonical JSON the app writes (Decimals as strings)."""
    return json.dumps(json.loads(dumps(value)), sort_keys=True)
