#!/bin/bash

FILE_DIR=$( dirname -- "${BASH_SOURCE[0]}" )
LOGFILE="$FILE_DIR/monitor.log"


while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monitor.py" >> "$LOGFILE"
    python3 -u "${FILE_DIR}/watchdog_monitor.py" >> "$LOGFILE" 2>&1
    EXITCODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script crashed with exit code $EXITCODE. Restarting in 5 seconds..." >> "$LOGFILE"
    sleep 5
done

