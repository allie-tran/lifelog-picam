from fastapi import Depends, FastAPI

from fastapi import Depends
from sqlalchemy import  select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


from typing import  Optional

from database import get_session
from app_types import CamelCaseModel

from location.gps_pipeline import run_pipeline
from scripts.utils import get_device_from_headers
from database.models import RawGPS, Device, ImageGPS
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

tf = TimezoneFinder()
@app.put("/upload-gps")
async def upload_gps(
    request: GPSUploadRequest,
    device: str = Depends(get_device_from_headers),
    session: Session = Depends(get_session)
):
    # find device
    timezone = tf.timezone_at(lng=request.longitude, lat=request.latitude)
    stmt = insert(RawGPS).values(
        device_id=select(Device.id).where(Device.device_id == device),
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
