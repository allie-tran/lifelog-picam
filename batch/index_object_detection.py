# You can install it using pip:
# pip install ultralytics

import json
import os
from tqdm import tqdm

from pymongo import MongoClient


if __name__ == "__main__":
    client = MongoClient("mongodb://localhost:27017/")
    db = client["picam"]
    collection = db["images"]
    device = "cathal"
    finished = os.listdir("yolo_outputs/output")
    indexed = collection.aggregate(
        [
            {
                "$match": {
                    "device": device,
                    "processed.yolo": True,
                    "processed.insightface": True,
                }
            },
            {"$project": {"_id": 0, "image_path": 1}},
        ]
    )
    indexed = set([item["image_path"].split("/")[-1].split(".")[0] for item in indexed])
    finished = set([image.split(".")[0] for image in finished])
    print(f"Total finished: {len(finished)}, already indexed: {len(indexed)}")
    finished = finished - indexed
    print(f"Total to index: {len(finished)}")
    ops = []
    total = len(finished)
    ok = 0
    for image in tqdm(finished):
        try:
            data = json.load(open(f"yolo_outputs/output/{image}.jpg.json"))
            data["image_path"] = f"{device}/{image}.jpg"
            collection.update_one(
                {"image_path": data["image_path"], "device": device},
                {
                    "$set": {
                        "objects": data["objects"],
                        "people": data["people"],
                        "processed.yolo": True,
                        "processed.insightface": True,
                    }
                },
            )
        except Exception as e:
            print(f"Error processing {image}: {e}")

    if len(ops) > 0:
        collection.bulk_write(ops)
