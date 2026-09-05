#!/usr/bin/env bash
# Refuse to let a credential into the repository.
#
# A real Groq key reached git history once, through deploy/.env.bak-preflip —
# a backup of a gitignored secrets file, which the ignore rules did not cover.
# The lesson encoded here: scan CONTENT, not just filenames, because the next
# leak will arrive under a name nobody predicted.
#
#   pre-commit:  scans staged content
#   CI:          scans the whole working tree  (--all)
set -uo pipefail

if [[ "${1:-}" == "--all" ]]; then
  FILES=$(git ls-files)
  MODE="working tree"
else
  FILES=$(git diff --cached --name-only --diff-filter=ACM)
  MODE="staged changes"
fi
[[ -z "$FILES" ]] && exit 0

# token-shaped credentials; each pattern requires enough entropy after the
# prefix that documentation placeholders like "gsk_..." do not trip it.
PATTERNS=(
  'gsk_[A-Za-z0-9]{20,}'          # Groq
  'sk-[A-Za-z0-9]{32,}'           # OpenAI
  'hf_[A-Za-z0-9]{20,}'           # HuggingFace
  'AKIA[0-9A-Z]{16}'              # AWS access key id
  'ghp_[A-Za-z0-9]{30,}'          # GitHub PAT
  '-----BEGIN [A-Z ]*PRIVATE KEY' # any private key
)

hits=0
for f in $FILES; do
  [[ -f "$f" ]] || continue
  case "$f" in scripts/check-secrets.sh) continue;; esac   # this file names the patterns
  for p in "${PATTERNS[@]}"; do
    if match=$(grep -nEI "$p" "$f" 2>/dev/null | head -3); then
      [[ -z "$match" ]] && continue
      echo "SECRET  $f"
      echo "$match" | sed 's/^/        /'
      hits=$((hits+1))
    fi
  done
done

if (( hits )); then
  printf '\nRefusing: credential-shaped content found in the %s.\n' "$MODE"
  echo "If this is a real key: rotate it first, then remove it from the file."
  echo "If it is a placeholder, make it obviously fake (e.g. gsk_xxx)."
  exit 1
fi
exit 0
