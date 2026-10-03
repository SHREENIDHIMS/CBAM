"""The first reference-data tables and their `v_active_*` views (R1-050).

Revision ID: 0008
Revises: 0007

Each table holds one dataset: `dataset_version_id`, `effective_from`, `effective_to` (exclusive)
and the business columns. Rows are inserted only into a pending version and never change
(trigger from 0007). No regulatory value is loaded here: the loader fills these tables from
`backend/refdata/` (docs/DATABASE.md section 6). The column lists are a starting shape; later
phases add columns as their requirements need them.

`v_active_<dataset>` is the one place the source activation rule lives (docs/DATABASE.md
section 5): version `active` AND source `in_force`/`commenced`, or `superseded` for the dates
before its `effective_to` (a superseded source always has one, so replays of earlier dates work). The date part is exposed as
`usable_from`/`usable_to` (row period narrowed by the source's commencement and effective
period), and services filter on the legal date.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# name -> (business columns DDL, exclusion key columns; empty = one row per period)
_DATASETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "cbam_commodity_codes": (
        """
        code_prefix text not null check (code_prefix ~ '^[0-9]{2,10}$'),
        listing_text text not null,
        sector text not null check (sector ~ '^[a-z][a-z_]*$'),
        description text not null,
        greenhouse_gases text,
        in_scope boolean not null,
        exclusion_within text check (exclusion_within ~ '^[0-9]{2,10}$')
        """,
        ("code_prefix",),
    ),
    "threshold_rules": (
        """
        threshold_gbp numeric(18,2) not null check (threshold_gbp > 0),
        forward_days integer not null check (forward_days > 0),
        backward_months integer not null check (backward_months > 0),
        backward_test_day integer not null check (backward_test_day between 1 and 28),
        lookback_floor_date date,
        warning_ratio numeric(5,4) not null check (warning_ratio > 0 and warning_ratio <= 1)
        """,
        (),
    ),
    "registration_rules": (
        """
        rule text not null check (rule in ('ordinary_30_day','first_year_transitional')),
        days integer check (days > 0),
        fixed_deadline date,
        check (days is not null or fixed_deadline is not null)
        """,
        ("rule",),
    ),
    "service_state": (
        """
        service text not null check (service ~ '^[a-z][a-z0-9_]*$'),
        opening_date date not null
        """,
        ("service",),
    ),
    "exclusion_rules": (
        """
        rule_key text not null check (rule_key ~ '^[a-z][a-z0-9_.]*$'),
        description text not null,
        applies_when text
        """,
        ("rule_key",),
    ),
    "origin_rules": (
        """
        rule_key text not null check (rule_key ~ '^[a-z][a-z0-9_.]*$'),
        description text not null,
        value_text text
        """,
        ("rule_key",),
    ),
    "geography_rules": (
        """
        geography text not null check (geography ~ '^[A-Z]{2}$'),
        in_uk_cbam_scope boolean not null,
        description text not null
        """,
        ("geography",),
    ),
    "tax_point_rules": (
        """
        rule_key text not null check (rule_key ~ '^[a-z][a-z0-9_.]*$'),
        procedure_code text,
        tax_point_event text not null,
        description text not null
        """,
        ("rule_key",),
    ),
    "working_days": (
        """
        jurisdiction text not null check (jurisdiction ~ '^[A-Z][A-Z_-]*$'),
        day date not null,
        is_working_day boolean not null
        """,
        ("jurisdiction", "day"),
    ),
    "sector_forms": (
        """
        sector text not null check (sector ~ '^[a-z][a-z_]*$'),
        code_pattern text not null,
        gases text,
        functional_unit text,
        routes text,
        questions jsonb,
        evidence_slots jsonb
        """,
        ("sector", "code_pattern"),
    ),
    "cds_report_layouts": (
        """
        report_type text not null
          check (report_type in ('import_item','import_header','import_tax_lines','export_item')),
        column_name text not null,
        maps_to text,
        required boolean not null
        """,
        ("report_type", "column_name"),
    ),
    "customs_monthly_exchange_rates": (
        """
        currency text not null check (currency ~ '^[A-Z]{3}$'),
        quote text not null check (quote in ('foreign_per_gbp','gbp_per_foreign')),
        rate numeric(18,8) not null check (rate > 0)
        """,
        ("currency",),
    ),
    "compliance_calendar": (
        """
        period text not null check (period ~ '^[0-9]{4}(Q[1-4])?$'),
        return_due date not null,
        payment_due date not null
        """,
        ("period",),
    ),
}


def _create(name: str, columns: str, key: tuple[str, ...]) -> str:
    table = f"cbam.ref_{name}"
    exclude_key = "".join(f"{col} with =, " for col in key)
    return f"""
    create table {table} (
      id uuid primary key,
      dataset_version_id uuid not null references cbam.ref_dataset_versions (id),
      effective_from date not null,
      effective_to date,
      {columns},
      check (effective_to is null or effective_to > effective_from),
      constraint ref_{name}_no_overlap exclude using gist (
        dataset_version_id with =, {exclude_key}
        daterange(effective_from, effective_to) with &&)
    );
    create index ref_{name}_version on {table} (dataset_version_id);
    create trigger ref_{name}_guard before insert or update or delete on {table}
      for each row execute function cbam.ref_data_guard();
    create trigger ref_{name}_guard_truncate before truncate on {table}
      for each statement execute function cbam.ref_data_guard();
    revoke update, delete, truncate on {table} from cbam_app;
    alter table {table} enable row level security;
    alter table {table} force row level security;
    create policy open_read on {table} for select using (true);
    create policy platform_insert on {table} for insert with check (cbam.is_platform());

    create view cbam.v_active_{name} as
    select t.*,
           v.version as dataset_version,
           s.source_id as source_ref,
           s.status as source_status,
           greatest(t.effective_from, s.commencement_date, s.effective_from) as usable_from,
           least(t.effective_to, s.effective_to) as usable_to
    from {table} t
    join cbam.ref_dataset_versions v on v.id = t.dataset_version_id
    join cbam.regulatory_sources s on s.id = v.source_id
    where v.status = 'active' and s.status in ('in_force','commenced','superseded');
    revoke insert, update, delete, truncate on cbam.v_active_{name} from cbam_app;
    """  # noqa: S608 - names come from the fixed list above


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    for name, (columns, key) in _DATASETS.items():
        op.execute(_create(name, columns, key))


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    for name in reversed(list(_DATASETS)):
        op.execute(f"drop view if exists cbam.v_active_{name}")
        op.execute(f"drop table if exists cbam.ref_{name}")
