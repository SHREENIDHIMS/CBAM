"""Helpers to write throwaway dataset folders (with a correct checksum) for refdata tests."""

import hashlib
from datetime import date
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "refdata"

CODES_V1 = """code_prefix,listing_text,sector,description,greenhouse_gases,in_scope,exclusion_within
72,72,iron_and_steel,Iron and steel,Carbon dioxide,true,
7204,Except 7204,iron_and_steel,Ferrous waste and scrap,,false,72
2804,2804,hydrogen,Hydrogen,Carbon dioxide,true,
"""


def write_dataset(
    root: Path,
    *,
    dataset: str = "cbam_commodity_codes",
    version: str = "t.1",
    csv: str = CODES_V1,
    source_id: str = "TEST-SOURCE",
    source_status: str = "laid",
    effective_from: date = date(2027, 1, 1),
    effective_to: date | None = None,
    fixture: bool = True,
    commencement_date: date | None = None,
    extra: str = "",
    checksum: str | None = None,
) -> Path:
    folder = root / dataset / version
    folder.mkdir(parents=True, exist_ok=True)
    data = csv.encode()
    (folder / "data.csv").write_bytes(data)
    digest = checksum or hashlib.sha256(data).hexdigest()
    lines = [
        f"dataset: {dataset}",
        f'version: "{version}"',
        f"source_id: {source_id}",
        "source_title: Test source (not law)",
        "source_type: guidance",
        "retrieved_at: 2026-10-03",
        f"source_status: {source_status}",
        f"effective_from: {effective_from.isoformat()}",
        f"effective_to: {effective_to.isoformat() if effective_to else 'null'}",
        f"checksum_sha256: {digest}",
        f"fixture: {'true' if fixture else 'false'}",
    ]
    if commencement_date:
        lines.append(f"commencement_date: {commencement_date.isoformat()}")
    (folder / "manifest.yaml").write_text("\n".join(lines) + "\n" + extra)
    return folder
