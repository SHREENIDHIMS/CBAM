"""Reference-data loader (R1-050): `uv run python -m app.modules.refdata.load <folder>`.

Reads `<folder>/manifest.yaml` and `<folder>/data.csv`, checks the checksum and the CSV shape,
and stores the data as a `pending` dataset version. Loading never activates anything.

- Idempotent: the same folder again changes nothing (no rows, no audit event).
- A changed file under an already loaded version is refused; new content is a new version.
- A file whose bytes do not match the manifest checksum is refused (tampering or a bad edit).
"""

import csv
import hashlib
import io
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.clock import Clock, SystemClock
from app.core.config import get_settings
from app.core.db import get_engine, tenant_session
from app.core.errors import InvalidRequestError, RuleBlockedError
from app.core.ids import uuid7
from app.modules.refdata import rules
from app.modules.refdata.datasets import Column, DatasetSpec, dataset_spec
from app.modules.refdata.manifest import Manifest, parse_manifest

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}
_MAX_REPORTED_ERRORS = 20


@dataclass(frozen=True)
class LoadResult:
    dataset: str
    version: str
    version_id: UUID
    status: str  # loaded | unchanged
    row_count: int


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_value(column: Column, raw: str) -> Any:
    value = raw.strip()
    if value == "":
        if column.optional:
            return None
        raise ValueError("a value is required")
    match column.kind:
        case "text":
            return value
        case "int":
            return int(value)
        case "bool":
            if value.lower() in _TRUE:
                return True
            if value.lower() in _FALSE:
                return False
            raise ValueError("expected true or false")
        case "date":
            return date.fromisoformat(value)
        case "decimal":
            try:
                return Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("not a decimal number") from exc
        case "json":
            return json.loads(value)
    raise AssertionError(column.kind)  # pragma: no cover


def parse_rows(spec: DatasetSpec, manifest: Manifest, raw: bytes) -> list[dict[str, Any]]:
    """Typed rows from data.csv. `effective_from`/`effective_to` columns are optional and
    default to the manifest's period. Every problem is reported with its row number."""
    try:
        text_data = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidRequestError("data.csv must be UTF-8 text") from exc
    reader = csv.DictReader(io.StringIO(text_data, newline=""))
    header = reader.fieldnames or []
    allowed = {*spec.column_names, "effective_from", "effective_to"}
    unknown = [h for h in header if h not in allowed]
    missing = [c.name for c in spec.columns if c.name not in header]
    if unknown or missing:
        raise InvalidRequestError(
            f"data.csv columns do not match dataset {spec.name}: "
            f"unknown {unknown or 'none'}, missing {missing or 'none'}"
        )
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, record_ in enumerate(reader, start=2):  # row 1 is the header
        if None in record_ or any(v is None for v in record_.values()):
            errors.append(f"row {number}: wrong number of cells")
            continue
        row_errors: list[str] = []
        parsed: dict[str, Any] = {}
        for column in spec.columns:
            try:
                parsed[column.name] = _parse_value(column, record_[column.name])
            except (ValueError, json.JSONDecodeError) as exc:
                row_errors.append(f"row {number}, {column.name}: {exc}")
        for name, default in (
            ("effective_from", manifest.effective_from),
            ("effective_to", manifest.effective_to),
        ):
            cell = (record_.get(name) or "").strip()
            try:
                parsed[name] = date.fromisoformat(cell) if cell else default
            except ValueError:
                row_errors.append(f"row {number}, {name}: not an ISO date")
        if not row_errors and parsed["effective_to"] is not None:
            if parsed["effective_to"] <= parsed["effective_from"]:
                row_errors.append(f"row {number}: effective_to must be after effective_from")
        errors.extend(row_errors)
        if not row_errors:
            rows.append(parsed)
    if not errors:
        for first, second in rules.find_overlaps(rows, spec.key):
            errors.append(
                f"rows {first + 2} and {second + 2}: same key with overlapping effective periods"
            )
    if errors:
        shown = errors[:_MAX_REPORTED_ERRORS]
        more = len(errors) - len(shown)
        suffix = f" (and {more} more)" if more else ""
        raise InvalidRequestError("data.csv has problems: " + "; ".join(shown) + suffix)
    return rows


