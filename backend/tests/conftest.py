"""Shared pytest config for the backend unit suite.

These tests are unit-only: no Postgres, Mongo, Redis, Celery, or network. We set
harmless env defaults *before* any app module imports so `core.config` (which
calls `load_dotenv` and reads DIR/THUMBNAIL_DIR at import time) resolves to a
temp sandbox instead of the real data mounts.
"""
import os
import tempfile

# Sandbox the image/thumbnail roots so nothing points at real data mounts.
_SANDBOX = tempfile.mkdtemp(prefix="picam-test-")
os.environ.setdefault("DIR", os.path.join(_SANDBOX, "images"))
os.environ.setdefault("THUMBNAIL_DIR", os.path.join(_SANDBOX, "thumbnails"))
os.environ.setdefault("EMBEDDING_DIR", os.path.join(_SANDBOX, "embeddings"))
