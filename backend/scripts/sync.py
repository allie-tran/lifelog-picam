from pymongo import MongoClient
import glob
import os
import time
import zvec
from constants import DIR, THUMBNAIL_DIR
from pipelines.all import index_to_mongo, create_thumbnail, encode_image
from tqdm import tqdm

client = MongoClient("mongodb://localhost:27017/")
db = client["picam"]
mongo_collection = db["images"]

def to_id(image_path):
    return image_path.replace("/", "_")


def sync_images(device: str, zvec_collection: zvec.Collection):
    def in_zvec(image_path):
        docs = zvec_collection.fetch(to_id(image_path))
        if docs:
            return True
        return False

    print(f"Syncing images for device: {device}")
    # 1. Collect all the "databases"
    raw_images = glob.glob(f"{DIR}/{device}/**/*.jpg", recursive=True)
    raw_images = set(raw_images)
    raw_images = set(image.split(device + "/")[1] for image in raw_images)
    print(f"Total raw images: {len(raw_images)}")

    mongo_images = mongo_collection.aggregate([
        {"$match": {"device": device}},
        {"$group": {"_id": "$image_path"}},
    ])
    mongo_image_paths = set(image["_id"] for image in mongo_images)
    print(f"MongoDB: {len(mongo_image_paths)} images")

    thumbnail_images = glob.glob(f"{THUMBNAIL_DIR}/{device}/**/*.webp", recursive=True)
    thumbnail_images = set(thumbnail_images)
    thumbnail_images = set(image.split(device + "/")[1] for image in thumbnail_images)
    thumbnail_images = set(image.replace(".webp", ".jpg") for image in thumbnail_images)
    print(f"Total thumbnail images: {len(thumbnail_images)}")

    # 2. Base on raw_images, find the missing ones in mongo and zvec
    print("-" * 30)

    missing_in_mongo = raw_images - mongo_image_paths
    print(f"Missing in MongoDB: {len(missing_in_mongo)}")
    missing_in_thumbnail = raw_images - thumbnail_images
    print(f"Missing in Thumbnail: {len(missing_in_thumbnail)}")
    start = time.time()
    missing_in_zvec = raw_images - set(image for image in raw_images if in_zvec(image))
    print(f"Checked ZVec in {time.time() - start:.2f} seconds")
    print(f"Missing in ZVec: {len(missing_in_zvec)}")

    all_missing = missing_in_mongo | missing_in_thumbnail | missing_in_zvec
    for image in all_missing:
        # Try opening the image to see if it's corrupted
        image_path = f"{DIR}/{device}/{image}"
        try:
            Image.open(image_path).verify()
        except Exception as e:
            print(f"Corrupted image found and removed: {image_path}")
            os.remove(image_path)
            if image in missing_in_mongo:
                missing_in_mongo.remove(image)
            if image in missing_in_thumbnail:
                missing_in_thumbnail.remove(image)
            if image in missing_in_zvec:
                missing_in_zvec.remove(image)

    for image in tqdm(missing_in_mongo):
        index_to_mongo(device, image)

    for image in tqdm(missing_in_thumbnail):
        create_thumbnail(device, image)

    for image in tqdm(missing_in_zvec):
        encode_image(device, image, zvec_collection)

    # 3. Base on raw_images, find the extra ones in mongo and zvec
    print("-" * 30)
    extra_in_mongo = mongo_image_paths - raw_images
    print(f"Extra in MongoDB: {len(extra_in_mongo)}")
    for image in tqdm(extra_in_mongo):
        mongo_collection.delete_many({"device": device, "image_path": image})

    extra_in_thumbnail = thumbnail_images - raw_images
    print(f"Extra in Thumbnail: {len(extra_in_thumbnail)}")
    for image in tqdm(extra_in_thumbnail):
        thumbnail_path = f"{THUMBNAIL_DIR}/{device}/{image.replace('.jpg', '.webp')}"
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

    start = time.time()
    extra_in_zvec = set(image for image in mongo_image_paths if in_zvec(image)) - raw_images
    print(f"Checked ZVec in {time.time() - start:.2f} seconds")
    print(f"Extra in ZVec: {len(extra_in_zvec)}")
    for image in tqdm(extra_in_zvec):
        zvec_collection.delete(to_id(image))

    zvec_collection.optimize()
    print("Sync complete!")