def _lock(session: Session, dataset: str) -> None:
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"refdata:{dataset}"}
    )


def _retrieved_at(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _ensure_source(
    session: Session, manifest: Manifest, now: datetime, *, audit_actor: UUID | None
) -> UUID:
    existing = session.execute(
        text("select id from cbam.regulatory_sources where source_id = :s"),
        {"s": manifest.source_id},
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))  # the registry is the authority, not the manifest
    source_pk = uuid7()
    session.execute(
        text(
            "insert into cbam.regulatory_sources (id, source_id, title, source_type, url,"
            " publication_date, status, commencement_date, retrieved_at, notes, created_at)"
            " values (:id, :source_id, :title, :source_type, :url, :publication_date, :status,"
            " :commencement_date, :retrieved_at, :notes, :now)"
        ),
        {
            "id": source_pk,
            "source_id": manifest.source_id,
            "title": manifest.source_title,
            "source_type": manifest.source_type,
            "url": manifest.source_url,
            "publication_date": manifest.publication_date,
            "status": manifest.source_status,
            "commencement_date": manifest.commencement_date,
            "retrieved_at": _retrieved_at(manifest.retrieved_at),
            "notes": None,
            "now": now,
        },
    )
    record(
        session,
        tenant_id=None,
        actor_type="system",
        actor_id=audit_actor,
        action="refdata.source_registered",
        object_type="regulatory_source",
        object_id=source_pk,
        occurred_at=now,
        after={"source_id": manifest.source_id, "status": manifest.source_status},
    )
    return source_pk


_METADATA_COLUMNS = ("source_id", "effective_from", "effective_to", "is_fixture")


