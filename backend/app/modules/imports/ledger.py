"""Read side of the import ledger: lines, declarations and their lineage (R1-005).

Every query filters by `tenant_id` as well as relying on row-level security (CLAUDE.md rule 7).
A line resolves to the raw row(s) it came from, the batch and the stored file's SHA-256. The raw
cell text is returned only through these routes, which require `imports:read`.
"""

import re
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.core.errors import InvalidRequestError, TenantMismatchError
from app.core.pagination import clamp_limit, decode_cursor, encode_cursor
from app.modules.imports import rules
from app.modules.imports.schemas import (
    DeclarationOut,
    ImportLineDetail,
    ImportLineOut,
    ImportLinePage,
    LineBatchOut,
    LineVersionOut,
    PartyOut,
    RowExceptionOut,
    SourceRowOut,
    StoredFileOut,
)

_CODE_PREFIX = re.compile(r"^[0-9]{1,10}$")
_ORIGIN = re.compile(r"^[A-Z]{2}$")

_LINE_SELECT = """
select l.id, l.declaration_id, d.mrn, d.acceptance_date, l.item_no, l.version, l.supersedes_id,
  not exists (select 1 from cbam.import_lines n
               where n.tenant_id = l.tenant_id and n.supersedes_id = l.id) as is_current,
  l.commodity_code, l.description, l.net_mass_kg, l.customs_value_source,
  l.customs_value_currency, l.customs_value_gbp, l.customs_value_gbp_note, l.valuation_basis,
  l.value_source, l.value_override_reason, l.country_of_origin_declared, l.cpc, l.batch_id,
  l.source_row_id, l.entry_method, l.change_reason, l.created_at,
  (select count(*) from cbam.import_line_sources s
     join cbam.row_exceptions e on e.tenant_id = s.tenant_id
      and e.source_row_id = s.source_row_id and e.status = 'open'
    where s.tenant_id = l.tenant_id and s.import_line_id = l.id) as open_exceptions
from cbam.import_lines l
join cbam.declarations d on d.tenant_id = l.tenant_id and d.id = l.declaration_id
"""


def _line_out(row: Row[Any]) -> ImportLineOut:
    return ImportLineOut(**dict(row._mapping))


