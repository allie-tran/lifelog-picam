import numpy as np
from pymongo import MongoClient
import zvec
from tqdm import tqdm
import pickle
from bson.binary import Binary

import secrets

import numpy as np
from scipy.stats import ortho_group


ZVEC_DIR = "/mnt/DATA/duyen/zvec"
Image_DIR = "/mnt/MySceal/LifelogPicam"

def generate_secure_transformation_matrix(dimension):
    """
    Generates a cryptographically secure orthonormal matrix.
    Uses 'secrets' to generate a seed for the orthogonal group generation.
    """
    # Generate a high-entropy 32-bit integer seed
    # We use 32-bit because most underlying PRNG seeds for ortho_group
    # expect a standard integer range.
    secure_seed = secrets.randbits(32)

    # Generate the matrix using the Haar distribution
    # We provide the secure seed to the Generator
    rng = np.random.default_rng(secure_seed)
    matrix = ortho_group.rvs(dim=dimension, random_state=rng)

    return matrix


def apply_transformation(embedding, transform_matrix):
    """
    Applies the transformation M to a face embedding vector.

    Args:
        embedding: A 1D numpy array (the face embedding)
        transform_matrix: The orthonormal matrix M
    Returns:
        The transformed (rotated) embedding
    """
    # Ensure the embedding is treated as a column vector for the dot product
    return np.dot(transform_matrix, embedding)

matrix = generate_secure_transformation_matrix(768)
binary_matrix = Binary(pickle.dumps(matrix, protocol=2))

mongo_uri = "mongodb://localhost:27017"
database_name = "picam"
client = MongoClient(mongo_uri)
db = client[database_name]
collection = db["devices"]
collection.update_many({ "device_id": "allie" }, { "$set": { "transform_matrix": binary_matrix } }, upsert=True)

print("Generated and stored the secure transformation matrix for 'allie' in MongoDB.")


# Transfer the old zvec database to a new one with a indexer
for device in ["allie"]:
    schema = zvec.CollectionSchema(
        name=f"{device}_conclip",
        fields=[zvec.FieldSchema("image_path", zvec.DataType.STRING)],
        vectors=[
            zvec.VectorSchema(
                "embedding",
                zvec.DataType.VECTOR_FP32,
                768,
                index_param=zvec.FlatIndexParam(metric_type=zvec.MetricType.COSINE),
            ),
        ],
    )

    new = zvec.create_and_open(f"{ZVEC_DIR}/{device}_conclip", schema)
    # new = zvec.open(f"{ZVEC_DIR}/{device}_conclip")

    path = "../backend/features/allie/conclip_0.features.npz"
    data = np.load(path)
    feats = data["features"]
    image_paths = data["image_paths"]

    pbar = tqdm(total=len(image_paths))
    for path, feat in zip(image_paths, feats):
        feat = apply_transformation(feat, matrix)
        pbar.update(1)
        new_doc = zvec.Doc(
            id=path.replace("/", "_"),
            vectors={"embedding": feat.astype(np.float32)},
            fields={"image_path": path},
        )
        new.insert(new_doc)
