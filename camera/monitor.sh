#!/bin/bash
LOGFILE="/home/allie/Camera/camera/monitor.log"
STARTTIME=$(date '+%Y-%m-%d %H:%M:%S %Z')

echo $STARTTIME > start_time.txt
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monitor.py" >> "$LOGFILE"
    python3 -u /home/allie/Camera/camera/watchdog_monitor.py >> "$LOGFILE" 2>&1
    EXITCODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script crashed with exit code $EXITCODE. Restarting in 5 seconds..." >> "$LOGFILE"
    sleep 5
done