def list_lines(
    session: Session,
    tenant_id: UUID,
    *,
    commodity_code: str | None = None,
    origin: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    batch_id: UUID | None = None,
    entry_method: str | None = None,
    has_open_exceptions: bool | None = None,
    include_superseded: bool = False,
    limit: int | None = None,
    cursor: str | None = None,
) -> ImportLinePage:
    """Newest first, keyset-paginated by id. Current versions only unless asked otherwise."""
    if commodity_code is not None and not _CODE_PREFIX.match(commodity_code):
        raise InvalidRequestError("commodity_code must be 1 to 10 digits")
    if origin is not None and not _ORIGIN.match(origin):
        raise InvalidRequestError("origin must be a 2-letter code in capitals")
    page = clamp_limit(limit)
    where = ["l.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": tenant_id, "n": page + 1}
    if commodity_code is not None:
        where.append("left(l.commodity_code, length(:code)) = :code")
        params["code"] = commodity_code
    if origin is not None:
        where.append("l.country_of_origin_declared = :origin")
        params["origin"] = origin
    if date_from is not None:
        where.append("d.acceptance_date >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where.append("d.acceptance_date <= :date_to")
        params["date_to"] = date_to
    if batch_id is not None:
        where.append("l.batch_id = :batch")
        params["batch"] = batch_id
    if entry_method is not None:
        where.append("l.entry_method = :entry")
        params["entry"] = entry_method
    if not include_superseded:
        where.append(
            "not exists (select 1 from cbam.import_lines n"
            " where n.tenant_id = l.tenant_id and n.supersedes_id = l.id)"
        )
    if has_open_exceptions is not None:
        test = (
            "exists (select 1 from cbam.import_line_sources s"
            " join cbam.row_exceptions e on e.tenant_id = s.tenant_id"
            " and e.source_row_id = s.source_row_id and e.status = 'open'"
            " where s.tenant_id = l.tenant_id and s.import_line_id = l.id)"
        )
        where.append(test if has_open_exceptions else f"not {test}")
    if cursor:
        try:
            params["after"] = UUID(str(decode_cursor(cursor)["i"]))
        except (KeyError, ValueError) as exc:
            raise InvalidRequestError("The cursor is not valid") from exc
        where.append("l.id < :after")
    sql = f"{_LINE_SELECT} where {' and '.join(where)} order by l.id desc limit :n"
    rows = session.execute(text(sql), params).all()  # fragments above are fixed; values bound
    items = rows[:page]
    next_cursor = encode_cursor({"i": str(items[-1].id)}) if len(rows) > page else None
    return ImportLinePage(items=[_line_out(r) for r in items], next_cursor=next_cursor)


def _party(session: Session, tenant_id: UUID, party_id: UUID | None) -> PartyOut | None:
    if party_id is None:
        return None
    row = session.execute(
        text("select id, eori, name from cbam.parties where tenant_id = :t and id = :i"),
        {"t": tenant_id, "i": party_id},
    ).one_or_none()
    return None if row is None else PartyOut(id=row.id, eori=row.eori, name=row.name)


def get_declaration(session: Session, tenant_id: UUID, declaration_id: UUID) -> DeclarationOut:
    row = session.execute(
        text(
            "select d.*, not exists (select 1 from cbam.declarations n"
            " where n.tenant_id = d.tenant_id and n.supersedes_id = d.id) as is_current"
            " from cbam.declarations d where d.tenant_id = :t and d.id = :i"
        ),
        {"t": tenant_id, "i": declaration_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return DeclarationOut(
        id=row.id,
        mrn=row.mrn,
        version=row.version,
        supersedes_id=row.supersedes_id,
        is_current=row.is_current,
        acceptance_date=row.acceptance_date,
        acceptance_at=row.acceptance_at,
        procedure_code=row.procedure_code,
        additional_procedure_codes=row.additional_procedure_codes,
        importer=_party(session, tenant_id, row.importer_party_id),
        declarant=_party(session, tenant_id, row.declarant_party_id),
        representative=_party(session, tenant_id, row.representative_party_id),
        representation_type=row.representation_type,
        eori_context=row.eori_context,
        entry_method=row.entry_method,
        batch_id=row.batch_id,
        created_at=row.created_at,
    )


def get_line(session: Session, tenant_id: UUID, line_id: UUID) -> ImportLineDetail:
    """The line with its declaration, parties, every source row (raw), the batch, the stored
    file's details (not a download), the version chain and the open exceptions of its rows."""
    row = session.execute(
        text(f"{_LINE_SELECT} where l.tenant_id = :t and l.id = :i"),
        {"t": tenant_id, "i": line_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    line = _line_out(row)
    sources = session.execute(
        text(
            "select s.source_row_id, s.role, s.report_type, sr.batch_id, sr.row_number, sr.raw,"
            " sr.row_sha256 from cbam.import_line_sources s"
            " join cbam.source_rows sr on sr.tenant_id = s.tenant_id and sr.id = s.source_row_id"
            " where s.tenant_id = :t and s.import_line_id = :i order by sr.row_number, s.role"
        ),
        {"t": tenant_id, "i": line_id},
    ).all()
    batch = session.execute(
        text(
            "select b.id, b.status, b.acquisition_method, b.cds_report_type, b.eori, b.acquired_on,"
            " b.window_start, b.window_end, v.id as version_id, v.original_filename, v.sha256,"
            " v.size_bytes from cbam.import_batches b"
            " left join cbam.document_versions v on v.tenant_id = b.tenant_id"
            " and v.id = b.document_version_id where b.tenant_id = :t and b.id = :b"
        ),
        {"t": tenant_id, "b": line.batch_id},
    ).one_or_none()
    if batch is None:
        raise TenantMismatchError()
    versions = session.execute(
        text(
            "select l.id, l.version, l.supersedes_id, l.change_reason, l.batch_id, l.created_at,"
            " not exists (select 1 from cbam.import_lines n where n.tenant_id = l.tenant_id"
            "   and n.supersedes_id = l.id) as is_current"
            " from cbam.import_lines l join cbam.declarations d"
            "   on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
            " where l.tenant_id = :t and d.mrn = :mrn and l.item_no = :item order by l.version"
        ),
        {"t": tenant_id, "mrn": line.mrn, "item": line.item_no},
    ).all()
    exceptions = session.execute(
        text(
            "select distinct e.id, e.row_number, e.field, e.code, e.severity, e.message,"
            " e.status, e.row_version from cbam.row_exceptions e"
            " join cbam.import_line_sources s on s.tenant_id = e.tenant_id"
            "   and s.source_row_id = e.source_row_id"
            " where e.tenant_id = :t and s.import_line_id = :i and e.status = 'open'"
            " order by e.row_number, e.id"
        ),
        {"t": tenant_id, "i": line_id},
    ).all()
    return ImportLineDetail(
        line=line,
        declaration=get_declaration(session, tenant_id, line.declaration_id),
        sources=[SourceRowOut(**dict(r._mapping)) for r in sources],
        batch=LineBatchOut(
            id=batch.id,
            status=batch.status,
            acquisition_method=batch.acquisition_method,
            cds_report_type=batch.cds_report_type,
            eori_context=rules.parse_eori_context(batch.eori),
            acquired_on=batch.acquired_on,
            window_start=batch.window_start,
            window_end=batch.window_end,
        ),
        file=StoredFileOut(
            document_version_id=batch.version_id,
            filename=batch.original_filename,
            sha256=batch.sha256,
            size_bytes=batch.size_bytes,
        ),
        versions=[LineVersionOut(**dict(r._mapping)) for r in versions],
        open_exceptions=[RowExceptionOut(**dict(r._mapping)) for r in exceptions],
    )
