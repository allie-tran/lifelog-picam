import zvec
import numpy as np

directory = "/mnt/ssd0/embeddings/zvec"


def create_collection(device, search_model):
    schema = zvec.CollectionSchema(
        name=f"{device}_{search_model}",
        vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 768),
        fields=[
            zvec.FieldSchema("image_path", zvec.DataType.STRING),
        ],
    )

    collection = zvec.create_and_open(
        path=f"{directory}/{device}_{search_model}", schema=schema
    )
    return collection


def open_collection(device, search_model):
    collection = zvec.open(path=f"{directory}/{device}_{search_model}")
    return collection


def to_id(image_path):
    return image_path.replace("/", "_").replace("\\", "_")


def insert_embedding(collection, embedding, image_path):
    collection.insert(
        zvec.Doc(
            id=to_id(image_path),
            vectors={"embedding": embedding},
            fields={"image_path": image_path},
        )
    )


def insert_batch_embeddings(collection, embeddings, image_paths):
    for embedding, image_path in zip(embeddings, image_paths):
        doc = zvec.Doc(
            id=to_id(image_path),
            vectors={"embedding": embedding},
            fields={"image_path": image_path},
        )
        collection.insert(doc)

    collection.optimize()


def search_similar_embeddings(collection, query_embedding, top_k=10):
    results = collection.query(
        vectors=zvec.VectorQuery(field_name="embedding", vector=query_embedding),
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


def fetch_embeddings(collection, image_paths):
    ids = [to_id(image_path) for image_path in image_paths]
    docs = collection.fetch(ids=ids)
    arrays = [docs[id].vectors["embedding"] for id in ids if id in docs]
    arrays = [np.array(arr) for arr in arrays]
    return np.vstack(arrays) if arrays else np.empty((0, 768), dtype=np.float32)