def load_dataset(
    session: Session,
    folder: Path,
    *,
    now: datetime,
    app_env: str,
    loaded_by: UUID | None = None,
) -> LoadResult:
    """Load one dataset folder as a pending version inside the caller's transaction."""
    manifest_path, data_path = folder / "manifest.yaml", folder / "data.csv"
    if not manifest_path.is_file() or not data_path.is_file():
        raise InvalidRequestError(f"{folder} needs manifest.yaml and data.csv")
    manifest = parse_manifest(manifest_path.read_bytes())
    raw = data_path.read_bytes()
    actual = sha256_hex(raw)
    if actual != manifest.checksum_sha256:
        raise InvalidRequestError(
            f"data.csv checksum {actual} does not match the manifest "
            f"({manifest.checksum_sha256}); the file changed after it was recorded"
        )
    if manifest.fixture and app_env == "production":
        raise RuleBlockedError("Fixture datasets cannot be loaded in production")
    try:
        spec = dataset_spec(manifest.dataset)
    except KeyError as exc:
        raise InvalidRequestError(str(exc)) from exc
    rows = parse_rows(spec, manifest, raw)
    _lock(session, spec.name)

    dataset_id = session.execute(
        text("select id from cbam.ref_datasets where name = :n"), {"n": spec.name}
    ).scalar_one_or_none()
    if dataset_id is None:
        dataset_id = uuid7()
        session.execute(
            text("insert into cbam.ref_datasets (id, name) values (:i, :n)"),
            {"i": dataset_id, "n": spec.name},
        )
    existing = session.execute(
        text(
            "select v.id, v.checksum_sha256, v.effective_from, v.effective_to, v.is_fixture,"
            " s.source_id from cbam.ref_dataset_versions v"
            " join cbam.regulatory_sources s on s.id = v.source_id"
            " where v.dataset_id = :d and v.version = :v"
        ),
        {"d": dataset_id, "v": manifest.version},
    ).one_or_none()
    if existing is not None:
        same = (
            existing.checksum_sha256 == actual
            and existing.source_id == manifest.source_id
            and existing.effective_from == manifest.effective_from
            and existing.effective_to == manifest.effective_to
            and existing.is_fixture == manifest.fixture
        )
        if not same:
            raise RuleBlockedError(
                f"{spec.name} version {manifest.version} is already loaded with different "
                "content; a changed file needs a new version folder"
            )
        return LoadResult(spec.name, manifest.version, existing.id, "unchanged", len(rows))

    source_pk = _ensure_source(session, manifest, now, audit_actor=loaded_by)
    version_id = uuid7()
    session.execute(
        text(
            "insert into cbam.ref_dataset_versions (id, dataset_id, version, source_id,"
            " checksum_sha256, effective_from, effective_to, is_fixture, row_count, status,"
            " loaded_at, loaded_by, notes)"
            " values (:id, :d, :v, :s, :c, :ef, :et, :fx, :n, 'pending', :at, :by, :notes)"
        ),
        {
            "id": version_id,
            "d": dataset_id,
            "v": manifest.version,
            "s": source_pk,
            "c": actual,
            "ef": manifest.effective_from,
            "et": manifest.effective_to,
            "fx": manifest.fixture,
            "n": len(rows),
            "at": now,
            "by": loaded_by,
            "notes": manifest.notes,
        },
    )
    _insert_rows(session, spec, version_id, rows)
    record(
        session,
        tenant_id=None,
        actor_type="system" if loaded_by is None else "user",
        actor_id=loaded_by,
        action="refdata.version_loaded",
        object_type="ref_dataset_version",
        object_id=version_id,
        occurred_at=now,
        after={
            "dataset": spec.name,
            "version": manifest.version,
            "checksum_sha256": actual,
            "rows": len(rows),
            "fixture": manifest.fixture,
        },
    )
    return LoadResult(spec.name, manifest.version, version_id, "loaded", len(rows))


def _insert_rows(
    session: Session, spec: DatasetSpec, version_id: UUID, rows: list[dict[str, Any]]
) -> None:
    columns = ["effective_from", "effective_to", *spec.column_names]
    values = ", ".join(
        f"cast(:{c.name} as jsonb)" if c.kind == "json" else f":{c.name}"
        for c in (Column("effective_from", "date"), Column("effective_to", "date"), *spec.columns)
    )
    sql = (  # identifiers come from the fixed dataset registry; values are bound
        f"insert into cbam.{spec.table} (id, dataset_version_id, {', '.join(columns)})"  # noqa: S608
        f" values (:id, :dataset_version_id, {values})"
    )
    params = []
    for row in rows:
        bound = {
            c.name: json.dumps(row[c.name])
            if c.kind == "json" and row[c.name] is not None
            else row[c.name]
            for c in spec.columns
        }
        params.append(
            {
                "id": uuid7(),
                "dataset_version_id": version_id,
                "effective_from": row["effective_from"],
                "effective_to": row["effective_to"],
                **bound,
            }
        )
    if params:
        session.execute(text(sql), params)


def load_folder(engine: Engine, folder: Path, *, clock: Clock, app_env: str) -> LoadResult:
    with tenant_session(engine, tenant_id=None, platform=True) as session:
        return load_dataset(session, folder, now=clock.now(), app_env=app_env)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m app.modules.refdata.load <dataset folder> [...]", file=sys.stderr)
        return 2
    settings = get_settings()
    engine = get_engine()
    for arg in args:
        try:
            result = load_folder(engine, Path(arg), clock=SystemClock(), app_env=settings.app_env)
        except (InvalidRequestError, RuleBlockedError) as exc:
            print(f"refused {arg}: {exc.detail}", file=sys.stderr)
            return 1
        print(
            f"{result.status}: {result.dataset} {result.version} ({result.row_count} rows, pending)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
