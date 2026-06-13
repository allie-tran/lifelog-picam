#!/usr/bin/env python3
"""Backfill small grid thumbnails for existing full thumbnails.

For every `*.webp` under THUMBNAIL_DIR (skipping `*_grid.webp`), writes a
downscaled `*_grid.webp` next to it. The full thumbnails are left untouched —
they stay the served full-size image; the grid derivative is only what the
browse grid loads.

Keep MAX/QUALITY in sync with backend/services/utils.py (GRID_THUMBNAIL_*).

Usage:
    THUMBNAIL_DIR=/mnt/ssd0/Images/LifelogPicam python batch/make_grid_thumbnails.py
    python batch/make_grid_thumbnails.py --thumbnail-dir /path --workers 8 --force
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from PIL import Image

load_dotenv('../backend/.env')  # load THUMBNAIL_DIR if not set in environment

GRID_MAX = 480
GRID_QUALITY = 72


def is_grid(path: str) -> bool:
    return path.endswith("_grid.webp")


def grid_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    return f"{base}_grid{ext}"


def iter_thumbnails(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".webp") and not is_grid(name):
                yield os.path.join(dirpath, name)


def make_one(src: str, force: bool) -> tuple[str, str]:
    dst = grid_path(src)
    if not force and os.path.exists(dst):
        return ("skip", dst)
    try:
        with Image.open(src) as img:
            img.load()
            grid = img.copy()
        grid.thumbnail((GRID_MAX, GRID_MAX))
        grid.save(dst, "WEBP", quality=GRID_QUALITY)
        return ("ok", dst)
    except Exception as e:  # noqa: BLE001 — report and continue
        return ("err", f"{src}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--thumbnail-dir",
        default=os.getenv("THUMBNAIL_DIR", "/mnt/ssd0/Images/LifelogPicam"),
        help="Root of thumbnails (default: $THUMBNAIL_DIR)",
    )
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--force", action="store_true", help="Regenerate existing grid files")
    ap.add_argument("--dry-run", action="store_true", help="List work without writing")
    args = ap.parse_args()

    root = args.thumbnail_dir
    if not os.path.isdir(root):
        print(f"THUMBNAIL_DIR not found: {root}", file=sys.stderr)
        return 1

    sources = list(iter_thumbnails(root))
    print(f"Found {len(sources)} full thumbnails under {root}")

    if args.dry_run:
        todo = [s for s in sources if args.force or not os.path.exists(grid_path(s))]
        print(f"Would create {len(todo)} grid thumbnails (max={GRID_MAX}, q={GRID_QUALITY})")
        return 0

    counts = {"ok": 0, "skip": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(make_one, s, args.force): s for s in sources}
        for i, fut in enumerate(as_completed(futures), 1):
            status, info = fut.result()
            counts[status] += 1
            if status == "err":
                print(f"  ERR {info}", file=sys.stderr)
            if i % 500 == 0:
                print(f"  {i}/{len(sources)} processed ({counts})")

    print(f"Done: {counts['ok']} created, {counts['skip']} skipped, {counts['err']} errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
