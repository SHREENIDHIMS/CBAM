"""SQLAlchemy Core definitions mirroring migration 0006 (the migration is the source of truth)."""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)

metadata = MetaData(schema="cbam")

tasks = Table(
    "tasks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("type", Text, nullable=False),
    Column("subject_type", Text),
    Column("subject_id", Uuid),
    Column("title", Text, nullable=False),
    Column("due_date", Date),
    Column("due_rule", Text),
    Column("owner_id", Uuid),
    Column("status", Text, nullable=False),
    Column("escalation_level", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("created_by", Uuid),
    Column("updated_at", DateTime(timezone=True)),
    Column("row_version", Integer, nullable=False),
)

task_events = Table(
    "task_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("task_id", Uuid, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("from_value", Text),
    Column("to_value", Text),
    Column("reason", Text),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", Uuid),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
