#!/bin/bash
LOGFILE="/home/allie/Camera/auto_capture.log"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting auto_capture.py" >> "$LOGFILE"
    python3 -u /home/allie/Camera/auto_capture.py >> "$LOGFILE" 2>&1
    EXITCODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script crashed with exit code $EXITCODE. Restarting in 5 seconds..." >> "$LOGFILE"
    sleep 5
done

