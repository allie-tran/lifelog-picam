
import os
DIR =  "/mnt/MySceal/LifelogPicam"
DELETE_DIR = "/mnt/MySceal/LifelogPicam-delete"
dry_run = True
dry_run = False
def delete_images(images):
    for image in images:
        image_path = os.path.join(DIR, image)
        delete_path = os.path.join(DELETE_DIR, image)
        if os.path.exists(image_path):
            if dry_run:
                print(f"Would delete: {image_path}")
            else:
                if not os.path.exists(os.path.dirname(delete_path)):
                    os.makedirs(os.path.dirname(delete_path))
                os.rename(image_path, delete_path)
        else:
            print(f"Image not found: {image_path}")

def image_key_to_path(image_key):
    date = image_key.split("_")[0]
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    image_key = image_key.split(".")[0] + ".jpg"
    return os.path.join("cathal", date, image_key)

with open("to_delete.txt", "r") as f:
    images_to_delete = [line.strip() for line in f.readlines()]
    images_to_delete = [image_key_to_path(image) for image in images_to_delete]
    delete_images(images_to_delete)
