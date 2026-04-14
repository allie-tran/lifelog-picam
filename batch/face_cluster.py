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
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session, selectinload
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
    with Session(engine) as session:
        stmt = select(Image).options(selectinload(Image.people)).where(Image.device == DEVICE)
        images = session.execute(stmt).scalars().all()

    image_embeddings = []
    person_ids = []
    for img in tqdm(images, desc="Loading embeddings"):
        if img.people:
            for person in img.people:
                if person.embedding is not None and person.confidence is not None and person.confidence >= 0.5:
                    image_embeddings.append(person.embedding)
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
    cluster_to_id = {}
    with Session(engine) as session:
        for i, centroid in enumerate(centroids):
            name = generate_name()
            cluster = {
                "center_embedding": centroid.tolist(),
                "cluster_label": name
            }
            stmt = insert(PeopleCluster).values(**cluster).returning(PeopleCluster.id)
            cluster_id = session.execute(stmt).scalar_one()
            cluster_to_id[i] = cluster_id
        session.commit()
        print(f"Saved {len(centroids)} cluster centroids to database.")

    print("Visualizing clusters...")
    visualize_clusters(embeddings, cluster_labels)

    print("Updating database with cluster labels...")
    cluster_to_name = {}
    to_updates = []

    total = len(person_ids)
    update_count = 0
    with Session(engine) as session:
        for person_id, cluster_label in zip(person_ids, cluster_labels):
            stmt = select(ImagePerson).where(ImagePerson.id == person_id)
            person = session.execute(stmt).scalar_one()
            if cluster_label not in cluster_to_name:
                cluster_to_name[cluster_label] = generate_name()

            person.label = cluster_to_name[cluster_label]
            person.cluster_id = cluster_to_id[cluster_label]
            to_updates.append(person)

            if len(to_updates) >= 100:
                session.bulk_save_objects(to_updates)
                session.commit()
                to_updates = []
                update_count += 100
                print(f"Updated {update_count}/{total} people...")

        if to_updates:
            session.bulk_save_objects(to_updates)
            session.commit()
            print(f"Updated {update_count + len(to_updates)}/{total} people...")

if __name__ == "__main__":
    main()
