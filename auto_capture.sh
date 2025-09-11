#!/bin/bash

while ! rpicam-still --output starting.jpg
do
	sleep 1
done

TIMEOUT=0
TIMELAPSE=30 # in seconds
DATE=$(date +"%Y-%m-%d")
OUTPUT="Camera/timelapse/$DATE"

test -d $OUTPUT || mkdir -p $OUTPUT
rpicam-still --timeout $TIMEOUT --timelapse $((TIMELAPSE * 1000)) -o $OUTPUT/%04d.jpg
