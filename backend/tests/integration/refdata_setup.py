"""Shared setup for integration tests that need ACTIVE reference data (fixture datasets only).

Reference data is global and the test database persists, so a test that needs it resets the
reference tables first. Batches point at the layout version they used (a foreign key), so the
import tables are cleared before the reference tables.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, text

from app.core.db import tenant_session
from app.modules.refdata import service
from app.modules.refdata.datasets import DATASETS
from app.modules.refdata.load import load_dataset
from app.modules.refdata.service import Actor
from tests.integration.conftest import make_user

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
IMPORT_TABLES = [
    "import_line_sources",
    "import_lines",
    "declarations",
    "parties",
    "row_exceptions",
    "source_rows",
    "import_batches",
]
REF_TABLES = [
    *(f"ref_{name}" for name in DATASETS),
    "ref_dataset_versions",
    "ref_datasets",
    "regulatory_sources",
    "platform_domain_owners",
]


def reset_refdata(admin_engine: Engine) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("set local role cbam_owner"))
        for table in [*IMPORT_TABLES, *REF_TABLES]:
            conn.execute(text(f"alter table cbam.{table} disable trigger user"))
            conn.execute(text(f"alter table cbam.{table} no force row level security"))
            conn.execute(text(f"delete from cbam.{table}"))  # noqa: S608
            conn.execute(text(f"alter table cbam.{table} force row level security"))
            conn.execute(text(f"alter table cbam.{table} enable trigger user"))


def platform(engine: Engine, user: UUID | None = None):  # type: ignore[no-untyped-def]
    return tenant_session(engine, tenant_id=None, user_id=user, platform=True)


def make_owner(app_engine: Engine, admin_engine: Engine) -> UUID:
    uid = make_user(app_engine)
    with tenant_session(admin_engine, tenant_id=None, platform=True) as s:
        s.execute(text("set local role cbam_owner"))
        s.execute(text("insert into cbam.platform_domain_owners (user_id) values (:u)"), {"u": uid})
    return uid


def load(engine: Engine, folder: Path) -> None:
    with platform(engine) as s:
        load_dataset(s, folder, now=NOW, app_env="local")


def put_source_in_force(engine: Engine, owner: UUID, source_id: str) -> None:
    with platform(engine, owner) as s:
        current = service.get_source(s, source_id)
        service.set_source_status(
            s,
            Actor(owner),
            NOW,
            source_id,
            expected_version=current["row_version"],
            status="in_force",
            reason="Primary text read",
            commencement_date=date(2027, 1, 1),
        )


def activate(engine: Engine, owner: UUID, dataset: str, version: str) -> None:
    with platform(engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, dataset, version)
    with platform(engine, owner) as s:
        current = service.get_version(s, dataset, version)
        service.activate_version(
            s,
            Actor(owner),
            NOW,
            dataset,
            version,
            expected_version=current["row_version"],
            app_env="local",
            reason="Reviewed the impact report",
            acknowledge_warnings=True,
        )
