#!/bin/bash
# One-time setup on the owner's Mac: a clean clone for the background crawl, and its launchd
# schedule. Safe to run again (it refreshes the schedule).
# Undo: launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/org.lebanon-fire-incidents.home-crawl.plist
set -euo pipefail
LABEL="org.lebanon-fire-incidents.home-crawl"
RUNNER="$HOME/Projects/lebanon-fire-incidents-runner"
PUBLIC_REPO="https://github.com/serge-netizen/lebanon-fire-incidents.git"
PRIVATE_REPO="https://github.com/serge-netizen/lebanon-fire-incidents-data.git"
[ -d "$RUNNER/.git" ] || git clone -q "$PUBLIC_REPO" "$RUNNER"
[ -d "$RUNNER/private/.git" ] || git clone -q "$PRIVATE_REPO" "$RUNNER/private"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__HOME__#$HOME#g" "$RUNNER/scripts/launchd/$LABEL.plist" > "$DST"
plutil -lint "$DST"
launchctl bootout "gui/$(id -u)" "$DST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DST"
echo "installed $DST — log: ~/Library/Logs/lebanon-fire-incidents/crawl.log"
