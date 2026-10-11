#!/usr/bin/env bash
# Link the solo-empire workspace trees that the lake code and tests resolve by
# repo-relative path (product repos, system contracts, templates, DB schema).
# The links are gitignored; set SOLO_EMPIRE_ROOT if the checkout is elsewhere.
set -euo pipefail
cd "$(dirname "$0")/.."
SE="${SOLO_EMPIRE_ROOT:-$HOME/solo-empire}"
for p in projects systems templates repository-catalog; do
  [ -e "$p" ] || ln -s "$SE/$p" "$p"
done
mkdir -p infra
[ -e infra/database ] || ln -s "$SE/infra/database" infra/database
echo "overlay linked from $SE"
