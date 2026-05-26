import asyncio
import json
import aiomqtt
from datetime import datetime
import os
from rich import print as rprint
from biometrics.types import data_type_mapping, MQTTMessage

# 1. Paste the exact settings from your screenshot
MQTT_TOPIC = "polar/#"

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))  # Default TLS port for MQTT

mqtt_client: aiomqtt.Client | None = None


def parse_data(topic: str, payload: str):
    _, data_type, device_id = topic.split("/")
    payload = json.loads(str(payload))
    data_class = data_type_mapping.get(data_type)
    assert data_class is not None, f"Unknown data type: {data_type}"
    try:
        items = payload["data"]
        # add phone's timestamp if not present
        items = [
            {**item, "timeStamp": item.get("timeStamp", payload["phoneTimestamp"] * 100_000), "deviceId": device_id } for item in items # convert phone timestamp from ms to ns if timeStamp is not present
        ]
        message = MQTTMessage(
            phone_timestamp=payload["phoneTimestamp"],
            device_id=device_id,
            recording_name=payload["recordingName"],
            data_type=data_type,
            data=[data_class(**item) for item in items]
        )
        # rprint(f"Received {data_type} data from device {device_id}:")
        # rprint(message)
    except Exception as e:
        rprint(f"Error parsing message: {e}. Payload: {payload}")

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

        except aiomqtt.MqttError as error:
            print(f"MQTT Error: {error}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
