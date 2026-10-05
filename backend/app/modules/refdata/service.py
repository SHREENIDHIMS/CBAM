"""Reference-data service: lookups by legal date, impact reports and activation (R1-050).

Reads go only through the `v_active_*` views, so a row of a pending or retired version, or of a
source that is not in force on the date, can never be returned (CLAUDE.md rules 1 and 2).
Activation needs a dry-run impact report and a domain owner; the database enforces the same
two things with a trigger (migration 0007), so a hidden button is never the only guard.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.errors import (
    InvalidRequestError,
    NotPermittedError,
    ReasonRequiredError,
    RuleBlockedError,
    StaleVersionError,
    TenantMismatchError,
)
from app.core.money import dumps
from app.core.versioning import update_versioned
from app.modules.refdata import rules
from app.modules.refdata.datasets import DatasetSpec, dataset_spec

_MAX_REPORTED_CHANGES = 500
_MAX_REPORTED_AFFECTED = 500


@dataclass(frozen=True)
class Actor:
    user_id: UUID


@dataclass(frozen=True)
class Snapshot:
    """The reference rows usable on one legal date, plus the versions they came from.

    Pass `rows` into a `rules.py` function and store `version_ids` on the decision so a
    historical replay uses the same data (CLAUDE.md rule 4).
    """

    on: date
    version_ids: tuple[UUID, ...]
    rows: Mapping[str, tuple[dict[str, Any], ...]]


def _spec(dataset: str) -> DatasetSpec:
    try:
        return dataset_spec(dataset)
    except KeyError as exc:
        raise InvalidRequestError(str(exc)) from exc


_USABLE = "usable_from <= :on and (usable_to is null or :on < usable_to)"


def _clean(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("id", "usable_from", "usable_to")}


def get(
    session: Session, dataset: str, key: Mapping[str, Any], *, on: date
) -> dict[str, Any] | None:
    """The one usable row for `key` on legal date `on`, or None. Never "latest"."""
    spec = _spec(dataset)
    if set(key) != set(spec.key):
        raise InvalidRequestError(f"{dataset} is looked up by {list(spec.key)}")
    conditions = "".join(f" and {k} = :k_{k}" for k in spec.key)
    sql = f"select * from cbam.{spec.view} where {_USABLE}{conditions}"  # noqa: S608
    params = {"on": on, **{f"k_{k}": v for k, v in key.items()}}
    rows = session.execute(text(sql), params).mappings().all()
    if len(rows) > 1:  # the exclusion constraint makes this impossible; fail loudly if not
        raise RuleBlockedError(f"{dataset} has more than one usable row for {dict(key)}")
    return _clean(dict(rows[0])) if rows else None


def get_by_prefix(session: Session, dataset: str, value: str, *, on: date) -> dict[str, Any] | None:
    """The usable row whose listed prefix is the longest prefix of `value` (a commodity
    code, digits only). HMRC lists headings and sub-headings and covers everything below them.

    A code that is too short to decide is refused, never guessed: if a listed row below `value`
    would give a different answer (for example `7202` when `7202 21` is excepted from `72`), the
    caller must pass the full commodity code.
    """
    spec = _spec(dataset)
    if spec.prefix_column is None:
        raise InvalidRequestError(f"{dataset} has no prefix lookup")
    if not value.isdigit():
        raise InvalidRequestError("a prefix lookup needs digits only")
    column = spec.prefix_column
    sql = (
        f"select * from cbam.{spec.view} where {_USABLE}"  # noqa: S608
        f" and :value like {column} || '%'"
        f" order by length({column}) desc limit 1"
    )
    row = session.execute(text(sql), {"on": on, "value": value}).mappings().first()
    below_sql = (
        f"select 1 from cbam.{spec.view} where {_USABLE}"  # noqa: S608
        f" and {column} like :value || '%' and {column} <> :value"
        " and in_scope is distinct from :scope limit 1"
    )
    scope = None if row is None else row["in_scope"]
    differs = session.execute(
        text(below_sql), {"on": on, "value": value, "scope": scope}
    ).scalar_one_or_none()
    if differs is not None:
        raise RuleBlockedError(
            f"Commodity code {value} is too short to decide: listed codes below it differ"
        )
    return _clean(dict(row)) if row else None


def snapshot(session: Session, datasets: Sequence[str], *, on: date) -> Snapshot:
    """Every usable row of the named datasets on `on`, with the version ids they came from."""
    rows: dict[str, tuple[dict[str, Any], ...]] = {}
    version_ids: dict[UUID, None] = {}
    for name in datasets:
        spec = _spec(name)
        sql = f"select * from cbam.{spec.view} where {_USABLE} order by id"  # noqa: S608
        found = [dict(r) for r in session.execute(text(sql), {"on": on}).mappings().all()]
        for row in found:
            version_ids[row["dataset_version_id"]] = None
        rows[name] = tuple(_clean(r) for r in found)
    return Snapshot(on=on, version_ids=tuple(version_ids), rows=rows)


def rows_of_version(session: Session, dataset: str, version_id: UUID) -> list[dict[str, Any]]:
    """All rows of one stored version (any status), for impact reports and replay."""
    spec = _spec(dataset)
    sql = (
        f"select * from cbam.{spec.table} where dataset_version_id = :v"  # noqa: S608
        " order by effective_from, id"
    )
    return [dict(r) for r in session.execute(text(sql), {"v": version_id}).mappings().all()]


# --- registry reads ---------------------------------------------------------------------

_SOURCE_COLS = (
    "id, source_id, title, source_type, url, publication_date, status, commencement_date,"
    " effective_from, effective_to, retrieved_at, notes, row_version"
)


def list_sources(session: Session) -> list[dict[str, Any]]:
    sql = f"select {_SOURCE_COLS} from cbam.regulatory_sources order by source_id"  # noqa: S608
    return [dict(r) for r in session.execute(text(sql)).mappings().all()]


def get_source(session: Session, source_id: str) -> dict[str, Any]:
    sql = f"select {_SOURCE_COLS} from cbam.regulatory_sources where source_id = :s"  # noqa: S608
    row = session.execute(text(sql), {"s": source_id}).mappings().first()
    if row is None:
        raise TenantMismatchError()
    return dict(row)


def list_datasets(session: Session) -> list[dict[str, Any]]:
    sql = (
        "select d.id, d.name,"
        " (select v.version from cbam.ref_dataset_versions v"
        "   where v.dataset_id = d.id and v.status = 'active') as active_version,"
        " (select count(*) from cbam.ref_dataset_versions v"
        "   where v.dataset_id = d.id and v.status = 'pending') as pending_versions"
        " from cbam.ref_datasets d order by d.name"
    )
    return [dict(r) for r in session.execute(text(sql)).mappings().all()]


_VERSION_COLS = (
    "v.id, v.dataset_id, d.name as dataset, v.version, s.source_id as source_ref,"
    " s.status as source_status, v.checksum_sha256, v.effective_from, v.effective_to,"
    " v.is_fixture, v.row_count, v.status, v.loaded_at, v.activated_by, v.activated_at,"
    " v.retired_at, v.impact_report is not null as has_impact_report, v.row_version, v.notes"
)
_VERSION_FROM = (
    " from cbam.ref_dataset_versions v join cbam.ref_datasets d on d.id = v.dataset_id"
    " join cbam.regulatory_sources s on s.id = v.source_id"
)


def list_versions(session: Session, dataset: str) -> list[dict[str, Any]]:
    sql = (
        f"select {_VERSION_COLS}{_VERSION_FROM}"
        " where d.name = :n order by v.loaded_at desc, v.version desc"
    )
    return [dict(r) for r in session.execute(text(sql), {"n": dataset}).mappings().all()]


def get_version(session: Session, dataset: str, version: str) -> dict[str, Any]:
    sql = (
        f"select {_VERSION_COLS}, v.impact_report{_VERSION_FROM}"
        " where d.name = :n and v.version = :v"
    )
    row = session.execute(text(sql), {"n": dataset, "v": version}).mappings().first()
    if row is None:
        raise TenantMismatchError()
    return dict(row)


# --- source registry changes ------------------------------------------------------------


def _require_domain_owner(session: Session, actor: Actor) -> None:
    owner = session.execute(
        text("select 1 from cbam.platform_domain_owners where user_id = :u"), {"u": actor.user_id}
    ).scalar_one_or_none()
    if owner is None:
        raise NotPermittedError("Only a domain owner can do this")


def set_source_status(
    session: Session,
    actor: Actor,
    now: datetime,
    source_id: str,
    *,
    expected_version: int,
    status: str,
    reason: str | None,
    commencement_date: date | None = None,
    effective_to: date | None = None,
) -> dict[str, Any]:
    """A domain owner moves a source forward (for example laid -> in_force) with a reason."""
    _require_domain_owner(session, actor)
    current = get_source(session, source_id)
    if current["row_version"] != expected_version:
        raise StaleVersionError("This source changed since you loaded it; reload and try again")
    decision = rules.source_status_decision(current["status"], status, reason=reason)
    if decision.outcome == "BLOCKED":
        raise RuleBlockedError(decision.reason, rule_id=decision.rule_id)
    if decision.outcome == "REASON_REQUIRED":
        raise ReasonRequiredError(decision.reason, rule_id=decision.rule_id)
    values: dict[str, Any] = {"status": status}
    if status == "superseded":
        if effective_to is None:
            raise InvalidRequestError("Say the date the source stopped applying (effective_to)")
        values["effective_to"] = effective_to
    if commencement_date is not None:
        values["commencement_date"] = commencement_date
    update_versioned(
        session,
        "regulatory_sources",
        row_id=current["id"],
        expected_version=expected_version,
        values=values,
    )
    record(
        session,
        tenant_id=None,
        actor_type="user",
        actor_id=actor.user_id,
        action="refdata.source_status_changed",
        object_type="regulatory_source",
        object_id=current["id"],
        occurred_at=now,
        before={
            "status": current["status"],
            "commencement_date": _jsonable(current["commencement_date"]),
            "effective_to": _jsonable(current["effective_to"]),
        },
        after={
            "status": status,
            "commencement_date": _jsonable(commencement_date or current["commencement_date"]),
            "effective_to": _jsonable(effective_to or current["effective_to"]),
        },
        reason=reason,
    )
    return get_source(session, source_id)


# --- impact report ----------------------------------------------------------------------


@dataclass(frozen=True)
class AffectedItem:
    """One downstream record whose outcome could change, named by id (never personal data)."""

    kind: str
    ref: str
    detail: str
    # Optional structure for providers that count per client: `group` names what was counted (a
    # code prefix) and `count` how many. Lets a caller without `refdata:activate` see totals only.
    group: str = ""
    count: int = 0


# A provider answers "which records would change outcome?" for one dataset. Phase 3 registers
# the import-line provider. It must not read across tenants: it returns counts per tenant or
# ids the platform may see, never business content (CLAUDE.md rule 7).
ImpactProvider = Callable[[Session, rules.VersionDiff], Sequence[AffectedItem]]
_PROVIDERS: dict[str, ImpactProvider] = {}


def register_impact_provider(dataset: str, provider: ImpactProvider) -> None:
    _spec(dataset)
    _PROVIDERS[dataset] = provider


def clear_impact_providers() -> None:
    """For tests."""
    _PROVIDERS.clear()


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _json_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else {k: _jsonable(v) for k, v in row.items()}


def _active_version(session: Session, dataset: str) -> Any:
    return session.execute(
        text(
            "select v.id, v.version from cbam.ref_dataset_versions v"
            " join cbam.ref_datasets d on d.id = v.dataset_id"
            " where d.name = :n and v.status = 'active'"
        ),
        {"n": dataset},
    ).one_or_none()


def redact_impact_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report as a caller WITHOUT `refdata:activate` may see it: per-client items (which name
    a client by id) become totals per group: how many clients and lines, never which."""
    if report is None:
        return None
    affected = report.get("affected") or {}
    items = affected.get("items") or []
    totals: dict[tuple[str, str], list[int]] = {}
    kept: list[dict[str, Any]] = []
    for item in items:
        if item.get("group"):
            t = totals.setdefault((item["kind"], item["group"]), [0, 0])
            t[0] += 1
            t[1] += int(item["count"])
        else:
            kept.append(item)
    kept.extend(
        {
            "kind": kind,
            "ref": group,
            "detail": f"{lines} current record(s) across {clients} client(s) under {group}",
            "group": group,
            "count": lines,
        }
        for (kind, group), (clients, lines) in sorted(totals.items())
    )
    return {**report, "affected": {**affected, "count": len(kept), "items": kept}}


