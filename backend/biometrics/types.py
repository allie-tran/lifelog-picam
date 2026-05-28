
from dependencies import CamelCaseModel


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
    "LOG": LogData
}
