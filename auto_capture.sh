#!/bin/bash
LOGFILE="/home/allie/Camera/auto_capture.log"
TIMEOUT=60  # Seconds to wait before deciding it's "stuck"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting auto_capture.py" >> "$LOGFILE"

    # Start the python script in the background
    python3 -u /home/allie/Camera/auto_capture.py >> "$LOGFILE" 2>&1 &
    PYTHON_PID=$!

    while kill -0 $PYTHON_PID 2>/dev/null; do
        # Check the last modification time of the log file
        LAST_MOD=$(stat -c %Y "$LOGFILE")
        CURRENT_TIME=$(date +%s)
        DIFF=$((CURRENT_TIME - LAST_MOD))

        if [ $DIFF -gt $TIMEOUT ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script hung (no log activity for $DIFF s). Killing PID $PYTHON_PID" >> "$LOGFILE"
            kill -9 $PYTHON_PID
            sleep 2
            break
        fi

        sleep 10  # Check every 10 seconds
    done

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script exited or killed. Restarting in 5s..." >> "$LOGFILE"
    sleep 5
done

