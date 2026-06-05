from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from database.models import Device

def create_device(session: Session, device: str):
    stmt = insert(Device).values(device_id=device).on_conflict_do_nothing(index_elements=["device_id"])
    session.execute(stmt)
    session.commit()
    return {"message": f"Device {device} created successfully."}
