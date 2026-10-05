"""Impact provider for the commodity-code dataset (Phase 2 impact report, Phase 3 step 4).

When a new version of the code list is dry-run, the report lists which downstream records could
change outcome. For import lines that is a COUNT per tenant for each changed code prefix, read
through the SECURITY DEFINER function `cbam.impact_line_counts_by_code_prefix` (migration 0011):
counts of current lines only, never an id, a value or a name (CLAUDE.md rule 7; docs/SECURITY.md
lists this as the first cross-tenant code path).
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.refdata import rules as refdata_rules
from app.modules.refdata import service as refdata

DATASET = "cbam_commodity_codes"


def line_impact(
    session: Session, diff: refdata_rules.VersionDiff
) -> Sequence[refdata.AffectedItem]:
    prefixes = sorted({str(c.key["code_prefix"]) for c in diff.changes})
    items: list[refdata.AffectedItem] = []
    for prefix in prefixes:
        rows = session.execute(
            text(
                "select tenant_id, line_count"
                " from cbam.impact_line_counts_by_code_prefix(cast(:p as text[]))"
                " order by tenant_id"
            ),
            {"p": [prefix]},
        ).all()
        items.extend(
            refdata.AffectedItem(
                "import_lines", str(r.tenant_id), f"{r.line_count} current line(s) under {prefix}"
            )
            for r in rows
        )
    return items


def register() -> None:
    refdata.register_impact_provider(DATASET, line_impact)
