import numpy as np
import zvec
from zvec.typing.enum import LogLevel
from constants import DIR, EMBEDDING_DIR
from visual import clip_model
import os

directory = EMBEDDING_DIR

zvec.init(
    optimize_threads=1,
    query_threads=1,
)

def create_collection(device, search_model):
    schema = zvec.CollectionSchema(
        name=f"{device}_{search_model}",
        vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 768, index_param=zvec.FlatIndexParam(metric_type=zvec.MetricType.COSINE)),
        fields=[
            zvec.FieldSchema("image_path", zvec.DataType.STRING),
        ],
    )

    collection = zvec.create_and_open(
        path=f"{directory}/{device}_{search_model}", schema=schema
    )
    return collection


def open_collection(device, search_model):
    try:
        collection = zvec.open(path=f"{directory}/{device}_{search_model}")
        print(collection.path, collection.stats)
    except ValueError:
        collection = create_collection(device, search_model)
    return collection


def to_id(image_path):
    return image_path.replace("/", "_").replace("\\", "_")


def insert_embedding(collection, embedding, image_path):
    result = collection.insert(
        zvec.Doc(
            id=to_id(image_path),
            vectors={"embedding": embedding},
            fields={"image_path": image_path},
        )
    )
    if not result.ok():
        print(image_path, result.code(), result.message())

def insert_batch_embeddings(collection, embeddings, image_paths):
    for embedding, image_path in zip(embeddings, image_paths):
        doc = zvec.Doc(
            id=to_id(image_path),
            vectors={"embedding": embedding},
            fields={"image_path": image_path},
        )
        collection.insert(doc)


def search_similar_embeddings(collection, query_embedding, top_k=10):
    results = collection.query(
        zvec.VectorQuery(field_name="embedding", vector=query_embedding),
        topk=top_k,
    )
    return results


def search_similar_embeddings_by_id(collection, image_path, top_k=10):
    results = collection.query(
        vectors=zvec.VectorQuery(field_name="embedding", id=to_id(image_path)),
        topk=top_k,
    )
    return results


def delete_embedding(collection, image_path):
    collection.delete(to_id(image_path))


def check_if_exists(collection, image_path):
    doc = collection.get(to_id(image_path))
    return doc is not None


def fetch_embeddings(collection, image_paths, device_id):
    collection.flush()
    ids = [to_id(image_path) for image_path in image_paths]
    docs = collection.fetch(ids=ids)
    vectors = {id: doc.vectors["embedding"] for (id, doc) in docs.items()}

    missing = [id for id in ids if id not in docs]
    for id in missing:
        try:
            path = id.replace("_", "/", 1)
            path = f"{DIR}/{device_id}/{path}"
            vector = clip_model.encode_image(path)
            vector = vector.astype(np.float32).flatten()
            insert_embedding(collection, vector, id.replace("_", "/", 1))
            vectors[id] = vector
        except Exception:
            continue

    valid_paths = [id for id in ids if id in vectors]
    # TODO! remove

    arrays = [vectors[id] for id in valid_paths]
    arrays = [np.array(arr) for arr in arrays]

    valid_paths = [id.replace("_", "/", 1) for id in valid_paths]
    return valid_paths, np.vstack(arrays) if arrays else np.empty((0, 768), dtype=np.float32)

def backup_collection(collection):
    backup_path = f"{collection.path}_backup"
    path = collection.path
    os.system(f"cp -r {path} {backup_path}")

def restore_backup(collection):
    backup_path = f"{collection.path}_backup"
    path = collection.path
    if os.path.exists(backup_path):
        os.system(f"rm -rf {path}")
        os.system(f"mv {backup_path} {path}")
