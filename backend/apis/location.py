from fastapi import Depends, FastAPI, HTTPException

from fastapi import Depends
from sqlalchemy import  select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


from typing import  Optional

from auth.devices import verify_device_and_user
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
    user = verify_device_and_user(session, device_id, "location")
    timezone = tf.timezone_at(lng=request.longitude, lat=request.latitude)
    stmt = insert(RawGPS).values(
        device_id=user.id,
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


@app.get("/latest-gps")
async def last_gps(
    device: str,
    session: Session = Depends(get_session)
):
    associated_user = session.execute(select(SensorDevice.associated_user).where(SensorDevice.device_id == device, SensorDevice.sensor_type == "location")).scalar_one_or_none()
    if not associated_user:
        raise HTTPException(status_code=404, detail="Device not found or not associated with a user")

    last_gps = session.execute(select(RawGPS).where(RawGPS.device_id == associated_user).order_by(RawGPS.timestamp.desc())).scalars().first()
    if not last_gps:
        raise HTTPException(status_code=404, detail="No GPS data found for device")
    print("Last GPS data for device {}: lat={}, lon={}, elev={}, time={}, tz={}".format(
        device, last_gps.latitude, last_gps.longitude, last_gps.elevation, last_gps.timestamp, last_gps.timezone
    ))
    return {
        "latitude": last_gps.latitude,
        "longitude": last_gps.longitude,
        "elevation": last_gps.elevation,
        "timestamp": last_gps.timestamp.isoformat(),
        "timezone": last_gps.timezone
    }
