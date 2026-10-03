#!/usr/bin/env bash
# CLAUDE.md rule 5: no float in money, mass, emissions, rates or FX.
set -euo pipefail
cd "$(dirname "$0")/../backend"
if grep -rnE '\bfloat\(|: *float\b|-> *float\b|\bfloat\b *\|' app --include='*.py'; then
  echo "float found in app/ - use Decimal" >&2
  exit 1
fi
echo "float-ban: clean"
