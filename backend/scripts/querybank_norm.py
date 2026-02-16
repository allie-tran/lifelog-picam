import os

import numpy as np
from app_types import AppFeatures, Array1D
from tqdm.auto import tqdm
from constants import SEARCH_MODEL
from visual import clip_model

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
    if os.path.exists(f"files/QB_norm/{SEARCH_MODEL}/query_features.npy"):
        print(f"Loading precomputed query features for QB-Norm from files/QB_norm/{SEARCH_MODEL}/query_features.npy")
        return np.load(f"files/QB_norm/{SEARCH_MODEL}/query_features.npy")

    # Load training queries
    print("Computing query features for QB-Norm...")
    queries = []
    queries = [line.strip() for line in open("files/queries.txt").readlines()]

    # Add random queries from LLM
    queries += [
        line.strip() for line in open("files/Lifelog_Activity_List.csv").readlines()
    ]
    query_features = []
    for text in tqdm(queries, desc="Encoding queries"):
        query_vector = clip_model.encode_text(text, normalize=True)
        query_features.append(query_vector)
    query_features = np.array(query_features)
    np.save(f"files/QB_norm/{SEARCH_MODEL}/query_features.npy", query_features)
    return query_features


BETA = 20
k = 1000


def load_qb_norm_features(features: AppFeatures):
    # Precompute once for all test queries
    beta = BETA

    query_features = load_query_features()
    query_features = query_features / np.linalg.norm(
        query_features, axis=1, keepdims=True
    )

    # Step 1: Precompute with training queries and dataset features
    features_list = []
    for device in features.keys():
        feat = features[device][SEARCH_MODEL].features
        if len(feat) == 0:
            continue
        features_list.append(feat)
    merged_features = np.concatenate(features_list, axis=0)
    train_test = query_features @ merged_features.T  # shape: (M, I)
    train_test_exp = np.exp(train_test * beta)
    all_retrieved_videos = get_retrieved_images(train_test_exp, k)
    all_normalizing_sum = np.sum(a=train_test_exp, axis=0)

    print(f"Loaded QB-Norm features with retrieved videos.")
    # split per devices
    retrieved_videos = {}
    normalizing_sum = {}
    start_idx = 0
    for device_id in features.keys():
        device_features = features[device_id][SEARCH_MODEL].features
        end_idx = start_idx + device_features.shape[0]
        device_retrieved_videos = (
            all_retrieved_videos[
                (all_retrieved_videos >= start_idx) & (all_retrieved_videos < end_idx)
            ]
            - start_idx
        )
        device_normalizing_sum = all_normalizing_sum[start_idx:end_idx]
        retrieved_videos[device_id] = device_retrieved_videos
        normalizing_sum[device_id] = device_normalizing_sum
        start_idx = end_idx

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
    assert test_test_exp.shape[1] >= normalizing_sum.shape[0], f"{test_test_exp.shape[1]} needs to be >= {normalizing_sum.shape[0]}"

    normalizing_sum = np.concatenate(
        [
            normalizing_sum,
            np.ones(test_test_exp.shape[1] - normalizing_sum.shape[0]) * max_norm,
        ],
        axis=0,
    )

    print(test_test_exp.shape, index_for_normalizing[0].shape, normalizing_sum.shape)
    test_test_normalized[index_for_normalizing, :] = (
        test_test_exp[index_for_normalizing, :] / normalizing_sum
    )
    test_test_normalized = test_test_normalized.reshape(-1).astype(np.float32)
    return test_test_normalized
