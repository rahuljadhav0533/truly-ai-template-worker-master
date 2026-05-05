from fastapi import FastAPI, UploadFile, File, Request
import tempfile
import shutil
import base64
import json

from app.processor import process_pdf, process_pdf_file_from_gcs

app = FastAPI()


# -----------------------------
# Health check
# -----------------------------
@app.get("/")
def health():
    return {"status": "ok"}


# -----------------------------
# Manual upload (testing)
# -----------------------------
@app.post("/process-pdf")
async def process(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    result = process_pdf(temp_path)
    return result


# -----------------------------
# Pub/Sub trigger (MAIN FLOW)
# -----------------------------
@app.post("/process-pubsub")
async def process_pubsub(request: Request):
    try:
        body = await request.json()

        message = body.get("message", {})
        data = message.get("data")

        if not data:
            print("No data in Pub/Sub message")
            return {"status": "no data"}

        # Decode base64
        decoded = base64.b64decode(data).decode("utf-8")

        # 3. Print decoded string
        print("DECODED STRING:", decoded)
        payload = json.loads(decoded)
        # 4. Print final payload JSON
        print("FINAL PAYLOAD:")
        print(json.dumps(payload, indent=2))

        bucket = payload.get("bucket")
        name = payload.get("name")

        print(f"Processing file: {name} from bucket: {bucket}")

        # Download + process
        result = process_pdf_file_from_gcs(bucket, name)

        print("Processing complete")

        return {"status": "processed", "file": name}

    except Exception as e:
        print("Error:", str(e))
        return {"status": "error", "message": str(e)}

import pdfplumber
import re

@app.post("/extract-i130")
async def extract_i130(file: UploadFile = File(...)):
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    # Read PDF text
    text = ""
    with pdfplumber.open(temp_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    # Clean extraction (your logic)
    result = {
        "form_name": "I-130 Petition for Alien Relative",
        "petitioner": {
            "full_name": None,
            "ssn": None,
            "date_of_birth": None,
            "country_of_birth": None,
            "marital_status": None,
            "address": None
        },
        "beneficiary": {
            "full_name": None,
            "date_of_birth": None,
            "country_of_birth": None,
            "address": None
        }
    }

    return result
