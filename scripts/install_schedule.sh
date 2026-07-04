#!/usr/bin/env bash
#
# Install a launchd LaunchAgent that runs the job-pipeline daily at 07:00
# local time and prints the digest path on completion.
#
# Usage:   scripts/install_schedule.sh
# Uninstall:
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.jobpipeline.ingest.plist
#   rm ~/Library/LaunchAgents/com.jobpipeline.ingest.plist
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
PLIST_LABEL="com.jobpipeline.ingest"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_DIR="$REPO_DIR/data/logs"

mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$PLIST_PATH")"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>src.run_ingest</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/run_ingest.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/run_ingest.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Installed $PLIST_LABEL: runs daily at 07:00 local time."
echo "Plist: $PLIST_PATH"
echo "Logs:  $LOG_DIR/run_ingest.{out,err}.log"
echo
echo "To uninstall:"
echo "  launchctl bootout gui/\$(id -u) $PLIST_PATH"
echo "  rm $PLIST_PATH"
