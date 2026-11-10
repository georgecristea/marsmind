#!/usr/bin/env bash
# Fetch the open-source Terraforming Mars engine into vendor/terraforming-mars
# at the exact commit cards/db.json was extracted from (its "commit" field).
#
# Needed only for the local app (mode 3, sparring seats) and for regenerating
# cards/db.json (extract_cards.py / audit_db.py). Modes 1-2 never need it.
#
#   scripts/vendor_bootstrap.sh            clone (shallow) or fast-forward to the pin
#   scripts/vendor_bootstrap.sh --build    ... then npm ci && npm run build (node 22.x)
#   scripts/vendor_bootstrap.sh --repo URL use a mirror instead of GitHub
#
# Idempotent: re-running on a clean checkout just re-pins. A dirty vendor
# directory (local edits) is never touched — commit or stash them first.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$ROOT/cards/db.json"
DEST="$ROOT/vendor/terraforming-mars"
REPO="https://github.com/terraforming-mars/terraforming-mars"
BUILD=0

usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD=1 ;;
    --repo) shift; REPO="${1:?--repo needs a URL}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in git python3; do
  command -v "$tool" >/dev/null || { echo "✗ $tool not found in PATH" >&2; exit 1; }
done
[ -f "$DB" ] || { echo "✗ $DB missing — cannot read the pinned commit" >&2; exit 1; }

PIN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$DB")"
case "$PIN" in
  *[!0-9a-f]*|"") echo "✗ cards/db.json has no usable \"commit\" field ($PIN)" >&2; exit 1 ;;
esac
echo "pinned engine commit: $PIN"

if [ -e "$DEST" ]; then
  if [ ! -d "$DEST/.git" ] && ! git -C "$DEST" rev-parse --git-dir >/dev/null 2>&1; then
    echo "✗ $DEST exists but is not a git checkout — move it aside first" >&2; exit 1
  fi
  if [ -n "$(git -C "$DEST" status --porcelain)" ]; then
    echo "✗ $DEST has local changes — commit or stash them; refusing to touch it" >&2
    exit 1
  fi
  HEAD="$(git -C "$DEST" rev-parse HEAD)"
  if [ "$HEAD" = "$PIN" ]; then
    echo "✓ vendor already at the pinned commit"
  else
    echo "· vendor at ${HEAD:0:10}, re-pinning to ${PIN:0:10}"
    git -C "$DEST" fetch --depth 1 origin "$PIN"
    git -C "$DEST" checkout --detach -q FETCH_HEAD
    echo "✓ vendor re-pinned"
  fi
else
  mkdir -p "$(dirname "$DEST")"
  echo "· cloning $REPO (shallow, single commit)"
  git init -q "$DEST"
  git -C "$DEST" remote add origin "$REPO"
  if git -C "$DEST" fetch --depth 1 origin "$PIN"; then
    git -C "$DEST" checkout --detach -q FETCH_HEAD
  else
    echo "· shallow fetch by commit refused by the server — full clone instead"
    rm -rf "$DEST"
    git clone -q "$REPO" "$DEST"
    git -C "$DEST" checkout --detach -q "$PIN"
  fi
  echo "✓ cloned to $DEST at ${PIN:0:10}"
fi

if [ "$BUILD" -eq 1 ]; then
  command -v npm >/dev/null || { echo "✗ npm not found (the app needs node 22.x)" >&2; exit 1; }
  echo "· npm ci && npm run build (several minutes on first run)"
  (cd "$DEST" && npm ci && npm run build)
  echo "✓ built"
fi

echo
echo "Next:"
[ "$BUILD" -eq 1 ] || echo "  build (once, node 22.x):  cd vendor/terraforming-mars && npm ci && npm run build"
cat <<EOF
  start the local app:      cd vendor/terraforming-mars && npm start      # http://localhost:8080
  create a game:            python3 scripts/newgame.py --players "You=red,Anna=green,Ben=yellow"
  check the card db:        python3 scripts/audit_db.py
EOF
