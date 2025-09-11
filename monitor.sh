#!/bin/bash
# This script monitor the content of a directory, and when a new file is created
# it will send the file to a remote server using HTTP POST request.

# Configuration
DATE=$(date + "%Y-%m-%d_%H%M")
DIR="Camera/timelapse/$DATE"

REMOTE_URL="https://dcu.allietran.com/omi/be/upload"

# function to send file to remote server
send_file() {
    local file_path="$1"
    timestamp=$(date -r "$file_path" +"%s")
    timestamp=$((timestamp * 1000))
    echo "Sending file: $file_path"
    curl -X POST -F "file=@${file_path}" -F "timestamp=${timestamp}" "$REMOTE_URL"
}

# Monitor the directory for new files
inotifywait -m -e create --format '%w%f' "$DIR" | while read -r NEW_FILE;
do
    send_file "$NEW_FILE"
done
