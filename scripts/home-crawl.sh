#!/bin/bash
# Background crawl on the owner's Mac, run by launchd three times a day and at log-in
# (scripts/launchd/). Reads the four sources that block GitHub's servers — NNA, Elnashra,
# Janoubia, L'Orient Today — and saves their text to the private store.
# Runs from its own clone, always on main, so unfinished work in another clone never runs here.
# A Mac that was asleep or off catches up on its next run (crawler/pipeline.py, since_for).
set -uo pipefail
RUNNER="$HOME/Projects/lebanon-fire-incidents-runner"
LOG="$HOME/Library/Logs/lebanon-fire-incidents/crawl.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') home crawl"
cd "$RUNNER" || exit 1
git pull -q --ff-only origin main || echo "code update failed (offline?): running the copy already here"
git -C private pull -q --rebase || echo "store update failed (offline?): continuing"
"$HOME/.local/bin/uv" run --quiet crawler run --where home
cd private || exit 1
git add raw state
if ! git diff --cached --quiet; then
  git -c user.name="serge-netizen" -c user.email="293069954+serge-netizen@users.noreply.github.com" \
      commit -q -m "home crawl $(date -u +%Y-%m-%dT%H:%MZ)"
  if git pull -q --rebase && git push -q; then echo "saved to the private store"; else echo "push failed: next run retries"; fi
fi
