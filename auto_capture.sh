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
start_index=$(ls $OUTPUT | wc -l)
rpicam-still --timeout $TIMEOUT --timelapse $((TIMELAPSE * 1000)) -o $OUTPUT/image_%05d.jpg -n -w 1920 -h 1080 --framestart $start_index
