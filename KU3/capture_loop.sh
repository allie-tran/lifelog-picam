#!/bin/sh
# KC002 lifelog capture loop (v2).
#
# Started at boot by the hook appended to /config/app/bin/app_init.sh (see README.md; setup.py
# installs both). Shoots a still every INTERVAL seconds into PHOTO_DIR as
# YYYYMMDD_HHMMSS.jpg (UTC), which the SelfHealth app pulls over FTP.
#
# Everything tunable lives in $PHOTO_DIR/_capture.conf, which the app writes over FTP. Only the
# keys below are read, each is range-checked, and the file is never sourced — it arrives over the
# network and this runs as root. The loop reports back through $PHOTO_DIR/_status.txt and takes a
# one-off photo whenever $PHOTO_DIR/_snap_now appears. Control files start with "_" and none end
# in .jpg, so the app's photo listing never mistakes them for photos.

SCRIPT_VERSION=2
SD=/tmp/sd
SNAP_SRC=/tmp/jpg/1_jpgSnap.jpg
PHOTO_DIR=$SD/kc002_photos
CONF=$PHOTO_DIR/_capture.conf
STATUS=$PHOTO_DIR/_status.txt
SNAP_REQ=$PHOTO_DIR/_snap_now
LOG=$SD/kc002_capture.log
LOG_MAX_BYTES=262144
PIDFILE=/tmp/capture_loop.pid
SNAP_MARK=/tmp/capture_loop.snap_mark
RECORD_JPG=$SD/Record/Jpg

# Defaults. Re-applied before every load, so a key dropped from the config reverts rather than
# sticking at whatever it was last set to.
set_defaults() {
    INTERVAL=30          # seconds between photos, 3..3600
    PAUSED=0             # 1 = take no scheduled photos (a snap request still works)
    RETENTION_HOURS=24   # delete photos older than this; 0 = keep until space runs low
    MIN_FREE_MB=512      # below this free space, delete oldest photos first
    QUIET_START=-1       # local hour 0..23 when quiet time starts; -1 = no quiet time
    QUIET_END=-1         # local hour 0..23 when it ends (exclusive)
    UTC_OFFSET_MIN=0     # the phone's offset, so quiet hours follow the wearer's clock, not the camera's
    PRUNE_RECORD=1       # 1 = the firmware's own Record/Jpg copies follow the same retention (and go first when space runs low)
    CONFIG_ID=default    # echoed in the status file so the app knows its config landed
}
set_defaults

CR=$(printf '\r')

log() {
    if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt "$LOG_MAX_BYTES" ]; then
        mv -f "$LOG" "$LOG.1"
    fi
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

is_uint() {
    case "$1" in ''|*[!0-9]*) return 1 ;; esac
    return 0
}

# in_range VALUE MIN MAX
in_range() {
    is_uint "$1" && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]
}

LOADED_CONF=

load_config() {
    LOADED_CONF=$(cat "$CONF" 2>/dev/null)
    set_defaults
    [ -f "$CONF" ] || return 0
    while IFS='=' read -r key val || [ -n "$key" ]; do
        val=${val%"$CR"}
        case "$key" in
            INTERVAL)        in_range "$val" 3 3600 && INTERVAL=$val ;;
            PAUSED)          in_range "$val" 0 1 && PAUSED=$val ;;
            RETENTION_HOURS) in_range "$val" 0 8760 && RETENTION_HOURS=$val ;;
            MIN_FREE_MB)     in_range "$val" 64 65536 && MIN_FREE_MB=$val ;;
            QUIET_START)     { [ "$val" = "-1" ] || in_range "$val" 0 23; } && QUIET_START=$val ;;
            QUIET_END)       { [ "$val" = "-1" ] || in_range "$val" 0 23; } && QUIET_END=$val ;;
            UTC_OFFSET_MIN)
                # Signed: strip one leading '-' for the check, keep it for the value.
                in_range "${val#-}" 0 900 && UTC_OFFSET_MIN=$val ;;
            PRUNE_RECORD)    in_range "$val" 0 1 && PRUNE_RECORD=$val ;;
            CONFIG_ID)
                case "$val" in ''|*[!A-Za-z0-9_-]*) ;; *) CONFIG_ID=$val ;; esac ;;
        esac
    done < "$CONF"
}

