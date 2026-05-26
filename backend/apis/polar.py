import asyncio
import json
import aiomqtt
from datetime import datetime
import os
from rich import print as rprint

from dependencies import CamelCaseModel

# 1. Paste the exact settings from your screenshot
MQTT_TOPIC = "polar/#"

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))  # Default TLS port for MQTT

mqtt_client: aiomqtt.Client | None = None

class MeasurementData(CamelCaseModel):
    device_id: str
    time_stamp: int # in nanoseconds

class HeartRateData(MeasurementData):
    contact_status: bool
    contact_status_supported: bool
    corrected_hr: int
    hr: int
    ppg_quality: int
    rr_available: bool
    rrs_ms: list[float]

class MagnetometerData(MeasurementData):
    x: float
    y: float
    z: float

class AccelerometerData(MeasurementData):
    x: float
    y: float
    z: float

class GyroscopeData(MeasurementData):
    x: float
    y: float
    z: float

class PPGData(MeasurementData):
    channel_samples: list[int]
    status_bits: list[int]

class PPIData(MeasurementData):
    blocker_bit: bool
    error_estimate: int
    hr: int
    ppi: int
    skin_contact_status: bool
    skin_contact_supported: bool

class LogData(CamelCaseModel):
    type: str
    message: str

class MQTTMessage(CamelCaseModel):
    phone_timestamp: int
    device_id: str
    recording_name: str
    data_type: str
    data: list[MeasurementData | LogData]

data_type_mapping = {
    "PPG": PPGData,
    "ACC": AccelerometerData,
    "HR": HeartRateData,
    "MAGNETOMETER": MagnetometerData,
    "GYRO": GyroscopeData,
    "PPI": PPIData,
}

def parse_data(topic: str, payload: dict):
    _, data_type, device_id = topic.split("/")
    rprint(f"Received {data_type} data from device {device_id}:")
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
