"""Register a domain owner (the person who approves reference data). Run by an operator.

    MIGRATIONS_DATABASE_URL=... uv run python -m app.cli.bootstrap_domain_owner \\
        --user-id <Supabase auth user id> --email <their email>

The person must already exist in Supabase Auth. Nobody can grant this role through the app: a
client admin can hand out the tenant role `domain_owner` in their own client, so this platform-level
grant is deliberately a database operation (ADR-0003). It is written to the platform audit chain.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.core.audit import record
from app.core.db import make_engine, tenant_session
from app.modules.platform_admin import rules


def bootstrap(engine: Engine, *, user_id: UUID, email: str, now: datetime) -> bool:
    """Returns True if a new domain owner was registered, False if they already were one."""
    clean_email = rules.clean_email(email)
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        s.execute(text("set local role cbam_owner"))
        s.execute(
            text("insert into cbam.users (id, email) values (:i, :e) on conflict (id) do nothing"),
            {"i": user_id, "e": clean_email},
        )
        inserted = s.execute(
            text(
                "insert into cbam.platform_domain_owners (user_id) values (:i)"
                " on conflict (user_id) do nothing returning user_id"
            ),
            {"i": user_id},
        ).first()
        if inserted is not None:
            record(
                s,
                tenant_id=None,
                actor_type="system",
                actor_id=None,
                action="domain_owner.registered",
                object_type="user",
                object_id=user_id,
                occurred_at=now,
                reason="domain owner registered from the command line",
            )
        return inserted is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register a domain owner")
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not url:
        print("MIGRATIONS_DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        created = bootstrap(
            make_engine(url), user_id=args.user_id, email=args.email, now=datetime.now(UTC)
        )
    except ValueError as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        return 2
    except IntegrityError:
        print("that email already belongs to a different user id", file=sys.stderr)
        return 1
    print("domain owner registered" if created else "already a domain owner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
