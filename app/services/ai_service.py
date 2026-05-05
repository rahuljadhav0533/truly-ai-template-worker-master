import json
import time
import re
import vertexai
from vertexai.generative_models import GenerativeModel
from app.config import PROJECT_ID, LOCATION, MODEL_NAME, MAX_RETRIES

# Init Vertex AI
vertexai.init(project=PROJECT_ID, location=LOCATION)

model = GenerativeModel(MODEL_NAME)

PROMPT = """
You are an expert business analyst.

Convert the following document content into structured interview questions.

Return ONLY valid JSON.
Do NOT include markdown, backticks, or explanations.
Ensure the JSON is complete and valid.

Format:

{
  "questions": [
    {
      "question": "",
      "type": "text | select | date | number",
      "required": true
    }
  ]
}

TEXT:
{chunk}
"""

# -----------------------------
# CLEAN AI RESPONSE
# -----------------------------
def clean_ai_response(text: str) -> str:
    text = text.strip()

    # Remove markdown code blocks safely
    if text.startswith("```"):
        text = re.sub(r"^```json", "", text)
        text = re.sub(r"^```", "", text)
        text = re.sub(r"```$", "", text)

    return text.strip()


# -----------------------------
# EXTRACT VALID JSON
# -----------------------------
def extract_json(text: str):
    # Try direct parse
    try:
        return json.loads(text)
    except:
        pass

    # Try extracting JSON block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())

    raise ValueError("Invalid JSON format")


# -----------------------------
# VALIDATE RESPONSE STRUCTURE
# -----------------------------
def validate_response(data: dict):
    if not isinstance(data, dict):
        raise ValueError("Response is not a JSON object")

    if "questions" not in data:
        raise ValueError("Missing 'questions' key")

    if not isinstance(data["questions"], list):
        raise ValueError("'questions' must be a list")

    return True


# -----------------------------
# MAIN FUNCTION
# -----------------------------
def generate_questions(chunk):
    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(
                PROMPT.format(chunk=chunk),
                generation_config={
                    "max_output_tokens": 4096,
                    "temperature": 0.2,
                    "response_mime_type": "application/json"
                }
            )

            text = response.text or ""

            # 🔍 Debug log (very important)
            print("========== RAW AI RESPONSE ==========")
            print(text[:500])  # avoid huge logs
            print("=====================================")

            text = clean_ai_response(text)

            # 🚨 Detect incomplete JSON early
            if not text.startswith("{") or not text.endswith("}"):
                raise ValueError("Incomplete JSON from AI")

            data = extract_json(text)

            # ✅ Validate structure
            validate_response(data)

            return data

        except Exception as e:
            print(f"[AI ERROR] retry {attempt}: {e}")
            time.sleep(1)

    # fallback
    return {"questions": []}