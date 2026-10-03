"""Roles and permissions (R1-002). A starting least-privilege matrix; each phase adds its own.

Permission names are `<area>:<action>`. This is product access control, not law, so it lives in
code and is covered by a matrix test. Hard rules (tested):
- a tax agent can never register the liable person (CLAUDE.md rule 14);
- platform admins get no business-data permissions (they manage tenants and users only);
- a supplier has no ops-API permissions at all (suppliers use magic links, not accounts).
"""

from collections.abc import Iterable, Mapping

ROLES: tuple[str, ...] = (
    "platform_admin",
    "operations",
    "client_admin",
    "reviewer",
    "approver",
    "supplier",
    "tax_agent",
    "domain_owner",
)

# Roles a tenant admin may hand out. platform_admin is never a tenant role.
TENANT_ASSIGNABLE_ROLES: tuple[str, ...] = tuple(r for r in ROLES if r != "platform_admin")

# R1-042: TOTP is mandatory for these roles (the token must be aal2).
MFA_REQUIRED_ROLES: frozenset[str] = frozenset(
    {"platform_admin", "operations", "reviewer", "approver", "domain_owner"}
)

_READ_CORE = {"tenant:read", "tasks:read", "imports:read", "suppliers:read", "documents:read"}

ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    "platform_admin": frozenset(
        {"platform:tenants_manage", "platform:users_manage", "platform:audit_read"}
    ),
    "operations": frozenset(
        _READ_CORE
        | {
            "tasks:write",
            "imports:write",
            "suppliers:write",
            "documents:write",
            "outreach:send",
            "review:read",
            "review:resolve",
            "registration:read",
            "registration:prepare",
            "exports:read",
        }
    ),
    "client_admin": frozenset(
        _READ_CORE
        | {
            "tenant:members_manage",
            "tasks:write",
            "imports:write",
            "suppliers:write",
            "documents:write",
            "registration:read",
            "registration:prepare",
            "registration:submit_as_liable_person",
            "exports:read",
        }
    ),
    "reviewer": frozenset(_READ_CORE | {"review:read", "review:resolve", "tasks:write"}),
    "approver": frozenset(_READ_CORE | {"review:read", "registration:read", "approvals:decide"}),
    "supplier": frozenset(),
    "tax_agent": frozenset(_READ_CORE | {"registration:read", "exports:read"}),
    "domain_owner": frozenset(
        {"tenant:read", "tasks:read", "tasks:write", "review:read", "review:resolve"}
        | {"refdata:read", "refdata:activate", "audit:read"}
    ),
}

# Never available to a tax agent acting as a tax agent, whatever the matrix says.
TAX_AGENT_FORBIDDEN: frozenset[str] = frozenset(
    {"registration:submit_as_liable_person", "tenant:members_manage", "refdata:activate"}
)

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    """Union of the permissions of a user's roles. Unknown roles are an error, not ignored."""
    granted: set[str] = set()
    for role in roles:
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"unknown role {role!r}")
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def mfa_required(roles: Iterable[str]) -> bool:
    return any(role in MFA_REQUIRED_ROLES for role in roles)
