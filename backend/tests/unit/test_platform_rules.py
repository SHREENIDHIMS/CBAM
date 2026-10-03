"""R1-001: platform admin rules. Pure functions, no database."""

import pytest

from app.modules.platform_admin import rules


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("active", "suspended"),
        ("suspended", "active"),
        ("active", "closed"),
        ("suspended", "closed"),
    ],
)
def test_allowed_tenant_status_changes(current: str, target: str) -> None:
    assert (
        rules.tenant_status_decision(current, target, reason="requested by client").outcome
        == "ALLOWED"
    )


@pytest.mark.parametrize("target", ["active", "suspended"])
def test_a_closed_tenant_stays_closed(target: str) -> None:
    """Records are closed, never deleted or reopened by accident (docs/DATABASE.md section 1)."""
    d = rules.tenant_status_decision("closed", target, reason="oops")
    assert d.outcome == "BLOCKED"


def test_same_or_unknown_status_is_blocked() -> None:
    assert rules.tenant_status_decision("active", "active", reason="x").outcome == "BLOCKED"
    assert rules.tenant_status_decision("active", "deleted", reason="x").outcome == "BLOCKED"
    assert rules.tenant_status_decision("gone", "active", reason="x").outcome == "BLOCKED"


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_every_status_change_needs_a_reason(reason: str | None) -> None:
    assert (
        rules.tenant_status_decision("active", "suspended", reason=reason).outcome
        == "REASON_REQUIRED"
    )


def test_roles_are_validated_and_deduplicated() -> None:
    assert rules.clean_roles(["operations", "operations", "reviewer"]) == ("operations", "reviewer")


@pytest.mark.parametrize(
    "roles", [[], ["platform_admin"], ["operations", "platform_admin"], ["superuser"], [""]]
)
def test_bad_role_lists_are_refused(roles: list[str]) -> None:
    with pytest.raises(ValueError):
        rules.clean_roles(roles)


@pytest.mark.parametrize("email", ["a@example.test", "First.Last+tag@sub.example.co.uk"])
def test_good_emails_are_normalised(email: str) -> None:
    assert rules.clean_email(f"  {email.upper()} ") == email.lower()


@pytest.mark.parametrize(
    "email", ["", "plain", "a@b", "a@@b.co", "a b@example.test", "@example.test", "a@.test"]
)
def test_bad_emails_are_refused(email: str) -> None:
    with pytest.raises(ValueError):
        rules.clean_email(email)
