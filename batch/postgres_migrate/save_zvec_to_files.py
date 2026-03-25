import numpy as np
import os
from pymongo import MongoClient
import zvec
from tqdm import tqdm
import pickle
from bson.binary import Binary
import glob

import secrets

import numpy as np
from scipy.stats import ortho_group


ZVEC_DIR = "/mnt/DATA/duyen/zvec"

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

# matrix = generate_secure_transformation_matrix(768)
# binary_matrix = Binary(pickle.dumps(matrix, protocol=2))

# mongo_uri = "mongodb://localhost:27017"
# database_name = "picam"
# client = MongoClient(mongo_uri)
# db = client[database_name]
# collection = db["devices"]
# collection.update_many({ "device_id": "allie" }, { "$set": { "transform_matrix": binary_matrix } }, upsert=True)

# print("Generated and stored the secure transformation matrix for 'allie' in MongoDB.")


# Transfer the old zvec database to a new one with a indexer
collection = zvec.open(f"{ZVEC_DIR}/allie_conclip")
EMBEDDING_DIR = "/mnt/MySceal/embeddings/conclip_vit_l14/"
IMAGE_DIR = "/mnt/MySceal/LifelogPicam"

images = glob.glob(f"{IMAGE_DIR}/allie/**/*.jpg", recursive=True)
pbar = tqdm(total=len(images), desc="Processing images")
for img_path in images:
    rel_path = os.path.relpath(img_path, os.path.join(IMAGE_DIR, "allie"))
    embedding_path = os.path.join(EMBEDDING_DIR, "allie_features", os.path.basename(rel_path) + ".npy")

    if not os.path.exists(embedding_path):
        try:
            embedding = collection.fetch(rel_path.replace("/", "_"))[rel_path.replace("/", "_")].vectors["embedding"]
            os.makedirs(os.path.dirname(embedding_path), exist_ok=True)
            np.save(embedding_path, np.array(embedding))
        except Exception as e:
            print(f"Error fetching embedding for {rel_path}: {e}")
            continue

    pbar.update(1)
