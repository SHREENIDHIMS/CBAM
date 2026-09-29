---
name: reference-data
description: How to model, load, look up and change versioned effective-dated regulatory reference data in CBAM (law is data, not code). Use when adding a ref_ table, a dataset version, a lookup in service code, or when a rule needs a regulatory value.
---

# Reference data (R1-050, R2-015, R2-020)

## The rule
Any value that comes from law, a notice or HMRC guidance (codes, thresholds, rates,
defaults, factors, deadlines, schemes, calendars, penalty amounts, form definitions)
lives in a `ref_*` table loaded from `backend/refdata/`. Code reads it by legal date.

## Table shape
```sql
create table cbam.ref_<name> (
  id uuid primary key,
  dataset_version_id uuid not null references cbam.ref_dataset_versions,
  effective_from date not null,
  effective_to date,                 -- exclusive; null = open
  -- business key + value columns (NUMERIC for numbers)
  ...
);
```
Add an exclusion constraint on (business key, `daterange(effective_from, effective_to)`)
among active versions, and a `v_active_<name>` view applying the activation rule
(`docs/DATABASE.md` §5).

## Files
`backend/refdata/<dataset>/<version>/manifest.yaml` + `data.csv|yaml`
(manifest fields: `docs/TECHNICAL_SPEC.md` §6). Never edit a loaded version — make a
new version folder. Test-only data goes in `backend/tests/fixtures/refdata/` with
`fixture: true` in the manifest.

## Lookup in services
```python
ref = refdata.snapshot(["threshold_rules", "cbam_commodity_codes"], on=tax_point_date)
result = rules.backward_test(lines, ref.threshold_rules, as_of=as_of)
decision.dataset_version_ids = ref.version_ids
```
- Always pass the **legal date** (`on=`), never "latest".
- Pass the snapshot into `rules.py`; `rules.py` never queries.
- Store `ref.version_ids` on the decision so replay uses the same data.

## Changing data
Use `/refdata`. Load → dry-run impact report → domain owner activates (staging, then
production). Claude never activates.

## Red flags in review
- A literal like `50000`, `Decimal("0.8")`, `"2028-01-31"`, a code list, or a rate in
  `app/` code.
- A lookup without a date.
- A dataset whose manifest `source_status` is `draft` but whose version is `active`.
