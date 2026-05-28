
from typing import Any, Literal
from fastapi import Depends, FastAPI, Query
from sqlalchemy.orm import Session
from datetime import datetime

from sqlalchemy.sql import func, select

from database import get_session
from database.models import HeartRateData as HeartRateTable, MagnetometerData as MagnetometerTable, AccelerometerData as AccelerometerTable, GyroscopeData as GyroscopeTable, PPGData as PPGTable, PPIData as PPITable
from dependencies import CamelCaseModel


app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/list-biometrics-sensors")
def list_sensors():
    return ["1ABA333D"]

class MeasurementData(CamelCaseModel):
    time_stamp: int
    value: float

class NestedMeasurementData(CamelCaseModel):
    time_stamp: int
    values: dict[str, float | None]

class LogResponse(CamelCaseModel):
    keys: list[str]
    logs: dict[str, list[NestedMeasurementData]]

old_epoch_year = datetime.timestamp(datetime(1970, 1, 1))
epoch_year = datetime.timestamp(datetime(2000, 1, 1))
timedelta_seconds = epoch_year - old_epoch_year

def calculate_magnitude(x, y, z):
    return round((x**2 + y**2 + z**2) ** 0.5, 4)

def get_attr(obj, attr):
    if attr == "magnitude":
        return calculate_magnitude(getattr(obj, "x"), getattr(obj, "y"), getattr(obj, "z"))
    if "." in attr:
        name, index = attr.split(".")
        return getattr(obj, name)[int(index)]
    else:
        return getattr(obj, attr)



@app.get("/logs/{sensor}")
def get_sensor_logs(
    sensor: Literal["all", "heartrate", "magnetometer", "accelerometer", "gyroscope"],
    date: str,
    device_id: str,
    sample_rate: int = Query(default=50, description="Return every N-th row. Higher = fewer points."),
    session: Session = Depends(get_session)
) -> LogResponse:

    date_value = datetime.strptime(date, "%Y-%m-%d")
    start_timestamp = date_value.timestamp() - timedelta_seconds
    end_timestamp = start_timestamp + 86400

    start_ns = int(start_timestamp * 1_000_000_000)
    end_ns = int(end_timestamp * 1_000_000_000)

    # check if there is **any** heartrate data for the given date and device_id
    hr_exists = session.query(HeartRateTable).filter(
        HeartRateTable.device_id == device_id,
        HeartRateTable.time_stamp >= start_ns,
        HeartRateTable.time_stamp < end_ns
    ).first()
    if not hr_exists:
        return LogResponse(keys=[], logs={})

    # 1. Define the full registry of targets
    sensor_registry = {
        # "heartrate": (HeartRateTable, ["hr"]),
        "magnetometer": (MagnetometerTable, ["x", "y", "z", "magnitude"]),
        "accelerometer": (AccelerometerTable, ["x", "y", "z", "magnitude"]),
        "gyroscope": (GyroscopeTable, ["x", "y", "z", "magnitude"]),
        "ppg": (PPGTable, ["channel_samples.0", "channel_samples.1", "channel_samples.2", "channel_samples.3"]),
        "heartrate": (PPITable, ["hr", "ppi"])
    }

    targets = [(name, table, keys) for name, (table, keys) in sensor_registry.items()]

    all_res = {}

    for name, table, keys in targets:
        # 3. Create a window function to number the rows sequentially
        row_num_col = func.row_number().over(order_by=table.time_stamp).label("row_num")

        # 4. Core query wrapping our filter constraints
        base_stmt = (
            select(table, row_num_col)
            .where(
                table.device_id == device_id,
                table.time_stamp >= start_ns,
                table.time_stamp <= end_ns
            )
        ).subquery()

        # 5. Filter inside Postgres using Modulo (%) to sample every Nth row
        if name in ["heartrate", "ppi"]:
            # For heart rate, we want to sample every row
            sampled_stmt = select(base_stmt)
        else:
            sampled_stmt = select(base_stmt).where(base_stmt.c.row_num % sample_rate == 0)

        res = session.execute(sampled_stmt).all()

        # Define a strict 60-second interval (5,000,000,000 nanoseconds)
        BUCKET_SIZE_NS = 30 * 1_000_000_000 if name not in ["heartrate", "ppi"] else 1_000_000_000

        # 6. Group existing rows into their respective 5s buckets using integer division
        # This runs in O(M) time where M is just the small dataset returned by Postgres
        bucketed_data = {}
        for row in res:
            # Snap the row's timestamp down to the nearest 5-second bucket start
            bucket_id = (row.time_stamp // BUCKET_SIZE_NS) * BUCKET_SIZE_NS
            bucketed_data[bucket_id] = row

        # 7. Generate the uniform timeline from start to end by steps of 5 seconds
        all_res[name] = []

        this_start_ns = max(start_ns, min(bucketed_data.keys()) if bucketed_data else start_ns)
        this_end_ns = min(end_ns, max(bucketed_data.keys()) + BUCKET_SIZE_NS if bucketed_data else end_ns)

        for current_ts_ns in range(this_start_ns, this_end_ns, BUCKET_SIZE_NS):
            frontend_timestamp = int(current_ts_ns // 1_000_000_000 + timedelta_seconds)

            # O(1) instant hash lookup
            if current_ts_ns in bucketed_data:
                row = bucketed_data[current_ts_ns]
                data: dict[str, Any] = {k: get_attr(row, k) for k in keys}
                all_res[name].append(NestedMeasurementData(
                    time_stamp=frontend_timestamp,
                    values=data
                ))
            else:
                # Drop the null object for gaps
                all_res[name].append(NestedMeasurementData(
                    time_stamp=frontend_timestamp,
                    values={k: None for k in keys}
                ))

    return LogResponse(keys=list(all_res.keys()), logs=all_res)

