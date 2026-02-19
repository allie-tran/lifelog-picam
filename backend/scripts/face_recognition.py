from fastapi import UploadFile
import zvec
from auth.types import Device
from database.types import ImageRecord
import cv2
import numpy as np

from scripts.object_detection import get_face_data_from_person_crop

directory = "/mnt/ssd0/embeddings/zvec"

def create_zvec_collection(device):
    collection_schema = zvec.CollectionSchema(
        "faces",
        vectors=[
            zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 512),
        ],
        fields=[
            zvec.FieldSchema("image_path", zvec.DataType.STRING),
            zvec.FieldSchema("device", zvec.DataType.STRING),
            zvec.FieldSchema("bbox", zvec.DataType.STRING),
        ],
    )

    name = f"{directory}/{device}_faces"
    zvec_collection = zvec.create_and_open(name, collection_schema)

    agg = ImageRecord.aggregate(
        [
            {"$match": {"people": {"$exists": True, "$ne": []}, "device": device}},
            {"$unwind": "$people"},
            {
                "$project": {
                    "embedding": "$people.embedding",
                    "image_path": 1,
                    "device": 1,
                    "bbox": "$people.bbox",
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
                "device": doc.device,
                "bbox": ",".join(map(str, doc.bbox)),
            },
        )
        zvec_collection.insert(zvec_doc)
    zvec_collection.optimize()
    return zvec_collection


def open_face_collection(device):
    try:
        return zvec.open(path=f"{directory}/{device}_faces")
    except ValueError:
        return create_zvec_collection(device)


def index_face_embeddings(
    zvec_collection: zvec.Collection, device: str, image_record: ImageRecord
):
    for person in image_record.people:
        embedding = person.embedding
        bbox = person.bbox

        zvec_doc = zvec.Doc(
            id=str(image_record._id),
            vectors={"embedding": embedding},
            fields={
                "image_path": image_record.image_path,
                "device": device,
                "bbox": ",".join(map(str, bbox)),
            },
        )
        zvec_collection.insert(zvec_doc)


def search_face_embedding(
    zvec_collection: zvec.Collection, embedding: list[float], top_k: int = 5
):
    results = zvec_collection.query(
        vectors=zvec.VectorQuery(field_name="embedding", vector=embedding),
        topk=top_k,
    )
    return results


def search_for_faces(
    zvec_collection: zvec.Collection, file: UploadFile
):
    cv_image = cv2.imdecode(np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR)
    faces = get_face_data_from_person_crop(cv_image)
    print(f"Detected {len(faces)} faces in the uploaded image.")
    if not faces:
        raise ValueError("No faces detected in the uploaded image.")
    face = faces[0].embedding
    results = search_face_embedding(zvec_collection, face, top_k=10)
    print(results)
    return [doc.fields["image_path"] for doc in results]


def add_face_to_whitelist(device: str, name: str, file: UploadFile):
    cv_image = cv2.imdecode(np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR)
    faces = get_face_data_from_person_crop(cv_image)

    for face in faces:
        embedding = face.embedding
        Device.update_one(
            {"device_id": device},
            {
                "$addToSet": {
                    "whitelist": {
                        "name": name,
                        "embedding": embedding,
                    }
                }
            },
        )
