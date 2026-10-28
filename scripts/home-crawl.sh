#!/bin/bash
# Background crawl on the owner's Mac, run by launchd three times a day and at log-in
# (scripts/launchd/). Reads the four sources that block GitHub's servers — NNA, Elnashra,
# Janoubia, L'Orient Today — and saves their text to the private store.
# Runs from its own clone, always on main, so unfinished work in another clone never runs here.
# A Mac that was asleep or off catches up on its next run (crawler/pipeline.py, since_for).
# After saving something new it starts GitHub's crawl job, which classifies the new articles and
# publishes the Civil Defense bulletins (crawl.yml), with the owner's own GitHub login on this Mac.
# Everything is inside main(): the script updates itself (git pull), and bash reads a script as it
# runs, so the whole body is read before the update can change it.
set -uo pipefail

main() {
  local RUNNER="$HOME/Projects/lebanon-fire-incidents-runner"
  local LOG="$HOME/Library/Logs/lebanon-fire-incidents/crawl.log"
  mkdir -p "$(dirname "$LOG")"
  exec >>"$LOG" 2>&1
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') home crawl"
  cd "$RUNNER" || exit 1
  git pull -q --ff-only origin main || echo "code update failed (offline?): running the copy already here"
  git -C private pull -q --rebase || echo "store update failed (offline?): continuing"
  "$HOME/.local/bin/uv" run --quiet crawler run --where home
  # The two-year history (crawler/backfill.py): a little each run until it is complete.
  "$HOME/.local/bin/uv" run --quiet crawler backfill --where home --minutes 20
  cd private || exit 1
  git add raw state
  if ! git diff --cached --quiet; then
    git -c user.name="serge-netizen" -c user.email="293069954+serge-netizen@users.noreply.github.com" \
        commit -q -m "home crawl $(date -u +%Y-%m-%dT%H:%MZ)"
    if git pull -q --rebase && git push -q; then
      echo "saved to the private store"
      if "$HOME/.local/bin/gh" workflow run crawl.yml --repo serge-netizen/lebanon-fire-incidents >/dev/null 2>&1; then
        echo "GitHub crawl started: it classifies what was saved"
      else
        echo "could not start the GitHub crawl: its next scheduled run catches up"
      fi
    else
      echo "push failed: next run retries"
    fi
  fi
}

main "$@"
exit
