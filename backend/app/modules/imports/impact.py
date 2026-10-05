"""Impact provider for the commodity-code dataset (Phase 2 impact report, Phase 3 step 4).

When a new version of the code list is dry-run, the report lists which downstream records could
change outcome. For import lines that is a COUNT per tenant for each changed code prefix, read
through the SECURITY DEFINER function `cbam.impact_line_counts_by_code_prefix` (migration 0011):
counts of current lines only, never an id, a value or a name (CLAUDE.md rule 7; docs/SECURITY.md
lists this as the first cross-tenant code path).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.modules.refdata import rules as refdata_rules
from app.modules.refdata import service as refdata

DATASET = "cbam_commodity_codes"
MAX_PREFIXES_PER_CALL = 1000  # the database function refuses more


def line_impact(
    session: Session, diff: refdata_rules.VersionDiff
) -> Sequence[refdata.AffectedItem]:
    """One call per 1000 changed prefixes (the function refuses more). The function is for
    platform mode, which the caller's session already is."""
    prefixes = sorted({str(c.key["code_prefix"]) for c in diff.changes})
    if not prefixes:
        return []
    rows: list[Row[Any]] = []
    for start in range(0, len(prefixes), MAX_PREFIXES_PER_CALL):
        rows += session.execute(
            text(
                "select prefix, tenant_id, line_count"
                " from cbam.impact_line_counts_by_code_prefix(cast(:p as text[]))"
                " order by prefix, tenant_id"
            ),
            {"p": prefixes[start : start + MAX_PREFIXES_PER_CALL]},
        ).all()
    return [
        refdata.AffectedItem(
            "import_lines",
            str(r.tenant_id),
            f"{r.line_count} current line(s) under {r.prefix}",
            group=r.prefix,
            count=int(r.line_count),
        )
        for r in rows
    ]


def register() -> None:
    refdata.register_impact_provider(DATASET, line_impact)
