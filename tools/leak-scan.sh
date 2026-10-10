#!/usr/bin/env bash
# Fails if any term from the private blocklist appears in tracked files. The list lives outside the repo.
set -euo pipefail
LIST="${LEAK_LIST:-$HOME/.claude/private/leak-terms.txt}"
[ -f "$LIST" ] || { echo "no blocklist at $LIST"; exit 2; }
cd "$(dirname "$0")/.."
FILES=$(git ls-files); [ -z "$FILES" ] && FILES=$(rg --files); if echo "$FILES" | xargs rg -n -i -w -f "$LIST" --no-messages; then echo "LEAK: terms above must not be in this repo"; exit 1; fi
echo "leak scan clean"
