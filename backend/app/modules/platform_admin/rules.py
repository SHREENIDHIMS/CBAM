"""Platform admin rules (R1-001). Pure functions: no database, clock or network."""

import re
from collections.abc import Sequence

from app.core.decisions import Decision
from app.core.permissions import TENANT_ASSIGNABLE_ROLES

RULE_TENANT_STATUS = "R1-001.tenant_status"
RULE_VERSION = "1"

# Closed is terminal: records are closed or superseded, never deleted or silently reopened.
_ALLOWED: dict[str, frozenset[str]] = {
    "active": frozenset({"suspended", "closed"}),
    "suspended": frozenset({"active", "closed"}),
    "closed": frozenset(),
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _decision(outcome: str, reason: str) -> Decision:
    return Decision(
        rule_id=RULE_TENANT_STATUS,
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome=outcome,
        reason=reason,
    )


def tenant_status_decision(current: str, target: str, *, reason: str | None) -> Decision:
    if current not in _ALLOWED or target not in _ALLOWED:
        return _decision("BLOCKED", f"unknown status in {current!r} -> {target!r}")
    if target == current:
        return _decision("BLOCKED", "status is unchanged")
    if target not in _ALLOWED[current]:
        return _decision("BLOCKED", f"{current} -> {target} is not allowed")
    if not (reason and reason.strip()):
        return _decision("REASON_REQUIRED", f"{current} -> {target} needs a reason")
    return _decision("ALLOWED", f"{current} -> {target}")


def clean_roles(roles: Sequence[str]) -> tuple[str, ...]:
    """Validated, de-duplicated roles for a tenant member. platform_admin is never allowed."""
    if not roles:
        raise ValueError("at least one role is required")
    bad = [r for r in roles if r not in TENANT_ASSIGNABLE_ROLES]
    if bad:
        raise ValueError(f"not an assignable role: {bad[0]!r}")
    return tuple(dict.fromkeys(roles))


def clean_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.match(cleaned):
        raise ValueError("not a valid email address")
    return cleaned
