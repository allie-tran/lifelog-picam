import sys
from elasticsearch import Elasticsearch
from tqdm import tqdm
from pymongo import MongoClient
from zvec import zvec


# Set up ElasticSearch
es = Elasticsearch("http://localhost:9200")
interest_index = "picam"
DIM = 768

if es.indices.exists(index=interest_index):
    to_delete = input(f"Do you want to delete existing index: {interest_index}? (Y/N) ")
    if to_delete == "Y":
        print("Deleting index: " + interest_index)
        es.indices.delete(index=interest_index)

if not es.indices.exists(index=interest_index):
    es.indices.create(
        index=interest_index,
        **{
            "settings": {
                "number_of_shards": 8,
                "elastiknn": True,  # 2
                "number_of_replicas": 0,
                "sort.field": ["timestamp"],
                "sort.order": ["asc"],
            },
            "mappings": {
                "properties": {
                    "image_path": {"type": "keyword"},
                    "thumbnail": {"type": "keyword"},
                    # visual
                    # "objects": {"type": "nested"},
                    # "people": {"type": "nested"},
                    # "ocr": {"type": "nested"},
                    "objects": {"type": "text"},
                    "people": {"type": "text"},
                    "ocr": {"type": "text"},

                    # time
                    "timestamp": {"type": "long"},
                    "date": {"type": "text"},
                    "time": {"type": "date", "format": "yyyy/MM/dd HH:mm:00Z"},
                    # "utc_time": {"type": "date", "format": "yyyy/MM/dd HH:mm:00Z"},
                    "seconds_from_midnight": {"type": "long"},
                    "weekday": { "type": "keyword", "similarity": "boolean", "normalizer": "lowercase" },

                    # location
                    "location": {"type": "text"},
                    "location_name": {"type": "text"},
                    "address": {"type": "text"},
                    "region": {
                        "type": "keyword",
                        "similarity": "boolean",
                        "normalizer": "lowercase",
                    },

                    # book keeping
                    "deleted:": {"type": "boolean"},
                    "delete_time": {"type": "date", "format": "yyyy/MM/dd HH:mm:00Z"},

                    # clip vector
                    "clip_vector": {
                        "type": "elastiknn_dense_float_vector",
                        "elastiknn": {
                            "dims": DIM,
                            "model": "permutation_lsh",  # 3
                            "k": 400,  # 4
                            "repeating": True,  # 5
                        },
                    },
                }
            },
        },
    )


def to_zvec_id(image_path):
    return image_path.replace("/", "_")


def index(device):
    requests = []
    client = MongoClient("mongodb://localhost:27017/")
    collection = client["picam"]["images"]
    zvec_collection = zvec.open(f"/mnt/MySceal/embeddings/zvec/{device}_conclip")
    dates = collection.distinct("date")

    for date in tqdm(dates):
        items = collection.find({"date": date, "device": device})

        for desc in items:
            image = desc["image_path"]
            # desc["day"] = time.day
            # desc["month"] = time.month
            # desc["year"] = time.year
            # desc["day_year"] = f"{desc['day']}/{desc['year']}"
            # desc["month_year"] = desc["month"] + "/" + desc["year"]
            # desc["day_month"] = desc["day"] + "/" + desc["month"]
            # desc["minute"] = int(desc["time"][14:16])
            # desc["hour"] = int(desc["time"][11:13])
            zvec_id = to_zvec_id(image)
            vector_doc = zvec_collection.fetch(zvec_id).get("zvec_id")
            if vector_doc is None:
                print(f"Warning: No vector found for image {image}")
                continue
            vector = vector_doc.vectors["embedding"]
            desc["clip_vector"] = vector

            # Add more fields to the document
            desc["weekday"] = desc["time"].weekday()

            # Flatten nested fields
            desc["objects"] = [obj["name"] for obj in desc["objects"]]
            desc["people"] = [person["name"] for person in desc["people"]]
            desc["ocr"] = " ".join([ocr["text"] for ocr in desc["ocr"]])

            desc["gps"] = {
                "lat": desc["gps"]["latitude"],
                "lon": desc["gps"]["longitude"],
            }

            # Bulk index documents in batches to avoid memory issues
            if sys.getsizeof(requests) + sys.getsizeof(desc) > 15000:
                try:
                    es.bulk(body=requests)
                except Exception as e:
                    print(sys.getsizeof(requests), image)
                    raise (e)
                requests = []

            requests.append({"index": {"_index": interest_index, "_id": image}})
            requests.append(desc)
        if requests:
            es.bulk(body=requests)

index("allie")
index("cathal")
