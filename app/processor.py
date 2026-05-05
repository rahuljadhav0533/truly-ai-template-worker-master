import uuid
import tempfile
from google.cloud import storage

from parser.extract_parser import extract_pdf
from app.services.ai_service import generate_questions
from app.services.deduplicator import deduplicate_questions


# -----------------------------
# MAIN PROCESSOR (unchanged)
# -----------------------------
def process_pdf(file_path):

    parsed = extract_pdf(file_path)

    result = {
        "templateId": str(uuid.uuid4()),
        "metadata": parsed.get("document_metadata", {}),
        "sections": [],
        "vector_chunks": []
    }

    for section in parsed.get("sections", []):
        section_obj = {
            "title": section["title"],
            "questions": []
        }

        for chunk in section.get("chunks", []):

            # Save chunk for vector DB later
            result["vector_chunks"].append({
                "text": chunk,
                "section": section["title"]
            })

            ai_output = generate_questions(chunk)

            section_obj["questions"].extend(
                ai_output.get("questions", [])
            )

        # Deduplicate
        section_obj["questions"] = deduplicate_questions(
            section_obj["questions"]
        )

        result["sections"].append(section_obj)

    return result


# -----------------------------
# NEW: GCS HANDLER
# -----------------------------
def process_pdf_file_from_gcs(bucket_name, file_name):

    print(f"⬇️ Downloading from GCS: {bucket_name}/{file_name}")

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        blob.download_to_filename(tmp.name)

        print("📄 File downloaded, processing...")

        result = process_pdf(tmp.name)

        print("✅ Processing complete")

        return result