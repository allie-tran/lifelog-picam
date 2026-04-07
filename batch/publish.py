import os
import json
import io
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload
import piexif
from PIL import Image as PILImage

# Import your models from models.py
from models import Image, ImageGPS, ImageObject, ImagePerson, ImageOCR

# --- Configuration ---
PG_URI = "postgresql://postgres:password@localhost:5432/lsc24"
SRC_DIR = "data/images"          # Where originals live
THUMB_DIR = "data/thumbnails"    # Where current thumbnails live
OUT_DIR = "data/published"       # Destination
engine = create_engine(PG_URI)

def get_full_metadata(image_row: Image):
    """Serializes relational data into a dictionary for JSON."""
    return {
        "id": str(image_row.id),
        "timestamp": image_row.local_timestamp.isoformat() if image_row.local_timestamp else None,
        "activity": {
            "label": image_row.activity,
            "confidence": image_row.activity_confidence,
            "description": image_row.activity_description
        },
        "location": {
            "name": image_row.location.name if image_row.location else None,
            "address": image_row.location.address if image_row.location else None,
            "gps": {
                "lat": image_row.gps.latitude,
                "lon": image_row.gps.longitude,
                "alt": image_row.gps.elevation
            } if image_row.gps else None
        },
        "detections": {
            "objects": [{"label": o.label, "conf": o.confidence, "bbox": o.bbox} for o in image_row.objects],
            "people": [{"name": p.label, "conf": p.confidence, "bbox": p.bbox} for p in image_row.people],
            "ocr": [{"text": t.text, "conf": t.confidence, "bbox": t.box_2d} for t in image_row.ocr]
        }
    }

def publish_batch(limit=50):
    with Session(engine) as session:
        stmt = (
            select(Image)
            .options(
                selectinload(Image.location),
                selectinload(Image.gps),
                selectinload(Image.objects),
                selectinload(Image.people),
                selectinload(Image.ocr)
            )
            .limit(limit)
        )
        
        images = session.execute(stmt).scalars().all()
        
        for img in images:
            # 1. Path Setup
            # Adjusting path logic to match your device-based subfolders
            src_path = os.path.join(SRC_DIR, img.device, img.image_path)
            thumb_source = os.path.join(THUMB_DIR, img.device, img.thumbnail)
            
            # Destination: data/published/YYYY/MM/DD/filename.jpg
            dt = img.local_timestamp or datetime.now()
            target_dir = os.path.join(OUT_DIR, f"{dt.year}", f"{dt.month:02d}", f"{dt.day:02d}")
            os.makedirs(target_dir, exist_ok=True)
            
            base_name = os.path.basename(img.image_path)
            target_img = os.path.join(target_dir, base_name)
            target_json = os.path.join(target_dir, base_name.replace(".jpg", ".json"))

            try:
                # 2. Handle Image & EXIF
                # We load EXIF from the ORIGINAL (src_path) but save it to the THUMBNAIL
                if os.path.exists(src_path) and os.path.exists(thumb_source):
                    exif_dict = piexif.load(src_path)
                    
                    # Optional: Inject your DB data into the EXIF object here
                    # (See previous logic for piexif.ImageIFD.XPKeywords etc.)
                    exif_bytes = piexif.dump(exif_dict)
                    
                    with PILImage.open(thumb_source) as t_img:
                        t_img.save(target_img, "JPEG", exif=exif_bytes, quality=95)
                
                # 3. Generate Metadata JSON
                metadata = get_full_metadata(img)
                with open(target_json, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                
                print(f"Published: {base_name}")

            except Exception as e:
                print(f"Failed {img.id}: {e}")

if __name__ == "__main__":
    publish_batch()