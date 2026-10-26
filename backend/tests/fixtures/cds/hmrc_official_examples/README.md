# HMRC Get customs data example fixtures

These CSVs contain **synthetic values only** under the exact headers extracted from HMRC's
official blank example ODS workbooks. They are not real declarations and must not be used as
evidence of actual value/date formatting.

Sources:

- [Get customs data for import and export declarations](https://www.gov.uk/guidance/get-customs-data-for-import-and-export-declarations)
- [Customs data report descriptions](https://www.gov.uk/government/publications/customs-data-report-descriptions)

HMRC updated the example downloads on 26 February 2026 and the field descriptions on
29 September 2026. `sources.json` pins each downloaded workbook URL and SHA-256 digest.
Regenerate with:

```powershell
python scripts/fixtures/build_hmrc_gcd_examples.py --source-dir <folder-with-item-header-tax_lines-ods>
```

Known limits (DATA-DEC-002):

- The ODS examples contain headers but no data rows, so all values here are invented.
- The fake dates use `DD/MM/YYYY`; an actual masked CSV must confirm the export format.
- The fixture maps `Invoice Currency` to the customs-value currency only because both fake
  invoice and customs values are GBP. That is not a general mapping for real reports.
- Representation code transformation and legal liable-person decisions remain out of scope.
