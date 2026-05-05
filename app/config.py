import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION", "us-central1")

MODEL_NAME = "gemini-1.5-flash"

MAX_RETRIES = 2