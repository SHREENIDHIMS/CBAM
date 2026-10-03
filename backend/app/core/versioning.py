"""Optimistic concurrency with `row_version` and `If-Match` (R1-045).

Approvals and updates carry the version the user saw. A write against a newer version is
refused with 409, so two approvers can never both "win" (CLAUDE.md rule 17).
"""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PreconditionRequiredError, StaleVersionError, TenantMismatchError

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_IF_MATCH = re.compile(r'^(?:W/)?"?(\d+)"?$')


def etag(row_version: int) -> str:
    return f'"{row_version}"'


def parse_if_match(header: str | None) -> int:
    """The row version from an If-Match header (`"3"`, `W/"3"` or `3`)."""
    if header is None:
        raise PreconditionRequiredError("Send the row version in an If-Match header")
    match = _IF_MATCH.match(header.strip())
    if match is None or int(match.group(1)) < 1:
        raise PreconditionRequiredError('If-Match must carry a row version, for example "3"')
    return int(match.group(1))


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier {name!r}")
    return name


def update_versioned(
    session: Session,
    table: str,
    *,
    row_id: UUID,
    expected_version: int,
    values: dict[str, Any],
) -> int:
    """Update one row only if it is still at `expected_version`; returns the new version.

    Raises StaleVersionError (409) if someone else changed it first, and TenantMismatchError
    (404) if the row is not visible to this tenant, so another tenant's rows look absent.
    """
    if "row_version" in values:
        raise ValueError("row_version is managed here; do not set it")
    table_name = _ident(table)
    assignments = ", ".join(f"{_ident(col)} = :v_{col}" for col in values)
    params: dict[str, Any] = {f"v_{col}": value for col, value in values.items()}
    params.update({"row_id": row_id, "expected": expected_version})
    sql = (  # identifiers validated above; values are bound parameters
        f"update cbam.{table_name} set {assignments}"  # noqa: S608
        f"{', ' if assignments else ''}row_version = row_version + 1, updated_at = now() "
        "where id = :row_id and row_version = :expected returning row_version"
    )
    new_version = session.execute(text(sql), params).scalar_one_or_none()
    if new_version is not None:
        return int(new_version)
    exists = session.execute(
        text(f"select 1 from cbam.{table_name} where id = :row_id"),  # noqa: S608
        {"row_id": row_id},
    ).scalar_one_or_none()
    if exists is None:
        raise TenantMismatchError()
    raise StaleVersionError("This record changed since you loaded it; reload and try again")
