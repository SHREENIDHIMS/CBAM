---
description: Add or update a versioned CBAM reference dataset safely (law is data)
argument-hint: <dataset name> <new version> [source URL]
---

Prepare a reference-data change for: **$ARGUMENTS**

Follow the `reference-data` skill. Steps:

1. Identify the dataset and its table (`docs/DATABASE.md` §4). Never edit an existing
   version folder; create `backend/refdata/<dataset>/<new version>/`.
2. Record the source in the manifest: source ID, URL, title, status
   (draft/laid/in_force/commenced/superseded), commencement date, retrieved date.
   Use the `regulatory-analyst` agent to confirm status. A draft source may be loaded
   but must not be activated.
3. Write `data.csv`/`data.yaml` transcribed from the source; note in the manifest who
   transcribed it. Compute and store the SHA-256.
4. Load locally with the loader; run the dry-run impact report; show which decisions
   and lines would change.
5. Add/adjust scenario tests that cover the new values' effective dates (before/after
   boundary).
6. Stop. Activation is done in the app by the domain owner (GOV-DEC-009), on staging
   then production — never by Claude.
