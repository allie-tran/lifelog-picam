
# --- custom: start KC002 photo capture loop ---
{
    WAIT=0
    while [ ! -x /tmp/sd/capture_loop.sh ] && [ $WAIT -lt 30 ]; do
        sleep 1
        WAIT=$((WAIT+1))
    done
    if [ -x /tmp/sd/capture_loop.sh ]; then
        /tmp/sd/capture_loop.sh >> /tmp/sd/capture_loop.log 2>&1 &
    else
        echo "$(date -u) capture_loop.sh not found after ${WAIT}s wait" >> /tmp/sd/capture_loop_start_error.log
    fi
} &
