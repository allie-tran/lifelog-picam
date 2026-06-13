# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**lifelog-picam** is a lifelogging system that captures images and GPS data from a Raspberry Pi camera, uploads them to a server, and provides a web UI for browsing, searching, and annotating the lifelog. The system is built around three main components: a camera client (Pi), a FastAPI backend server, and a React frontend.

## Components

### `camera/` — Raspberry Pi client
Runs on the Pi Zero 2W. Two background processes:
- `auto_capture.py` — captures still images every 10 seconds using `picamzero`, reads GPS via serial NMEA, encrypts images with PyNaCl before saving
- `watchdog_monitor.py` — watches `OUTPUT` dir for new files and uploads them (with GPS) to the backend via HTTP; retries on failure

Started automatically via crontab (`auto_capture.sh`, `monitor.sh`). Device identity comes from `.env` (`DEVICE_ID`, `DEVICE_SECRET_KEY`, `SERVER_PUBLIC_KEY`).

### `backend/` — FastAPI server
Runs at port 8082. Key dependencies: PostgreSQL (pgvector), MongoDB (ODM for user/auth documents), Redis (Celery broker + cache), Celery workers.

**App structure** — `main.py` composes one FastAPI app from `APIRouter` modules
in `routers/` (via `include_router`, prefixes preserve the original paths).
Business logic lives in `services/` (formerly `scripts/`), Pydantic models in
`schemas/` (formerly `app_types/`), config/logging/deps in `core/`, and external
clients in `integrations/` (`llm/`, `visual/`, `biometrics/`, `sessions/`). Route
prefixes:
- `/auth` — JWT auth, user/device management
- `/ingest` — chunked zip upload endpoint; processes zip into image records
- `/browse` — date/device browsing
- `/retrieval` — semantic search (CLIP embeddings via ConCLIP)
- `/explore` — deeper search and filtering
- `/location` — GPS ingest and location resolution (Foursquare)
- `/images`, `/annotations`, `/face`, `/delete` — image management

**Pipeline** — after upload, images go through `pipelines/`: segmentation (clustering by CLIP embedding similarity, threshold `SEGMENT_THRESHOLD=0.85`), activity annotation via LLM (Gemini by default), and day summary generation.

**LLM layer** — `backend/integrations/llm/` wraps Gemini (`gemini.py`), OpenAI (`openai.py`), and Ollama (`ollama.py`). The active model is set via `GEMINI_MODEL_NAME` / `OPENAI_MODEL_NAME` env vars.

**Database** — PostgreSQL via SQLAlchemy ORM (`database/models.py`): `Image`, `ImageEmbedding`, `ImageGPS`, `ImageObject`, `ImagePerson`, `Location`, `Device`. MongoDB via `mongodb-odm` for `User` and `DaySummaryRecord`. `database/types.py` contains `ImageRecord` — a helper class wrapping SQLAlchemy queries in a MongoDB-compatible API.

**Celery tasks** (`tasks/` package — the app is `tasks.celery_app`) — `describe_segment_task` calls the LLM to annotate a segment; runs in a solo worker pool with Redis backend. Task names stay `tasks.<func>` (jobs live in `tasks/__init__.py`).

### `frontend/` — React/TypeScript SPA
Uses `react-app-rewired` (CRA with overrides). State via Redux Toolkit. UI via MUI. Key pages: `MainPage`, `SearchPage`, `Faces`, `Biometrics`, `Admin`.

### `batch/` — one-off batch scripts
Standalone scripts for bulk indexing, embedding generation (ConCLIP ViT-L/14), object detection (YOLO), face clustering, Elasticsearch indexing, etc. Not part of the running service.

### `anonymisation/` — face anonymisation pipeline
Jupyter notebooks + scripts for face detection (YOLO), clustering, and blurring/segmentation (SAM).

### `alembic/` — DB migrations
Manages the PostgreSQL schema. The `batch/models.py` defines the batch-side ORM; migrations target that `Base`.

## Running the Services

### Backend
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8082 --reload
# In a separate terminal, start the Celery worker:
celery -A tasks.celery_app worker --loglevel=info
```
Requires `.env` with at minimum: `PG_URI`, `JWT_SECRET`, `GEMINI_API`, `GEMINI_MODEL_NAME`, `DIR`, `THUMBNAIL_DIR`.

### Frontend
```bash
cd frontend
yarn dev          # development server (port 3000) — use yarn, not npm
yarn build        # production build
```

### Camera (Pi only)
```bash
cd camera
python auto_capture.py   # capture images
python watchdog_monitor.py  # upload to server
```

### Database migrations
```bash
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Key Environment Variables

| Variable | Where | Purpose |
|---|---|---|
| `PG_URI` | backend, alembic | PostgreSQL connection |
| `JWT_SECRET` | backend | Auth token signing |
| `GEMINI_API` / `GEMINI_MODEL_NAME` | backend | LLM for segment annotation |
| `DIR` | backend | Root path for raw images |
| `THUMBNAIL_DIR` | backend | Root path for thumbnails |
| `DEVICE_ID` | camera, root `.env` | Camera device identity |
| `SERVER_PUBLIC_KEY` | camera | Server NaCl public key for image encryption |

## Architecture Notes

- Images are encrypted on the Pi using NaCl (box encryption) before upload; decrypted server-side in the ingest pipeline.
- Segmentation groups consecutive images by CLIP embedding cosine similarity; segments below the threshold create a new group.
- `DaySummaryRecord` in MongoDB caches computed day summaries; the `updated` flag triggers regeneration.
- The `ImageRecord` class in `database/types.py` is the main query interface — it wraps SQLAlchemy but exposes a MongoDB-style API (`find`, `find_one`, `distinct`, `update_one`) to ease the MongoDB→PostgreSQL migration.
- Auth uses two levels: JWT tokens (short-lived, via Redis session) and access levels (`NONE`, `ANY`, `OWNER`, `ADMIN`) enforced per endpoint via `Depends`.