def build_impact_report(
    session: Session, actor: Actor, now: datetime, dataset: str, version: str
) -> dict[str, Any]:
    """Dry run: what activating this pending version would change. Stored on the version."""
    spec = _spec(dataset)
    target = get_version(session, dataset, version)
    if target["status"] != "pending":
        raise RuleBlockedError(
            f"Only a pending version has an impact report; this is {target['status']}"
        )
    active = _active_version(session, dataset)
    old_rows = rows_of_version(session, dataset, active.id) if active else []
    new_rows = rows_of_version(session, dataset, target["id"])
    diff = rules.diff_versions(old_rows, new_rows, key=spec.key, columns=spec.column_names)
    source = get_source(session, target["source_ref"])
    usable = rules.source_usable(
        source_id=source["source_id"],
        status=source["status"],
        commencement_date=source["commencement_date"],
        effective_from=source["effective_from"],
        effective_to=source["effective_to"],
        on=target["effective_from"],
    )
    provider = _PROVIDERS.get(dataset)
    affected = list(provider(session, diff)) if provider else []
    warnings: list[str] = []
    if usable.outcome != "ACTIVE":
        warnings.append(
            f"Source {source['source_id']} would not allow this data to drive decisions yet: "
            f"{usable.reason}"
        )
    if target["is_fixture"]:
        warnings.append("This is a fixture dataset (test data), not law")
    if diff.coverage_gaps:
        warnings.append(
            "The new version does not cover some periods the active version covers; "
            "decisions for those dates would find no data"
        )
    if provider is None:
        warnings.append("No downstream impact provider is registered for this dataset yet")
    report: dict[str, Any] = {
        "dataset": dataset,
        "version": version,
        "version_id": str(target["id"]),
        "checksum_sha256": target["checksum_sha256"],
        "compared_to": None
        if active is None
        else {"id": str(active.id), "version": active.version},
        "generated_at": now.isoformat(),
        "rows": {
            "added": diff.count("added"),
            "removed": diff.count("removed"),
            "changed": diff.count("changed"),
            "unchanged": diff.unchanged,
        },
        "changes": [
            {
                "change": c.change,
                "key": {k: _jsonable(v) for k, v in c.key.items()},
                "effective_from": c.effective_from.isoformat(),
                "before": _json_row(c.before),
                "after": _json_row(c.after),
            }
            for c in diff.changes[:_MAX_REPORTED_CHANGES]
        ],
        "changes_truncated": len(diff.changes) > _MAX_REPORTED_CHANGES,
        "coverage_gaps": [
            {
                "key": {k: _jsonable(v) for k, v in g.key.items()},
                "from": g.start.isoformat(),
                "to": None if g.end is None else g.end.isoformat(),
            }
            for g in diff.coverage_gaps
        ],
        "source": {
            "source_id": source["source_id"],
            "status": source["status"],
            "outcome": usable.outcome,
            "reason": usable.reason,
        },
        "affected": {
            "provider_registered": provider is not None,
            "count": len(affected),
            "items": [
                {"kind": a.kind, "ref": a.ref, "detail": a.detail}
                | ({"group": a.group, "count": a.count} if a.group else {})
                for a in affected[:_MAX_REPORTED_AFFECTED]
            ],
            "truncated": len(affected) > _MAX_REPORTED_AFFECTED,
        },
        "warnings": warnings,
    }
    session.execute(
        text(
            "update cbam.ref_dataset_versions set impact_report = cast(:r as jsonb),"
            " row_version = row_version + 1, updated_at = now() where id = :i"
        ),
        {"r": dumps(report), "i": target["id"]},
    )
    record(
        session,
        tenant_id=None,
        actor_type="user",
        actor_id=actor.user_id,
        action="refdata.impact_report_generated",
        object_type="ref_dataset_version",
        object_id=target["id"],
        occurred_at=now,
        after={"dataset": dataset, "version": version, "rows": report["rows"]},
    )
    return report


