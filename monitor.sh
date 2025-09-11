#!/bin/bash
# This script monitor the content of a directory, and when a new file is created
# it will send the file to a remote server using HTTP POST request.

# Configuration
DATE=$(date +"%Y-%m-%d")
DIR="Camera/timelapse/$DATE"

# REMOTE_URL="https://dcu.allietran.com/omi/be/upload-image"
REMOTE_URL="https://mysceal.computing.dcu.ie/omi/be/upload-image"

# function to send file to remote server
send_file() {
    local file_path="$1"
    timestamp=$(date -r "$file_path" +"%s")
    timestamp=$((timestamp * 1000))
    echo "Sending file: $file_path with timestamp: $timestamp"
    curl -X PUT -F "file=@${file_path}" -F "timestamp=${timestamp}" "$REMOTE_URL"
}

# Monitor the directory for new files
echo "Watching $DIR"
inotifywait -m "$DIR" -e create | while read -r directory action NEW_FILE
do
    send_file "$DIR/$NEW_FILE"
done
