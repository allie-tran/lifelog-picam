import zvec


def create_collection(device, search_model):
    schema = zvec.CollectionSchema(
        name=f"{device}_{search_model}",
        vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 4),
    )

    collection = zvec.create_and_open(path=f"features/{device}_{search_model}", schema=schema)
    return collection

def open_collection(device, search_model):
    collection = zvec.open(path=f"features/{device}_{search_model}")
    return collection

def insert_embedding(collection, embedding, image_path):
    collection.insert(
        zvec.Doc(id=image_path, vectors={"embedding": embedding})
    )

def insert_batch_embeddings(collection, embeddings, image_paths):
    docs = []
    for embedding, image_path in zip(embeddings, image_paths):
        doc = zvec.Doc(id=image_path, vectors={"embedding": embedding})
        collection.insert(doc)

    collection.optimize()

def search_similar_embeddings(collection, query_embedding, top_k=10):
    results = collection.query(
        query=zvec.VectorQuery(
            "embedding",
            vector=query_embedding
        ),
        top_k=top_k
    )
    return results
