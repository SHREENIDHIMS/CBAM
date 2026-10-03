"""R1-002: permission matrix tests show least-privilege access."""

import pytest

from app.core.permissions import (
    ALL_PERMISSIONS,
    MFA_REQUIRED_ROLES,
    ROLE_PERMISSIONS,
    ROLES,
    TAX_AGENT_FORBIDDEN,
    TENANT_ASSIGNABLE_ROLES,
    mfa_required,
    permissions_for,
)


def test_every_role_has_an_entry() -> None:
    assert set(ROLES) == set(ROLE_PERMISSIONS)


def test_roles_match_the_database_constraint() -> None:
    """Migration 0002 lists the same eight roles; keep them in step."""
    assert set(ROLES) == {
        "platform_admin", "operations", "client_admin", "reviewer",
        "approver", "supplier", "tax_agent", "domain_owner",
    }  # fmt: skip


def test_r1_002_tax_agent_cannot_register_the_liable_person() -> None:
    """R1-002 / CLAUDE.md rule 14: an agent never registers the liable person."""
    perms = permissions_for(["tax_agent"])
    assert not perms & TAX_AGENT_FORBIDDEN
    assert "registration:submit_as_liable_person" not in perms
    assert "tenant:members_manage" not in perms


def test_client_admin_can_register_the_liable_person() -> None:
    assert "registration:submit_as_liable_person" in permissions_for(["client_admin"])


def test_only_client_admin_can_submit_as_liable_person() -> None:
    holders = {r for r in ROLES if "registration:submit_as_liable_person" in ROLE_PERMISSIONS[r]}
    assert holders == {"client_admin"}


def test_platform_admin_has_no_business_data_permissions() -> None:
    perms = permissions_for(["platform_admin"])
    assert all(p.startswith("platform:") for p in perms)


def test_supplier_has_no_operations_api_permissions() -> None:
    assert permissions_for(["supplier"]) == frozenset()


def test_only_the_domain_owner_activates_reference_data() -> None:
    holders = {r for r in ROLES if "refdata:activate" in ROLE_PERMISSIONS[r]}
    assert holders == {"domain_owner"}


def test_only_approvers_decide_approvals_and_they_cannot_import() -> None:
    assert {r for r in ROLES if "approvals:decide" in ROLE_PERMISSIONS[r]} == {"approver"}
    assert "imports:write" not in permissions_for(["approver"])


def test_reviewer_cannot_approve_or_activate() -> None:
    perms = permissions_for(["reviewer"])
    assert "approvals:decide" not in perms
    assert "refdata:activate" not in perms


def test_permission_names_are_area_action() -> None:
    assert all(p.count(":") == 1 and p == p.lower() for p in ALL_PERMISSIONS)


def test_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown role"):
        permissions_for(["superuser"])


def test_union_of_roles() -> None:
    both = permissions_for(["reviewer", "client_admin"])
    assert both >= permissions_for(["reviewer"]) | permissions_for(["client_admin"])


def test_mfa_roles_follow_the_prd() -> None:
    """PRD R1-042 (confirmed 3 Oct 2026): mandatory for five roles."""
    assert MFA_REQUIRED_ROLES == {
        "platform_admin", "operations", "reviewer", "approver", "domain_owner"
    }  # fmt: skip
    assert mfa_required(["operations"])
    assert mfa_required(["client_admin", "approver"])
    assert not mfa_required(["client_admin"])
    assert not mfa_required(["tax_agent", "supplier"])


def test_platform_admin_is_not_assignable_by_tenants() -> None:
    assert "platform_admin" not in TENANT_ASSIGNABLE_ROLES
    assert set(TENANT_ASSIGNABLE_ROLES) == set(ROLES) - {"platform_admin"}
