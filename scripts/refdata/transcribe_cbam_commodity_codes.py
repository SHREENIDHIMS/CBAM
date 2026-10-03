#!/usr/bin/env python3
"""Rebuild backend/refdata/cbam_commodity_codes/<version>/ from HMRC's goods-in-scope pages.

Source: HMRC's "Check which goods are in scope of Carbon Border Adjustment Mechanism (CBAM)" and its
five sector pages, read through the GOV.UK content API. The legal source recorded for the data is
FA 2026 s.143(2) and Sch 16 (the regulatory analyst found the same codes there). The script only copies what HMRC published;
a domain owner checks the result before anything is activated (CLAUDE.md rule 15, GOV-DEC-009).

    python3 scripts/refdata/transcribe_cbam_commodity_codes.py 2027.1 --retrieved 2026-10-03

Rules of the transcription (nothing else is interpreted):
- The listed code is stored as digits only (`2523 21` -> `252321`); the code as published is
  kept in `listing_text`. HMRC lists headings and sub-headings and says everything below a
  listed code is in scope, so the lookup is longest-prefix.
- Rows in the "not liable" table start with "Except". They are stored with `in_scope=false`
  and `exclusion_within` = the code they carve out of (as published, or, when the page says
  only "Except 7204", the listed in-scope code of the same sector that covers it).
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = "https://www.gov.uk/api/content/government/publications/"
INDEX = "check-which-goods-are-in-scope-of-carbon-border-adjustment-mechanism-cbam"
SECTORS = {
    "aluminium": "aluminium",
    "cement": "cement",
    "fertiliser": "fertiliser",
    "hydrogen": "hydrogen",
    "iron_and_steel": "iron-and-steel",
}
HEADER = [
    "code_prefix",
    "listing_text",
    "sector",
    "description",
    "greenhouse_gases",
    "in_scope",
    "exclusion_within",
]


def fetch(slug: str) -> dict:
    with urllib.request.urlopen(ROOT + slug, timeout=60) as response:  # noqa: S310 - fixed https URL
        return json.load(response)


def clean(cell: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()


def tables(body: str) -> list[list[list[str]]]:
    found = []
    for table in re.findall(r"<table.*?</table>", body, re.S):
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
            rows.append(cells[:3])
        found.append(rows)
    return found


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def rows_for(sector: str, slug: str) -> list[list[str]]:
    page = fetch(f"{INDEX}/goods-within-the-{slug}-sector")
    out: list[list[str]] = []
    listed: list[str] = []
    for table in tables(page["details"]["body"]):
        for cells in table[1:]:  # skip the header row
            listing, description, gases = (cells + ["", ""])[:3]
            gases = "" if gases.lower() == "not applicable" else gases
            if listing.lower().startswith("except"):
                match = re.match(r"except:?\s*([\d ]+?)(?:\s+within\s+([\d ]+))?$", listing, re.I)
                if not match:
                    sys.exit(f"cannot read exception row: {listing!r}")
                prefix = digits(match.group(1))
                within = digits(match.group(2)) if match.group(2) else ""
                if not within:
                    covering = [c for c in listed if prefix.startswith(c) and c != prefix]
                    if len(covering) != 1:
                        sys.exit(f"cannot place exception {listing!r} within one listed code")
                    within = covering[0]
                out.append([prefix, listing, sector, description, gases, "false", within])
            else:
                prefix = digits(listing)
                listed.append(prefix)
                out.append([prefix, listing, sector, description, gases, "true", ""])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--retrieved", default=date.today().isoformat())
    ap.add_argument("--out", default="backend/refdata/cbam_commodity_codes")
    args = ap.parse_args()

    all_rows: list[list[str]] = []
    updated = set()
    for sector, slug in SECTORS.items():
        all_rows += rows_for(sector, slug)
        updated.add(fetch(f"{INDEX}/goods-within-the-{slug}-sector")["public_updated_at"][:10])
    prefixes = [r[0] for r in all_rows]
    if len(prefixes) != len(set(prefixes)):
        sys.exit("a code prefix is listed twice")

    folder = Path(args.out) / args.version
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "data.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(all_rows)
    checksum = hashlib.sha256((folder / "data.csv").read_bytes()).hexdigest()
    published = max(updated)
    (folder / "manifest.yaml").write_text(
        f"""dataset: cbam_commodity_codes
version: "{args.version}"
source_id: FA2026-SCH16
source_title: "Finance Act 2026, section 143(2) and Schedule 16 (CBAM goods)"
source_type: legislation
source_url: https://www.legislation.gov.uk/ukpga/2026/11/schedule/16
commencement_date: 2027-01-01
retrieved_at: {args.retrieved}
source_status: laid
effective_from: 2027-01-01
effective_to: null
checksum_sha256: {checksum}
fixture: false
notes: >-
  Copied by scripts/refdata/transcribe_cbam_commodity_codes.py from the five HMRC sector pages
  (GOV.UK content API, pages last updated {published}); the regulatory analyst compared the
  codes with the goods table in FA 2026 Sch 16 para 1 (s.143(2) says a CBAM good is one specified
  by that Schedule; s.158(1): effect for goods imported on or after 1 January 2027) and found
  the same codes. Descriptions are HMRC's wording, not the statute's. NOT YET CHECKED by the
  domain owner. The source is registered `laid`; the domain owner sets it in force once she has
  confirmed the legal basis and that no regulations under Sch 16 para 2(3) changed the table
  (GOV-DEC-009, REG-DEC-018). This version stays pending until then. HMRC lists headings and
  sub-headings, and Sch 16 says goods within a listed code other than those the table excepts, so
  lookups use the longest listed prefix and the loader checks that every exception sits under a
  listed code. "Except 7204" has no parent on HMRC's page; it is stored within 72, as Sch 16 puts it.
"""
    )
    print(f"{len(all_rows)} rows -> {folder} (sha256 {checksum[:12]}...)")  # noqa: T201


if __name__ == "__main__":
    main()
