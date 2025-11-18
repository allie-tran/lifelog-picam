from io import BytesIO
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import numpy as np
import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from tqdm.auto import tqdm

from app_types import CustomFastAPI, DaySummary, SummarySegment
from auth import auth_app
from scripts.utils import to_base64
from constants import DIR
from database import init_db
from database.types import DaySummaryRecord, ImageRecord
from dependencies import CamelCaseModel
from pipelines.all import process_image, process_video
from pipelines.delete import remove_from_features, remove_physical_image
from pipelines.hourly import update_app
from preprocess import get_blurred_image, get_similar_images, load_features, retrieve_image, save_features
from scripts.describe_segments import describe_segment
from scripts.openai import openai_llm
from settings import control_app, get_mode
from settings.types import PiCamControl
import base64

def to_base64(image_data: bytes) -> str:
    """Convert image data to base64 string."""
    return base64.b64encode(image_data).decode("utf-8")
