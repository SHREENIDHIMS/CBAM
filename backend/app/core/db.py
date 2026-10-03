"""Database access: engine, and a transaction that carries the tenant for RLS.

Every business query runs inside `tenant_session`. It sets `app.tenant_id` (and
`app.user_id`) with `set_config(..., true)`, i.e. transaction-local like SET LOCAL, so a
pooled connection can never leak one tenant's context into the next request
(CLAUDE.md rule 7). With no tenant set, RLS returns no rows.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    """Engine for the app role `cbam_app` (never the owner or postgres)."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return make_engine(url)


def _set_context(
    session: Session, *, tenant_id: UUID | None, user_id: UUID | None, platform: bool
) -> None:
    for key, value in (
        ("app.tenant_id", str(tenant_id) if tenant_id else ""),
        ("app.user_id", str(user_id) if user_id else ""),
        ("app.is_platform", "on" if platform else ""),
    ):
        session.execute(text("select set_config(:k, :v, true)"), {"k": key, "v": value})


@contextmanager
def tenant_session(
    engine: Engine,
    *,
    tenant_id: UUID | None,
    user_id: UUID | None = None,
    platform: bool = False,
) -> Iterator[Session]:
    """One transaction scoped to a tenant. Commits on success, rolls back on error.

    `platform=True` is for verified platform admins managing tenants, users and
    memberships only; business tables never honour it.
    """
    with Session(engine) as session, session.begin():
        _set_context(session, tenant_id=tenant_id, user_id=user_id, platform=platform)
        yield session


def run_as_tenant[T](
    engine: Engine,
    tenant_id: UUID,
    job: Callable[[Session], T],
    *,
    user_id: UUID | None = None,
) -> T:
    """Worker helper: run a job's database work as one tenant."""
    with tenant_session(engine, tenant_id=tenant_id, user_id=user_id) as session:
        return job(session)