# Compared by content, not mtime: an FTP write can land within the same second as the last load,
# and busybox `test -nt` only compares whole seconds.
config_changed() {
    [ "$(cat "$CONF" 2>/dev/null)" != "$LOADED_CONF" ]
}

in_quiet_hours() {
    [ "$QUIET_START" -ge 0 ] && [ "$QUIET_END" -ge 0 ] || return 1
    [ "$QUIET_START" -eq "$QUIET_END" ] && return 1
    hour=$(( ( ( $(date +%s) + UTC_OFFSET_MIN * 60 ) / 3600 ) % 24 ))
    if [ "$QUIET_START" -lt "$QUIET_END" ]; then
        [ "$hour" -ge "$QUIET_START" ] && [ "$hour" -lt "$QUIET_END" ]
    else
        # Wraps midnight, e.g. 23 -> 7.
        [ "$hour" -ge "$QUIET_START" ] || [ "$hour" -lt "$QUIET_END" ]
    fi
}

free_mb() {
    # -P keeps each filesystem on one line so the 4th field is always "Available".
    set -- $(df -Pk "$SD" 2>/dev/null | tail -n 1)
    is_uint "$4" && echo $(( $4 / 1024 )) || echo -1
}

file_size() {
    wc -c < "$1" 2>/dev/null || echo 0
}

LAST_CAPTURE=
LAST_ERROR=
CAPTURES=0
FAILURES=0
STATE=starting

# Takes one photo. The firmware drops each snapshot at SNAP_SRC, overwriting the last one, so the
# old loop would happily re-copy a stale frame whenever a trigger silently failed. Here the frame
# must be newer than a marker touched a second before the trigger, and its size must hold still
# before it is copied (the firmware may still be writing it).
capture() {
    touch "$SNAP_MARK"
    sleep 1
    umsinicmd SysCtrl.Jpeg=1 >/dev/null 2>&1

    waited=0
    prev=-1
    while [ "$waited" -lt 8 ]; do
        sleep 1
        waited=$((waited + 1))
        if [ -f "$SNAP_SRC" ] && [ "$SNAP_SRC" -nt "$SNAP_MARK" ]; then
            size=$(file_size "$SNAP_SRC")
            if [ "$size" -gt 0 ] && [ "$size" -eq "$prev" ]; then
                break
            fi
            prev=$size
        fi
    done

    if ! [ -f "$SNAP_SRC" ] || ! [ "$SNAP_SRC" -nt "$SNAP_MARK" ] || [ "$prev" -le 0 ]; then
        FAILURES=$((FAILURES + 1))
        LAST_ERROR="no fresh frame from the camera"
        log "capture failed: $LAST_ERROR"
        return 1
    fi

    ts=$(date -u +%Y%m%d_%H%M%S)
    # Copy under a name the app ignores, then rename: FTP must never serve a half-written JPEG.
    if cp "$SNAP_SRC" "$PHOTO_DIR/$ts.part" && mv -f "$PHOTO_DIR/$ts.part" "$PHOTO_DIR/$ts.jpg"; then
        LAST_CAPTURE=$ts
        LAST_ERROR=
        CAPTURES=$((CAPTURES + 1))
        return 0
    fi
    rm -f "$PHOTO_DIR/$ts.part"
    FAILURES=$((FAILURES + 1))
    LAST_ERROR="could not write to the SD card"
    log "capture failed: $LAST_ERROR"
    return 1
}

