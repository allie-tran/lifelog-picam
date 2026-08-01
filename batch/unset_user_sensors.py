"""
One-off: drop the dead `sensors` key from user documents.

Sensor ownership lives in the `sensor_devices` table (it is what upload auth reads); the user
document used to carry a denormalised copy that the /auth endpoints no longer write or read.
Pydantic ignores the leftover key, so this is tidying rather than a required migration.

    python3 batch/unset_user_sensors.py            # report what would change
    python3 batch/unset_user_sensors.py --apply    # unset it

MONGO_URI defaults to the backend's local connection; MONGO_DB defaults to the `picam` database.
"""

import argparse
import os

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = os.getenv("MONGO_DB", "picam")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the unset (default: dry run)")
    args = parser.parse_args()

    # Short selection timeout so a wrong URI fails in seconds instead of the 30s default.
    users = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[MONGO_DB].users
    affected = users.count_documents({"sensors": {"$exists": True}})
    print(f"{MONGO_URI} db={MONGO_DB}: {affected} of {users.count_documents({})} users carry `sensors`")

    if affected == 0:
        return
    if not args.apply:
        print("Dry run. Re-run with --apply to unset the key.")
        return

    result = users.update_many({"sensors": {"$exists": True}}, {"$unset": {"sensors": ""}})
    remaining = users.count_documents({"sensors": {"$exists": True}})
    print(f"Unset on {result.modified_count} documents; {remaining} still carry the key")


if __name__ == "__main__":
    main()
