import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from app.utils.number_normalizer import normalize_hindi_numbers

router = APIRouter(prefix="/parse-voice", tags=["Voice"])

# Initialize OpenAI client (expects OPENAI_API_KEY in environment)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class VoiceInput(BaseModel):
    text: str

def split_into_segments(text: str) -> list[str]:
    separators = [" aur ", " phir ", " then ", ",", "\n"]
    segments = [text]

    for sep in separators:
        temp = []
        for seg in segments:
            temp.extend(seg.split(sep))
        segments = temp

    return [s.strip() for s in segments if s.strip()]

def safe_json_loads(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None

@router.post("")
def parse_voice(data: VoiceInput):
    clean_text = normalize_hindi_numbers(data.text)
    segments = split_into_segments(clean_text)
    items = []
    errors = []

    for segment in segments:
        prompt = f"""
You are an AI assistant for an Indian hardware and timber shop.

Convert the spoken sentence into structured JSON.

Rules:
- Quantity MUST be a number
- Rate MUST be a number in INR
- Unit can be any free text
- If rate is missing or not numeric, return EXACTLY:
{{ "error": "RATE_MISSING" }}
- Do NOT guess
- Do NOT add extra text
- Return ONLY valid JSON

Sentence:
\"{segment}\"
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You convert voice commands into JSON for billing."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )

            content = response.choices[0].message.content.strip()
            parsed = json.loads(content)

            if "error" in parsed:
                errors.append({
                    "segment": segment,
                    "error": parsed["error"]
                })
            else:
                items.append(parsed)

        except Exception:
            errors.append({
                "segment": segment,
                "error": "PARSE_FAILED"
            })

    if not items and errors:
        return {
            "items": [],
            "errors": errors
        }

    return {
        "items": items,
        "errors": errors
    }