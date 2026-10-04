"""SQLAlchemy Core definitions mirroring migrations 0009 and 0010 (the migrations are the source
of truth)."""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="cbam")

documents = Table(
    "documents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("created_by", Uuid),
)

document_versions = Table(
    "document_versions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("document_id", Uuid, nullable=False),
    Column("version", Integer, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("mime_detected", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("uploaded_by_type", Text, nullable=False),
    Column("uploaded_by_id", Uuid),
    Column("scan_state", Text, nullable=False),
    Column("uploaded_at", DateTime(timezone=True)),
)

import_batches = Table(
    "import_batches",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("file_sha256", Text),
    Column("document_version_id", Uuid),
    Column("filename", Text),
    Column("acquisition_method", Text, nullable=False),
    Column("cds_report_type", Text),
    Column("eori", Text),
    Column("window_start", Date),
    Column("window_end", Date),
    Column("source_owner", Text),
    Column("acquired_on", Date),
    Column("idempotency_key", Text),
    Column("request_fingerprint", LargeBinary, nullable=False),
    Column("status", Text, nullable=False),
    Column("rows_total", Integer, nullable=False),
    Column("rows_processed", Integer, nullable=False),
    Column("rows_valid", Integer, nullable=False),
    Column("rows_rejected", Integer, nullable=False),
    Column("lines_created", Integer, nullable=False),
    Column("lines_unchanged", Integer, nullable=False),
    Column("failure_reason", Text),
    Column("report_layout_version_id", Uuid),
    Column("layout_status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("created_by", Uuid),
    Column("updated_at", DateTime(timezone=True)),
    Column("row_version", Integer, nullable=False),
)

source_rows = Table(
    "source_rows",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("batch_id", Uuid, nullable=False),
    Column("row_number", Integer, nullable=False),
    Column("raw", JSONB, nullable=False),
    Column("row_sha256", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

row_exceptions = Table(
    "row_exceptions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("batch_id", Uuid, nullable=False),
    Column("source_row_id", Uuid),
    Column("row_number", Integer, nullable=False),
    Column("field", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("resolved_by", Uuid),
    Column("resolved_at", DateTime(timezone=True)),
    Column("resolution_reason", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("row_version", Integer, nullable=False),
)
