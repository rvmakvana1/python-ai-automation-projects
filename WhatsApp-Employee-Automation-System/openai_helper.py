import json
from openai import OpenAI
from config import OPENAI_API_KEY

# Initialize the OpenAI client once at module load
_client = OpenAI(api_key=OPENAI_API_KEY)

# System prompt that instructs the model to extract structured report data
_SYSTEM_PROMPT = """You are a data extraction assistant for PromoPe, a talent/influencer marketing company.
An employee will send you their end-of-day work report in casual Hindi or English (or a mix).
Your job is to extract the following fields and return ONLY a valid JSON object — no markdown, no explanation.

Fields to extract:
- brands_found         (number or string)
- brands_platform      (e.g. LinkedIn, Instagram, Facebook)
- brands_messaged      (number or string)
- brands_replied       (number or string)
- influencers_found    (number or string)
- influencers_platform (e.g. Instagram, YouTube)
- influencers_messaged (number or string)
- influencers_replied  (number or string)

Rules:
- If a field is not mentioned, set its value to "not mentioned".
- Do NOT include any text outside the JSON object.
- Example output:
{
  "brands_found": "10",
  "brands_platform": "LinkedIn, Instagram",
  "brands_messaged": "7",
  "brands_replied": "2",
  "influencers_found": "15",
  "influencers_platform": "Instagram",
  "influencers_messaged": "10",
  "influencers_replied": "3"
}
"""


def parse_report(text: str) -> dict:
    """Send employee report text to OpenAI and extract structured data.

    Args:
        text: Raw employee report message (Hindi/English/mixed).

    Returns:
        A dict with the 8 standardized report fields.
        Falls back to all "not mentioned" values if parsing fails.
    """
    fallback = {
        "brands_found": "not mentioned",
        "brands_platform": "not mentioned",
        "brands_messaged": "not mentioned",
        "brands_replied": "not mentioned",
        "influencers_found": "not mentioned",
        "influencers_platform": "not mentioned",
        "influencers_messaged": "not mentioned",
        "influencers_replied": "not mentioned",
    }

    try:
        print(f"[OpenAI] Parsing report text: {text[:80]}...")

        response = _client.chat.completions.create(
            model="gpt-4o-mini",          # Fast and cost-effective for extraction tasks
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
            temperature=0,               # Deterministic output for data extraction
            max_tokens=300,
        )

        raw_output = response.choices[0].message.content.strip()
        print(f"[OpenAI] Raw output: {raw_output}")

        parsed = json.loads(raw_output)

        # Ensure all expected keys exist; fill missing ones with fallback value
        for key in fallback:
            if key not in parsed:
                parsed[key] = "not mentioned"

        print("[OpenAI] Report parsed successfully")
        return parsed

    except json.JSONDecodeError as e:
        print(f"[OpenAI] JSON decode error: {e}")
        return fallback
    except Exception as e:
        print(f"[OpenAI] Exception during parsing: {e}")
        return fallback