# --- activation -------------------------------------------------------------------------


def activate_version(
    session: Session,
    actor: Actor,
    now: datetime,
    dataset: str,
    version: str,
    *,
    expected_version: int,
    app_env: str,
    reason: str,
    acknowledge_warnings: bool = False,
) -> dict[str, Any]:
    """A domain owner activates a pending version; the previous active one is retired.

    Needs a current dry-run impact report (compared with the version active right now), so
    nobody activates data blind. Nothing is deleted: the retired version stays for replay.
    """
    _spec(dataset)
    _require_domain_owner(session, actor)
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"refdata:{dataset}"}
    )
    target = get_version(session, dataset, version)
    if target["row_version"] != expected_version:
        raise StaleVersionError("This version changed since you loaded it; reload and try again")
    if target["status"] != "pending":
        raise RuleBlockedError(
            f"Only a pending version can be activated; this is {target['status']}"
        )
    if target["is_fixture"] and app_env == "production":
        raise RuleBlockedError("Fixture datasets cannot be activated in production")
    if not reason.strip():
        raise ReasonRequiredError("Say why this version is being activated")
    if target["row_count"] == 0:
        raise RuleBlockedError("An empty dataset version cannot be activated")
    report = target["impact_report"]
    active = _active_version(session, dataset)
    if report is None:
        raise RuleBlockedError("Generate the impact report before activating")
    compared = (report.get("compared_to") or {}).get("id")
    if compared != (str(active.id) if active else None):
        raise RuleBlockedError(
            "The active version changed after the impact report; generate it again"
        )
    if report.get("warnings") and not acknowledge_warnings:
        raise RuleBlockedError(
            "The impact report has warnings; read them and confirm to activate anyway"
        )
    update_versioned(
        session,
        "ref_dataset_versions",
        row_id=target["id"],
        expected_version=expected_version,
        values={"status": "active", "activated_by": actor.user_id, "activated_at": now},
    )
    record(
        session,
        tenant_id=None,
        actor_type="user",
        actor_id=actor.user_id,
        action="refdata.version_activated",
        object_type="ref_dataset_version",
        object_id=target["id"],
        occurred_at=now,
        before={"status": "pending"},
        after={"status": "active", "dataset": dataset, "version": version},
        reason=reason.strip(),
    )
    if active is not None:
        retired_row = session.execute(
            text("select row_version from cbam.ref_dataset_versions where id = :i"),
            {"i": active.id},
        ).scalar_one()
        update_versioned(
            session,
            "ref_dataset_versions",
            row_id=active.id,
            expected_version=retired_row,
            values={"status": "retired", "retired_at": now},
        )
        record(
            session,
            tenant_id=None,
            actor_type="user",
            actor_id=actor.user_id,
            action="refdata.version_retired",
            object_type="ref_dataset_version",
            object_id=active.id,
            occurred_at=now,
            before={"status": "active"},
            after={"status": "retired", "replaced_by": version},
        )
    return get_version(session, dataset, version)
