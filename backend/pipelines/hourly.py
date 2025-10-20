from app_types import CustomFastAPI
from scripts.low_visual_semantic import get_low_visual_density_indices
from scripts.querybank_norm import load_qb_norm_features
from scripts.segmentation import load_all_segments
from preprocess import save_features
from scripts.low_texture import get_pocket_indices
import numpy as np
from database.types import ImageRecord
from datetime import datetime
from app_types import CustomFastAPI

def update_app(app: CustomFastAPI):
    save_features(app.features, app.image_paths)
    app.last_saved = datetime.now()

    # Load query bank normalization features
    app.retrieved_videos, app.normalizing_sum = load_qb_norm_features(app.features)

    # Get low visual density images
    app.low_visual_indices, app.images_with_low_density = (
        get_low_visual_density_indices(app.image_paths)
    )
    low_pocket_indices, images_with_pocket = get_pocket_indices(app.image_paths)
    app.low_visual_indices = np.unique(
        np.concatenate([app.low_visual_indices, low_pocket_indices])
    )
    app.images_with_low_density = app.images_with_low_density.union(images_with_pocket)

    # Segment images excluding deleted and low visual density images
    load_all_segments(
        app.features,
        app.image_paths,
        set(ImageRecord.find(filter={"deleted": True}, distinct="image_path")).union(
            app.images_with_low_density
        ),
    )
    return app

def activity_recognition(app: CustomFastAPI):
    # Placeholder for future activity recognition implementation
    return app
