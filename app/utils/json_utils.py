import json
import re

def extract_json(text: str) -> dict:
    """
    Extract the first valid JSON object from Gemini output.
    Handles:
    - Plain JSON
    - Text before/after JSON
    - ```json fenced blocks
    """

    if not text or not text.strip():
        raise ValueError("Empty response from Gemini")

    # Remove markdown fences if any
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()

    # Find first JSON object
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError(f"No JSON object found in Gemini response: {text}")

    return json.loads(match.group())