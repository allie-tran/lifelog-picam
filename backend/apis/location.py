from fastapi import Depends, FastAPI, HTTPException

from fastapi import Depends
from sqlalchemy import  select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


from typing import  Optional

from database import get_session
from app_types import CamelCaseModel

from location.gps_pipeline import run_pipeline
from scripts.utils import get_device_from_headers
from database.models import RawGPS, Device, ImageGPS, SensorDevice
from datetime import datetime
from timezonefinder import TimezoneFinder

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

class GPSUploadRequest(CamelCaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float] = None
    timestamp: str
    device_id: str

tf = TimezoneFinder()
@app.put("/upload-gps")
async def upload_gps(
    request: GPSUploadRequest,
    session: Session = Depends(get_session)
):
    # find device
    device_id = request.device_id
    user = session.execute(select(SensorDevice.associated_user).where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == "location")).scalar_one_or_none()
    if not user:
        print("Device not found or not associated with a user. Please register the device first. (device_id: {})".format(device_id))
        raise HTTPException(status_code=404, detail="Device not found or not associated with a user. Please register the device first. (device_id: {})".format(device_id))
    username = session.execute(select(Device.id).where(Device.id == user)).scalar_one_or_none()
    if not username:
        raise HTTPException(status_code=404, detail="Associated user not found for device. Please register the device first. (device_id: {})".format(device_id))

    timezone = tf.timezone_at(lng=request.longitude, lat=request.latitude)
    stmt = insert(RawGPS).values(
        device_id=username,
        latitude=request.latitude,
        longitude=request.longitude,
        elevation=request.elevation,
        timestamp=datetime.fromisoformat(request.timestamp).astimezone(),
        timezone=timezone
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_raw_gps_device_time",
        set_={
            "latitude": request.latitude,
            "longitude": request.longitude,
            "elevation": request.elevation,
            "elevation": request.elevation,
        }
    )

    stmt = stmt.returning(RawGPS.id)
    result = session.execute(stmt)
    session.commit()

    return {"status": "success", "raw_gps_id": result.scalar()}


@app.get("/process-gps")
async def process_gps(
    device: str,
    date: str,
    session: Session = Depends(get_session)
):
    run_pipeline(session, device, date)


@app.get("/last-gps")
async def last_gps(
    device: str,
    session: Session = Depends(get_session)
):
    last_gps = session.execute(select(RawGPS).where(RawGPS.device_id == device).order_by(RawGPS.timestamp.desc())).scalars().first()
    if not last_gps:
        raise HTTPException(status_code=404, detail="No GPS data found for device")
    return {
        "latitude": last_gps.latitude,
        "longitude": last_gps.longitude,
        "elevation": last_gps.elevation,
        "timestamp": last_gps.timestamp.isoformat(),
        "timezone": last_gps.timezone
    }
