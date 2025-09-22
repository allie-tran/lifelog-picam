#!/bin/bash
# This script monitor the content of a directory, and when a new file is created
# it will send the file to a remote server using HTTP POST request.

# Configuration
DATE=$(date +"%Y-%m-%d")
DIR="Camera/timelapse/$DATE"
LOG_FILE="Camera/logs/$DATE.log"

# REMOTE_URL="https://dcu.allietran.com/omi/be/upload-image"
REMOTE_URL="https://mysceal.computing.dcu.ie/omi/be/upload-image"


# function to send file to remote server
send_file() {
    local file_path="$1"
    timestamp=$(date -r "$file_path" +"%s")
    timestamp=$((timestamp * 1000))
    # sending file with retry logic
    retried=0
    while true; do
        if [ $retried -ge 5 ]; then
            echo "Failed to send $file_path after 5 attempts. Skipping."
            return
        fi
        response=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -F "file=@${file_path}" -F "timestamp=${timestamp}" "$REMOTE_URL")
        if [ "$response" -eq 200 ]; then
            echo "File $file_path sent successfully."
            echo "$file_path" >> "$LOG_FILE"
            break
        else
            echo "Failed to send $file_path. HTTP status code: $response. Retrying in 5 seconds..."
            sleep 5
            retried=$((retried + 1))
        fi
    done
}

# back up other folders that are not today
for folder in Camera/timelapse/*; do
    if [ -d "$folder" ] && [ "$(basename "$folder")" != "$DATE" ]; then
        log_date=$(basename "$folder")
        log_file="Camera/logs/$log_date.log"
        for file in "$folder"/*; do
            if ! grep -q "^$file$" "$log_file"; then
                send_file "$file"
            fi
        done
    fi
done


# Monitor the directory for new files
echo "Watching $DIR"
inotifywait -m "$DIR" -e create | while read -r directory action NEW_FILE
do
    send_file "$DIR/$NEW_FILE"
done
