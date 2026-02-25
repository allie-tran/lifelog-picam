
import numpy as np

import secrets
import pickle

import numpy as np
from pymongo.client_session import Binary
from scipy.stats import ortho_group

from auth.types import Device


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


def generate_and_store_matrix(device: str, dimension: int):
    matrix = generate_secure_transformation_matrix(dimension)
    binary_matrix = Binary(pickle.dumps(matrix, protocol=2))
    Device.update_one(
        {"device_id": device},
        {"$set": {"transform_matrix": binary_matrix}},
        upsert=True,
    )

def get_matrix(device: str):
    device_record = Device.find_one({"device_id": device})
    if device_record and device_record.transform_matrix:
        return pickle.loads(device_record.transform_matrix)
    else:
        raise ValueError(f"No transformation matrix found for device {device}. Please generate one first.")
        return None