# Age-based cleanup, then a free-space floor. Oldest first: filenames sort chronologically.
prune() {
    if [ "$RETENTION_HOURS" -gt 0 ]; then
        # -exec rm, not -delete: not every busybox build has -delete.
        find "$PHOTO_DIR" -name "*.jpg" -mmin +$((RETENTION_HOURS * 60)) -exec rm -f {} \; 2>/dev/null
        # The firmware files its own copy of every snapshot under Record/Jpg/<yyyymmdd_hh>/; left
        # alone those grow ~250 MB a day. Only .jpg files, so any video in Record is untouched.
        if [ "$PRUNE_RECORD" = "1" ] && [ -d "$RECORD_JPG" ]; then
            find "$RECORD_JPG" -name "*.jpg" -mmin +$((RETENTION_HOURS * 60)) -exec rm -f {} \; 2>/dev/null
            rmdir "$RECORD_JPG"/* 2>/dev/null   # only succeeds on the now-empty hour folders
        fi
    fi
    rm -f "$PHOTO_DIR"/*.part 2>/dev/null

    rounds=0
    while [ "$rounds" -lt 50 ]; do
        free=$(free_mb)
        [ "$free" -lt 0 ] || [ "$free" -ge "$MIN_FREE_MB" ] && return 0
        rounds=$((rounds + 1))
        # The firmware keeps its own copy of every frame; those go before photos not yet pulled.
        dir=
        [ "$PRUNE_RECORD" = "1" ] && dir=$(ls "$RECORD_JPG" 2>/dev/null | head -n 1)
        oldest=$(ls "$PHOTO_DIR" 2>/dev/null | grep '\.jpg$' | head -n 20)
        if [ -n "$dir" ]; then
            log "low space (${free}MB): deleting firmware copies in Record/Jpg/$dir"
            rm -rf "${RECORD_JPG:?}/$dir"
        elif [ -n "$oldest" ]; then
            log "low space (${free}MB): deleting oldest photos"
            for f in $oldest; do rm -f "$PHOTO_DIR/$f"; done
        else
            return 0
        fi
    done
}

# Vendor control API (see apidemo/readme.txt): prints "BatteryInfo.Percent=NN" then "OK".
battery() {
    v=$(umsinicmd BatteryInfo.Percent=? 2>/dev/null | sed -n 's/^BatteryInfo\.Percent=//p' | head -n 1)
    v=${v%"$CR"}
    is_uint "$v" && echo "$v" || echo -1
}

write_status() {
    photos=$(ls "$PHOTO_DIR" 2>/dev/null | grep -c '\.jpg$')
    {
        echo "SCRIPT_VERSION=$SCRIPT_VERSION"
        echo "CONFIG_ID=$CONFIG_ID"
        echo "STATE=$STATE"
        echo "INTERVAL=$INTERVAL"
        echo "LAST_CAPTURE=$LAST_CAPTURE"
        echo "LAST_ERROR=$LAST_ERROR"
        echo "CAPTURES=$CAPTURES"
        echo "FAILURES=$FAILURES"
        echo "PHOTOS=$photos"
        echo "FREE_MB=$(free_mb)"
        echo "BATTERY=$(battery)"
        echo "UPDATED=$(date -u +%Y%m%d_%H%M%S)"
    } > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"
}

# ---------------------------------------------------------------------------------------------
# Single instance: re-running the script (say, over telnet after an update) replaces nothing and
# must not start a second loop shooting in parallel.
if [ -f "$PIDFILE" ]; then
    old=$(cat "$PIDFILE")
    if is_uint "$old" && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null; then
        echo "capture_loop already running as $old"
        exit 0
    fi
fi
echo $$ > "$PIDFILE"

mkdir -p "$PHOTO_DIR"
load_config
log "started v$SCRIPT_VERSION: every ${INTERVAL}s, paused=$PAUSED, config=$CONFIG_ID"

next=$(date +%s)
last_prune=0
while true; do
    now=$(date +%s)

    if [ -f "$SNAP_REQ" ]; then
        rm -f "$SNAP_REQ"
        log "snap requested"
        capture
        next=$((now + INTERVAL))
        write_status
    elif [ "$now" -ge "$next" ]; then
        load_config
        if [ "$PAUSED" = "1" ]; then
            STATE=paused
        elif in_quiet_hours; then
            STATE=quiet
        elif capture; then
            STATE=capturing
        else
            STATE=error
        fi

        # Cleanup scans the whole directory, so it runs every few minutes, not every frame.
        if [ $((now - last_prune)) -ge 300 ]; then
            prune
            last_prune=$now
        fi
        write_status

        # Schedule from the planned time, not from when the capture finished, so the cadence does
        # not drift by the capture's own duration. Skip ahead rather than burst after a stall.
        next=$((next + INTERVAL))
        now=$(date +%s)
        [ "$next" -le "$now" ] && next=$((now + INTERVAL))
    elif config_changed; then
        old_interval=$INTERVAL
        load_config
        log "config $CONFIG_ID: every ${INTERVAL}s, paused=$PAUSED, quiet=$QUIET_START-$QUIET_END"
        # A shorter interval takes effect now rather than after the old, longer wait.
        [ "$INTERVAL" != "$old_interval" ] && [ $((now + INTERVAL)) -lt "$next" ] && next=$((now + INTERVAL))
        write_status
    fi

    sleep 1
done
