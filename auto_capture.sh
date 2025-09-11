#!/bin/bash

while ! rpicam-still --output starting.jpg
do
    echo "Waiting for camera to be ready..."
    sleep 1
done

echo "Camera is ready. Starting timelapse capture."
TIMEOUT=0
TIMELAPSE=30 # in seconds
DATE=$(date +"%Y-%m-%d")
OUTPUT="Camera/timelapse/$DATE"

echo "Saving images to $OUTPUT"
test -d $OUTPUT || mkdir -p $OUTPUT
start_index=$(ls $OUTPUT | wc -l)
rpicam-still --timeout $TIMEOUT -o $OUTPUT/image_%05d.jpg -n -w 1920 -h 1080 --framestart $start_index --rotation 180 --timelapse $(($TIMELAPSE * 1000))
