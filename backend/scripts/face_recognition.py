from typing import List
from fastapi import UploadFile
import zvec
from auth.types import Device
from constants import EMBEDDING_DIR
from database.types import ImageRecord
import cv2
import numpy as np
from datetime import datetime

from scripts.object_detection import get_face_data_from_person_crop
from scripts.utils import to_base64


directory = EMBEDDING_DIR


def create_zvec_collection(device):
    collection_schema = zvec.CollectionSchema(
        f"{device}_faces",
        vectors=[
            zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 512),
        ],
        fields=[
            zvec.FieldSchema("timestamp", zvec.DataType.FLOAT, index_param=zvec.InvertIndexParam(enable_range_optimization=True)),
            zvec.FieldSchema("image_path", zvec.DataType.STRING),
            zvec.FieldSchema("bbox", zvec.DataType.STRING),
            zvec.FieldSchema("whitelist", zvec.DataType.BOOL, index_param=zvec.InvertIndexParam()),
        ],
    )

    name = f"{directory}/{device}_faces"
    zvec_collection = zvec.create_and_open(name, collection_schema)
    print(f"Created ZVec collection for device {device} at {name}")

    recent = datetime.now().timestamp() - 24 * 3600  # only index the last hour of data
    agg = ImageRecord.aggregate(
        [
            {
                "$match": {
                    "people": {"$exists": True, "$ne": []},
                    "device": device,
                    "timestamp": {"$gte": recent * 1000},
                }
            },
            {"$unwind": "$people"},
            {
                "$project": {
                    "embedding": "$people.embedding",
                    "image_path": 1,
                    "bbox": "$people.bbox",
                    "label": "$people.label",
                    "timestamp": 1,
                }
            },
        ]
    )

    # Insert all embeddings into Zvec
    for doc in agg:
        zvec_doc = zvec.Doc(
            id=str(doc.id),
            vectors={"embedding": doc.embedding},
            fields={
                "image_path": doc.image_path,
                "bbox": ",".join(map(str, doc.bbox)),
                "whitelist": doc.label != "redacted face" and doc.label != "face",
                "timestamp": doc.timestamp,
            },
        )
        zvec_collection.insert(zvec_doc)
    doc_count = zvec_collection.stats.doc_count
    print(f"Inserted {doc_count} face embeddings into ZVec collection for device {device}")
    return zvec_collection


def open_face_collection(device):
    try:
        collection = zvec.open(path=f"{directory}/{device}_faces")
        print(collection.path, collection.stats)
        return collection
    except ValueError:
        return create_zvec_collection(device)


def index_face_embeddings(
    zvec_collection: zvec.Collection, image_record: ImageRecord
):
    for i, person in enumerate(image_record.people):
        embedding = person.embedding
        bbox = person.bbox

        zvec_doc = zvec.Doc(
            id=f"{image_record.id}_{i}",
            vectors={"embedding": embedding},
            fields={
                "timestamp": image_record.timestamp,
                "image_path": image_record.image_path,
                "bbox": ",".join(map(str, bbox)),
                "whitelist": person.label != "redacted face" and person.label != "face",
            },
        )
        zvec_collection.insert(zvec_doc)


def delete_old_faces(zvec_collection: zvec.Collection, cutoff_timestamp: float):
    before = zvec_collection.stats.doc_count
    zvec_collection.delete_by_filter(filter=f'timestamp < {cutoff_timestamp} AND whitelist = false')
    after = zvec_collection.stats.doc_count
    print(f"Deleted {before - after} old face embeddings")


def search_face_embedding(
    zvec_collection: zvec.Collection, embedding: list[float], top_k: int = 5
):
    results = zvec_collection.query(
        vectors=zvec.VectorQuery(field_name="embedding", vector=embedding),
        topk=top_k,
    )
    return results


def search_for_faces(zvec_collection: zvec.Collection, files: List[UploadFile]):
    results = []
    for file in files:
        cv_image = cv2.imdecode(
            np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR
        )
        faces = get_face_data_from_person_crop(cv_image)
        print(f"Detected {len(faces)} faces in the uploaded image.")
        if not faces:
            continue
        face = faces[0].embedding
        results += search_face_embedding(zvec_collection, face, top_k=5)
    return [doc.fields["image_path"] for doc in results]


def add_face_to_whitelist(device: str, name: str, files: List[UploadFile]):
    cropped = []
    embeddings = []
    for file in files:
        cv_image = cv2.imdecode(
            np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR
        )
        if cv_image is None:
            print("Error: Unable to read the uploaded image.")
            continue
        faces = get_face_data_from_person_crop(cv_image)
        if not faces:
            continue
        face = faces[0].embedding
        bbox = faces[0].bbox
        # expand the box by 20% in each direction
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        x1 = max(0, x1 - int(w * 0.2))
        y1 = max(0, y1 - int(h * 0.2))
        x2 = min(cv_image.shape[1], x2 + int(w * 0.2))
        y2 = min(cv_image.shape[0], y2 + int(h * 0.2))
        cropped_image = cv_image[y1:y2, x1:x2]
        image_bytes = cv2.imencode(".jpg", cropped_image)[1].tobytes()

        embeddings.append(face)
        cropped.append(to_base64(image_bytes))

    Device.update_one(
        {"device_id": device},
        {
            "$addToSet": {
                "whitelist": {
                    "name": name,
                    "embeddings": embeddings,
                    "cropped": cropped,
                }
            }
        },
    )
