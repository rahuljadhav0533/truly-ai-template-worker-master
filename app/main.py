import fitz
from pdf2image import convert_from_path
import pytesseract

from fastapi import FastAPI, UploadFile, File, Request
import tempfile
import shutil
import base64
import json
import os
import pdfplumber
import re

from parser.extract_parser import extract_pdf
from app.processor import process_pdf, process_pdf_file_from_gcs
from app.services.ai_service import generate_questions
from app.services.deduplicator import deduplicate_questions

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok"}


def detect_pdf_type(path):
    doc = fitz.open(path)

    for page in doc:
        if page.get_text().strip():
            return "text"

    return "scanned"


def extract_text_ocr(path):
    images = convert_from_path(path)
    text = ""

    for img in images:
        text += pytesseract.image_to_string(img)

    return text

@app.post("/process-pdf")
async def process(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    result = process_pdf(temp_path)

    os.remove(temp_path)  # ✅ cleanup
    return result

@app.post("/process-pubsub")
async def process_pubsub(request: Request):
    try:
        body = await request.json()

        message = body.get("message", {})
        data = message.get("data")

        if not data:
            return {"status": "no data"}

        decoded = base64.b64decode(data).decode("utf-8")
        payload = json.loads(decoded)

        bucket = payload.get("bucket")
        name = payload.get("name")

        result = process_pdf_file_from_gcs(bucket, name)

        return {"status": "processed", "file": name}

    except Exception as e:
        return {"status": "error", "message": str(e)}

import pdfplumber

text = ""

with pdfplumber.open(file_path) as pdf:
    for page in pdf.pages:
        text += page.extract_text() or ""

print("DEBUG TEXT:", text[:1000])  # check extraction

ai_output = generate_questions(text)

all_questions = ai_output.get("questions", [])


@app.post("/extract-i130")
async def extract_i130(file: UploadFile = File(...)):

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    text = ""
    with pdfplumber.open(temp_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    os.remove(temp_path)

    return {"raw_text": text[:1000]}  # simplified
