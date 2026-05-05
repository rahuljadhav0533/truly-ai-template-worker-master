import fitz
from pdf2image import convert_from_path
import pytesseract
from fastapi import FastAPI, UploadFile, File, Request
import tempfile
import shutil
import base64
import json

from app.processor import process_pdf, process_pdf_file_from_gcs

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
        "full_name": extract_full_name(text),
        "ssn": extract_pattern(text, r"Social Security Number.*?(\d+)"),
        "date_of_birth": extract_pattern(text, r"Date of Birth.*?(\d{2}/\d{2}/\d{4})"),
        "country_of_birth": extract_country_safe(text),
        "marital_status": extract_marital_status(text),
        "address": None
    },
    "beneficiary": {
        "full_name": extract_full_name(text),
        "date_of_birth": extract_pattern(text, r"Date of Birth.*?(\d{2}/\d{2}/\d{4})"),
        "country_of_birth": extract_country_safe(text),
        "address": None
    }
}
 

    return result

@app.post("/generate-questions-universal")
async def generate_questions_universal(file: UploadFile = File(...)):

    import tempfile, shutil

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        file_path = tmp.name

    pdf_type = detect_pdf_type(file_path)

    all_questions = []

    if pdf_type == "text":
        parsed = extract_pdf(file_path)

        for section in parsed.get("sections", []):
            for chunk in section.get("chunks", []):
                ai_output = generate_questions(chunk)
                all_questions.extend(ai_output.get("questions", []))

    else:
        text = extract_text_ocr(file_path)
        ai_output = generate_questions(text)
        all_questions.extend(ai_output.get("questions", []))

    all_questions = deduplicate_questions(all_questions)

    return {
        "pdf_type": pdf_type,
        "total_questions": len(all_questions),
        "questions": all_questions
    }
