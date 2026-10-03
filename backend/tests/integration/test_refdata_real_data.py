"""R1-050 exit gate: the real datasets under backend/refdata load as pending, never as law.

The goods list was copied from HMRC's sector pages (see the manifest); the checks below use
the examples HMRC itself prints on those pages. A domain owner still has to check the list.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from app.modules.refdata import load as loader
from app.modules.refdata import service
from app.modules.refdata.manifest import parse_manifest
from tests.integration.test_refdata import (  # noqa: F401
    activate,
    clean,
    load,
    make_owner,
    open_source,
    scalar,
    session,
)

REAL = Path(__file__).resolve().parents[2] / "refdata"
CODES = REAL / "cbam_commodity_codes" / "2027.1"
CALENDAR = REAL / "compliance_calendar" / "2026-09-09"
ON = date(2027, 6, 1)


def test_real_datasets_are_never_fixtures_and_never_claim_to_be_in_force() -> None:
    manifests = sorted(REAL.glob("*/*/manifest.yaml"))
    assert manifests
    for path in manifests:
        manifest = parse_manifest(path.read_bytes())
        assert manifest.fixture is False, path
        assert manifest.source_status in ("draft", "laid"), path


def test_the_real_datasets_load_as_pending_and_are_served_to_nobody(app_engine: Engine) -> None:
    codes = load(app_engine, CODES)
    calendar = load(app_engine, CALENDAR)
    assert (codes.row_count, calendar.row_count) == (54, 5)
    assert (
        scalar(
            app_engine, "select count(*) from cbam.ref_dataset_versions where status = 'pending'"
        )
        == 2
    )
    with session(app_engine) as s:
        snap = service.snapshot(s, ["cbam_commodity_codes", "compliance_calendar"], on=ON)
    assert snap.version_ids == () and all(not rows for rows in snap.rows.values())
    assert load(app_engine, CODES).status == "unchanged"


def test_the_cli_loads_refuses_and_reloads(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(loader, "get_engine", lambda: app_engine)
    assert loader.main([str(CODES)]) == 0
    assert "loaded: cbam_commodity_codes 2027.1 (54 rows, pending)" in capsys.readouterr().out
    assert loader.main([str(CODES)]) == 0
    assert "unchanged:" in capsys.readouterr().out
    assert loader.main([str(CODES.parent / "missing")]) == 1
    assert "refused" in capsys.readouterr().err
    assert loader.main([]) == 2


def test_goods_lookups_match_the_examples_printed_by_hmrc(
    app_engine: Engine, admin_engine: Engine
) -> None:
    """Once the domain owner has activated the list and set its source in force."""
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, CODES)
    activate(app_engine, owner, "2027.1")
    open_source(app_engine, owner, "HMRC-CBAM-GOODS-SCOPE")

    def lookup(code: str) -> dict | None:  # type: ignore[type-arg]
        with session(app_engine) as s:
            return service.get_by_prefix(s, "cbam_commodity_codes", code, on=ON)

    hydrogen = lookup(
        "2804100000"
    )  # HMRC: "2804 1000 00 is not listed but is in scope ... 2804 10"
    cement = lookup("2523290000")  # HMRC: "2523 2900 00 ... falls under 2523 29"
    assert hydrogen and hydrogen["in_scope"] and hydrogen["sector"] == "hydrogen"
    assert cement and cement["in_scope"] and cement["code_prefix"] == "252329"
    steel = lookup("7208100000")  # under heading 72
    assert steel and steel["in_scope"] and steel["code_prefix"] == "72"
    scrap = lookup("7204100000")  # HMRC lists "Except 7204"
    assert scrap and scrap["in_scope"] is False and scrap["exclusion_within"] == "72"
    mixed = lookup("3105600000")  # "Except 3105 60 within 3105"
    assert mixed and mixed["in_scope"] is False
    other = lookup("3105100000")
    assert other and other["in_scope"] and other["code_prefix"] == "3105"
    assert lookup("9999000000") is None
