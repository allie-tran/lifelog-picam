import base64

from core.config import DIR, THUMBNAIL_DIR
from services.utils import (
    get_thumbnail_path,
    grid_thumbnail_path,
    to_absolute_bbox,
    to_base64,
)


def test_to_base64_roundtrips():
    assert base64.b64decode(to_base64(b"hello")) == b"hello"


class TestToAbsoluteBbox:
    def test_normalised_coords_scaled_to_pixels(self):
        assert to_absolute_bbox((0.1, 0.2, 0.5, 0.6), 100, 200) == (10, 40, 50, 120)

    def test_already_absolute_coords_pass_through_as_ints(self):
        # Any coord > 1 means the bbox is already in pixels; returned untouched.
        assert to_absolute_bbox((10, 20, 50, 60), 100, 200) == (10, 20, 50, 60)

    def test_normalised_coords_capped_to_image_bounds(self):
        # x2/y2 of 1.0 would land on width/height; clamped to dimension-1.
        assert to_absolute_bbox((0.0, 0.0, 1.0, 1.0), 100, 200) == (0, 0, 99, 199)


class TestGridThumbnailPath:
    def test_inserts_grid_suffix_before_extension(self):
        assert grid_thumbnail_path("/a/b/c.webp") == "/a/b/c_grid.webp"


class TestGetThumbnailPath:
    def test_maps_image_dir_to_thumbnail_dir_with_webp_ext(self):
        path, exists = get_thumbnail_path(f"{DIR}/2024/01/pic.jpg")
        assert path == f"{THUMBNAIL_DIR}/2024/01/pic.webp"
        # Nothing was written in the sandbox, so it must not exist.
        assert exists is False
