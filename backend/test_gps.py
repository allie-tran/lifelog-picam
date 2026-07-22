from sqlalchemy.sql import update
from database.models import Image, ImageGPS
from location.airports import nearest_airport
import os
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, select, text
from location.enrich_stops import enrich_stop
from location.gps_pipeline import run_pipeline
import logging
from dotenv import load_dotenv

from services.segmentation import load_all_segments
# lat = 52.35705709268293
# lon = 4.927731298360656
logging.basicConfig(level=logging.INFO)

# Dublin
lat = 53.42653365967742
lon = -6.243571532085561

# WHS Smith
lat = 53.42845998305085
lon = -6.2467839396825395

print(nearest_airport(lat, lon))
print(enrich_stop(lat, lon))


load_dotenv()
engine = create_engine(os.environ["PG_URI"])
Session = sessionmaker(bind=engine)

with Session() as session:
    device = "allie"
    date = "2026-06-14"
    image_ids = session.execute(
        select(Image.id).where(
            Image.device == device, Image.date == date
        )
    ).scalars().all()
    batch_size = 500
    for i in range(0, len(image_ids), batch_size):
        batch = image_ids[i:i + batch_size]
        res = session.execute(
            update(
                ImageGPS
            ).where(
                ImageGPS.image_id.in_(batch)
            ).values(mode=None)
        )
    session.commit()
    run_pipeline(session, device, date, modes_only=True)
    session.execute(
        update(Image)
        .where(Image.date == date)
        .where(Image.device == device)
        .values(
            segment_id=None,
        )
    )
    session.commit()
    print(f"Reset segments for date {date} and device {device}.")
    load_all_segments(session, device, date, skip_annotations=False)
