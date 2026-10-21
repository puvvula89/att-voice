"""Shared names for the bootstrap scripts. Every value comes from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("CARE_APP_ID", "cricket-care")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
