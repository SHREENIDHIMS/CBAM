"""The shape of each reference dataset: table, columns, key and prefix column.

This is schema metadata, not law: it says which columns a dataset's CSV must have and how to
parse them. Every value of a dataset comes from a versioned file under `backend/refdata/`
(CLAUDE.md rule 1). It mirrors migration 0008; a test compares the two.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["text", "int", "bool", "date", "decimal", "json"]


@dataclass(frozen=True)
class Column:
    name: str
    kind: Kind
    optional: bool = False


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]  # business key; with the effective period it must not overlap
    prefix_column: str | None = None  # set when lookups match the longest listed prefix

    @property
    def table(self) -> str:
        return f"ref_{self.name}"

    @property
    def view(self) -> str:
        return f"v_active_{self.name}"

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _c(name: str, kind: Kind = "text", *, optional: bool = False) -> Column:
    return Column(name, kind, optional)


_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        "cbam_commodity_codes",
        (
            _c("code_prefix"),
            _c("listing_text"),
            _c("sector"),
            _c("description"),
            _c("greenhouse_gases", optional=True),
            _c("in_scope", "bool"),
            _c("exclusion_within", optional=True),
        ),
        key=("code_prefix",),
        prefix_column="code_prefix",
    ),
    DatasetSpec(
        "threshold_rules",
        (
            _c("threshold_gbp", "decimal"),
            _c("forward_days", "int"),
            _c("backward_months", "int"),
            _c("backward_test_day", "int"),
            _c("lookback_floor_date", "date", optional=True),
            _c("warning_ratio", "decimal"),
        ),
        key=(),
    ),
    DatasetSpec(
        "registration_rules",
        (
            _c("rule"),
            _c("days", "int", optional=True),
            _c("fixed_deadline", "date", optional=True),
        ),
        key=("rule",),
    ),
    DatasetSpec("service_state", (_c("service"), _c("opening_date", "date")), key=("service",)),
    DatasetSpec(
        "exclusion_rules",
        (_c("rule_key"), _c("description"), _c("applies_when", optional=True)),
        key=("rule_key",),
    ),
    DatasetSpec(
        "origin_rules",
        (_c("rule_key"), _c("description"), _c("value_text", optional=True)),
        key=("rule_key",),
    ),
    DatasetSpec(
        "geography_rules",
        (_c("geography"), _c("in_uk_cbam_scope", "bool"), _c("description")),
        key=("geography",),
    ),
    DatasetSpec(
        "tax_point_rules",
        (
            _c("rule_key"),
            _c("procedure_code", optional=True),
            _c("tax_point_event"),
            _c("description"),
        ),
        key=("rule_key",),
    ),
    DatasetSpec(
        "working_days",
        (_c("jurisdiction"), _c("day", "date"), _c("is_working_day", "bool")),
        key=("jurisdiction", "day"),
    ),
    DatasetSpec(
        "sector_forms",
        (
            _c("sector"),
            _c("code_pattern"),
            _c("gases", optional=True),
            _c("functional_unit", optional=True),
            _c("routes", optional=True),
            _c("questions", "json", optional=True),
            _c("evidence_slots", "json", optional=True),
        ),
        key=("sector", "code_pattern"),
    ),
    DatasetSpec(
        "cds_report_layouts",
        (
            _c("report_type"),
            _c("column_name"),
            _c("maps_to", optional=True),
            _c("required", "bool"),
            _c("date_format", optional=True),
        ),
        key=("report_type", "column_name"),
    ),
    DatasetSpec(
        "customs_monthly_exchange_rates",
        (_c("currency"), _c("quote"), _c("rate", "decimal")),
        key=("currency",),
    ),
    DatasetSpec(
        "liable_person_rules",
        (
            _c("rule_key"),
            _c("representation_type"),
            _c("declarant_relation"),
            _c("eori_context", optional=True),
            _c("liable_party"),
            _c("description"),
        ),
        key=("rule_key",),
    ),
    DatasetSpec(
        "compliance_calendar",
        (_c("period"), _c("return_due", "date"), _c("payment_due", "date")),
        key=("period",),
    ),
)

DATASETS: dict[str, DatasetSpec] = {spec.name: spec for spec in _SPECS}


def dataset_spec(name: str) -> DatasetSpec:
    """The spec for a dataset name; unknown names are refused, never guessed."""
    try:
        return DATASETS[name]
    except KeyError:
        raise KeyError(f"unknown reference dataset {name!r}") from None
