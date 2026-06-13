import asyncio
import json
from typing import Any
import aiomqtt
from datetime import datetime
import os
from rich import print as rprint
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from integrations.biometrics.types import data_type_mapping
from database.models import Device, SensorDevice, db_type_mapping

# 1. Paste the exact settings from your screenshot
MQTT_TOPIC = "#"

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))  # Default TLS port for MQTT

mqtt_client: aiomqtt.Client | None = None

PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")
engine = create_engine(PG_URI)

old_epoch_year = datetime.timestamp(datetime(1970, 1, 1))
epoch_year = datetime.timestamp(datetime(2000, 1, 1))
timedelta_seconds = epoch_year - old_epoch_year

def parse_data(topic: str, payload_str: str):
    with Session(engine) as session:
        user_id, data_type, device_id = topic.split("/")
        payload: Any = json.loads(str(payload_str))
        data_class = data_type_mapping.get(data_type)
        assert data_class is not None, f"Unknown data type: {data_type}"

        # # Get device id in DB
        # device_obj = session.execute(
        #     select(SensorDevice).where(SensorDevice.device_id == device_id)
        # ).scalar_one_or_none()

        # if not device_obj:
        #     print(f"Device {device_id} not registered in DB. Please register using:")
        #     rprint(f"""curl <URL>/auth/add-sensor?device_id={device_id}&device_nickname=<nickname>&sensor_type=biometrics&associated_username=username -X PUT""")
        #     return

        # user = device_obj.associated_user
        # user_id = session.execute(
        #     select(Device.device_id).where(Device.id == user)
        # ).scalar_one_or_none()

        # if not user_id:
        #     print(f"Device {device_id} is not associated with any user. Please associate using:")
        #     rprint(f"""curl <URL>/auth/add-sensor?device_id={device_id}&device_nickname=<nickname>&sensor_type=biometrics&associated_username=username -X PUT""")
        #     return
        user = session.execute(
            select(Device).where(Device.device_id == user_id)
        ).scalar_one_or_none()
        if user is None:
            print(f"User {user_id} not found in DB. Please register using:")
            rprint(f"""curl <URL>/auth/register?device_id={device_id}&username={user_id} -X PUT""")
            return

        try:
            phone_timestamp = payload["phoneTimestamp"] # in milliseconds, from 1970-01-01
            # change epoch to 2000-01-01
            phone_timestamp = phone_timestamp - timedelta_seconds * 1000
            # convert to nanoseconds for DB storage
            phone_timestamp = phone_timestamp * 1_000_000 # convert to nanoseconds

            # min timestamp
            items = payload["data"]
            min_timestamp = min(item.get("timeStamp", phone_timestamp) for item in items)

            # add phone's timestamp if not present
            items = [
                {**item, "timeStamp": item.get("timeStamp", phone_timestamp) - min_timestamp + phone_timestamp, "deviceId": user_id } for item in items # convert phone timestamp from ms to ns if timeStamp is not present
            ]

            items = [data_class(**item) for item in items]
            if data_type == "LOG":
                print(f"Received LOG data for device {device_id}, for user {user_id}, with {len(items)} entries.")
                rprint(items)
            else:
                db_class = db_type_mapping.get(data_type)
                assert db_class is not None, f"Unknown data type for DB: {data_type}"

                stmt = insert(db_class).values([item.model_dump(by_alias=False) for item in items])
                session.execute(stmt)
        except Exception as e:
            rprint(f"Error parsing message: {e}")

        session.commit()

async def mqtt_consumer():
    """Background task to consume HiveMQ Cloud messages."""
    global mqtt_client
    while True:
        try:
            print(f"Connecting to HiveMQ Cloud at {MQTT_BROKER}...")
            async with aiomqtt.Client(
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                # username=MQTT_USERNAME,
                # password=MQTT_PASSWORD,
            ) as client:
                mqtt_client = client
                print("Successfully connected to HiveMQ Cloud!")

                await client.subscribe(MQTT_TOPIC)
                print(f"Subscribed to topic: {MQTT_TOPIC}")

                async for message in client.messages:
                    payload = message.payload.decode()
                    parse_data(str(message.topic), payload)

        except asyncio.CancelledError:
            raise
        except aiomqtt.MqttError as error:
            print(f"MQTT Error: {error}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
