import numpy as np
import pickle
import os
from app_types import Array1D
from visual import siglip_model
from tqdm.auto import tqdm

os.makedirs("files/QB_norm", exist_ok=True)

# Returns list of retrieved top k videos based on the sims matrix
def get_retrieved_images(sims, k):
    argm = np.argsort(-sims, axis=1)
    topk = argm[:, :k].reshape(-1)
    retrieved_videos = np.unique(topk)
    return retrieved_videos


# Returns list of indices to normalize from sims based on videos
def get_index_to_normalize(sims, videos):
    argm = np.argsort(-sims, axis=1)[:, 0]
    result = np.array(list(map(lambda x: x in videos, argm)))
    result = np.nonzero(result)
    return result


def load_query_features():
    if os.path.exists("files/QB_norm/query_features.npy"):
        return np.load("files/QB_norm/query_features.npy")

    # Load training queries
    print("Loading training queries...")
    queries = []
    queries = [line.strip() for line in open("files/queries.txt").readlines()]

    # Add random queries from LLM
    queries += [line.strip() for line in open("files/Lifelog_Activity_List.csv").readlines()]
    query_features = []
    for text in tqdm(queries, desc="Encoding queries"):
        query_vector = siglip_model.encode_text(text, normalize=True)
        query_features.append(query_vector)
    query_features = np.array(query_features)
    np.save(f"files/QB_norm/query_features.npy", query_features)
    return query_features

BETA = 20
k = 1000

def load_qb_norm_features(features):
    # Precompute once for all test queries
    beta = BETA

    query_features = load_query_features()
    query_features = query_features / np.linalg.norm(
        query_features, axis=1, keepdims=True
    )

    # Step 1: Precompute with training queries and dataset features
    train_test = query_features @ features.T
    train_test_exp = np.exp(train_test * beta)
    retrieved_videos = get_retrieved_images(train_test_exp, k)
    normalizing_sum = np.sum(a=train_test_exp, axis=0)

    print(f"Loaded QB-Norm features with {len(retrieved_videos)} retrieved videos.")
    return retrieved_videos, normalizing_sum


def apply_qb_norm_to_query(
    test_query_feat, features, retrieved_videos, normalizing_sum, beta
) -> Array1D[np.float32]:
    test_test = test_query_feat @ features.T  # shape: (1, I)
    test_test = test_test.reshape(1, -1)
    test_test_exp = np.exp(test_test * beta)
    test_test_normalized = test_test_exp.copy()

    index_for_normalizing = get_index_to_normalize(test_test_exp, retrieved_videos)

    # expand normalizing_sum to match the shape of test_test_exp
    # (currently (N,)) -> (N + n, 1)
    max_norm = max(normalizing_sum)
    normalizing_sum = np.concatenate(
        [normalizing_sum, np.ones(test_test_exp.shape[1] - normalizing_sum.shape[0]) * max_norm],
        axis=0,
    )

    print(test_test_exp.shape, index_for_normalizing[0].shape, normalizing_sum.shape)
    test_test_normalized[index_for_normalizing, :] = (
        test_test_exp[index_for_normalizing, :] / normalizing_sum
    )
    test_test_normalized = test_test_normalized.reshape(-1).astype(np.float32)
    return test_test_normalized
