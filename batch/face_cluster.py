import json
import os
import random
import secrets
from datetime import datetime

import numpy as np
import piexif
from dotenv import load_dotenv
from PIL import Image as PILImage
from scipy.stats import ortho_group
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.orm import Session, selectinload
from collections import defaultdict
from tqdm import tqdm
import glob
from names_generator import generate_name

# Import your models from models.py
from models import Image, ImagePerson, PeopleCluster

load_dotenv()

seed = 42
random.seed(seed)
np.random.seed(seed)

# --- Configuration ---
PG_URI = os.getenv("PG_URI")  # Your PostgreSQL connection string

assert PG_URI, "PostgreSQL URI must be set in .env"
engine = create_engine(PG_URI)

DEVICE = "cathal"

def load_embeddings():
    image_embeddings = []
    person_ids = []
    with Session(engine) as session:
        stmt = select(ImagePerson).where(ImagePerson.confidence >= 0.5).where(ImagePerson.embedding != None)
        people = session.execute(stmt).scalars().all()
        for person in tqdm(people, desc="Loading embeddings"):
            embedding = person.embedding
            if embedding is not None:
                image_embeddings.append(embedding)
                person_ids.append(person.id)

    return np.array(image_embeddings), person_ids

def cluster_embeddings(embeddings, n_clusters=10):
    from sklearn.cluster import KMeans

    kmeans = KMeans(n_clusters=n_clusters, random_state=seed)
    cluster_labels = kmeans.fit_predict(embeddings)
    centroids = kmeans.cluster_centers_
    return centroids, cluster_labels

def visualize_clusters(embeddings, cluster_labels):
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA
    import random

    pca = PCA(n_components=2, random_state=seed)
    ids = list(range(len(embeddings)))
    sampled_ids = random.sample(ids, min(1000, len(ids)))  # Sample for visualization
    embeddings = embeddings[sampled_ids]
    cluster_labels = cluster_labels[sampled_ids]
    reduced_embeddings = pca.fit_transform(embeddings)

    plt.figure(figsize=(10, 7))
    scatter = plt.scatter(reduced_embeddings[:, 0], reduced_embeddings[:, 1], c=cluster_labels, cmap='tab10')
    plt.legend(*scatter.legend_elements(), title="Clusters")
    plt.title("PCA of Face Embeddings with Cluster Labels")
    plt.xlabel("PCA Component 1")
    plt.ylabel("PCA Component 2")

    # Save the plot to a file
    plt.savefig("cluster_visualization.png")

def main():
    print("Loading embeddings...")
    embeddings, person_ids = load_embeddings()

    print("Clustering embeddings...")
    centroids, cluster_labels = cluster_embeddings(embeddings, n_clusters=20)

    print("Saving cluster centroids to database...")
    cluster_label_to_cluster_id = {}
    with Session(engine) as session:
        for i, centroid in enumerate(centroids):
            name = generate_name()
            name = name.replace("_", " ").title()
            cluster = {
                "center_embedding": centroid.tolist(),
                "cluster_label": name
            }
            stmt = insert(PeopleCluster).values(**cluster).returning(PeopleCluster.id)
            cluster_sql_id = session.execute(stmt).scalar_one()
            cluster_label_to_cluster_id[i] = cluster_sql_id
        session.commit()
        print(f"Saved {len(centroids)} cluster centroids to database.")

    print("Updating database with cluster labels...")
    cluster_to_person_ids = defaultdict(list)
    for person_id, cluster_label in zip(person_ids, cluster_labels):
        cluster_to_person_ids[cluster_label].append(person_id)

    with Session(engine) as session:
        batch_size = 1000
        for cluster_label, person_ids in cluster_to_person_ids.items():
            cluster_sql_id = cluster_label_to_cluster_id[cluster_label]
            name = generate_name()
            name = name.replace("_", " ").title()
            print(f"Updating cluster {cluster_sql_id} ({name}) with {len(person_ids)} people...")
            for i in range(0, len(person_ids), batch_size):
                batch_ids = person_ids[i:i+batch_size]
                stmt = (
                    update(ImagePerson)
                    .where(ImagePerson.id.in_(batch_ids))
                    .values(cluster_id=cluster_sql_id, label=name)
                )
                session.execute(stmt)
                print(f"Updated {min(i + batch_size, len(person_ids))}/{len(person_ids)} people in cluster {cluster_sql_id}...")
            session.commit()

if __name__ == "__main__":
    main()
