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

# rpicam-still --timeout $TIMEOUT -o $OUTPUT/image_%05d.jpg -n --framestart $start_index --timelapse $(($TIMELAPSE * 1000))

# Configuration
DATE=$(date +"%Y-%m-%d")
LOG_FILE="Camera/logs/$DATE.log"

# REMOTE_URL="https://dcu.allietran.com/omi/be/upload-image"
UPLOAD_URL="https://dcu.allietran.com/omi/be/upload-image"
CHECK_URL="https://dcu.allietran.com/omi/be/check-image-uploaded"

check_image_uploaded() {
    local file_path="$1"
    local log_file="$2"
    # Check if the file is in the log file
    if grep -Fxq "$file_path" "$log_file"; then
        return 0  # File already logged as sent
    fi

    timestamp=$(date -r "$file_path" +"%s")
    timestamp=$((timestamp * 1000))

    response=$(curl -s -o /dev/null -w "%{http_code}" -G "$CHECK_URL" --data-urlencode "timestamp=${timestamp}")
    if [ "$response" -eq 200 ]; then
        echo "OK"
        echo "$file_path" >> "$log_file"
        return 0  # File exists on server
    else
        echo "File $file_path does not exist on server."
        return 1  # File does not exist on server
    fi
}

# function to send file to remote server
send_file() {
    local file_path="$1"
    echo "Sending $file_path"
    timestamp=$(date -r "$file_path" +"%s")
    timestamp=$((timestamp * 1000))
    # sending file with retry logic
    retried=0
    while true; do
        if [ $retried -ge 5 ]; then
            echo "Failed to send $file_path after 5 attempts. Skipping."
            return
        fi
        response=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -F "file=@${file_path}" -F "timestamp=${timestamp}" "$UPLOAD_URL")
        if [ "$response" -eq 200 ]; then
            echo "File $file_path sent successfully."
            echo "$file_path" >> "$LOG_FILE"
            break
        else
            echo "Failed to send $file_path. HTTP status code: $response. Retrying in 1 seconds..."
            sleep 1
            retried=$((retried + 1))
        fi
    done
}

check_if_connected() {
    wget -q --spider http://google.com
    return $?
}

check_if_folder_is_synced() {
    local folder_path="$1"
    if [ -e "$folder_path/.synced" ]; then
        echo "OK"
        return 0  # Folder is marked as synced
    fi
    for file in "$folder_path"/*; do
        if [ -f "$file" ] && [[ "$file" == *.jpg ]]; then
            if ! check_image_uploaded "$file" "$folder_path/synced_files.txt"; then
                echo "Not synced"
                return 1  # Found a file that is not uploaded
            fi
        fi
    done
    echo "OK"
    touch "$folder_path/.synced"
}

# back up other folders that are not today
# if check_if_connected; then
#     echo "Internet connection is available."
#     echo "Checking previous folders"
#     for folder in Camera/timelapse/*; do
#     echo "$folder"
#         if [ -d "$folder" ] && [ "$(basename "$folder")" != "$DATE" ]; then
#             if ! check_if_folder_is_synced "$folder"; then
#                 echo "Folder $folder is not fully synced. Will attempt to upload remaining files."
#                 for file in "$folder"/*; do
#                     # Check if the file has already been sent
#                     if ! check_image_uploaded "$file"; then
#                         send_file "$file"
#                     fi
#                 done
#             fi
#         fi
#     done
#     echo "All previous folders are synced."
# fi

# Monitor the directory for new files
# echo "Watching $DIR"
# inotifywait -m "$DIR" -e create | while read -r directory action NEW_FILE
# do
#     send_file "$DIR/$NEW_FILE"
# done

echo "Starting timelapse capture loop."
while true; do
    file_name="image_$(printf "%05d" $start_index).jpg"
    rpicam-still -o $OUTPUT/$file_name -n

    echo "Captured image_$((start_index)).jpg"
    start_index=$((start_index + 1))
    sleep $TIMELAPSE

    # Upload the latest image to the server
    if check_if_connected; then
        if send_file "$OUTPUT/$file_name"
        then
            # Retry sending missing files
            if [ -f missing_files.txt ]; then
                echo "Retrying to send missing files..."
                while read -r missing_file; do
                    if [ -f "$missing_file" ]; then
                        send_file "$missing_file" && sed -i "\|$missing_file|d" missing_files.txt
                    else
                        echo "File $missing_file does not exist anymore. Removing from missing files list."
                        sed -i "\|$missing_file|d" missing_files.txt
                    fi
                done < missing_files.txt

                # If the file is empty after retries, remove it
                if [ ! -s missing_files.txt ]; then
                    rm missing_files.txt
                fi
            fi
        else
            echo $OUTPUT/$file_name >> missing_files.txt
        fi
    else
        echo "No internet connection. Will try to upload later."
        echo $OUTPUT/$file_name >> missing_files.txt
    fi
done
