import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- WhatsApp API Credentials ---
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# --- OpenAI API Key ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Google Sheets ---
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# --- Cloudinary (screenshot image hosting) ---
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY    = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

# --- Manager Phone Number (international format, no +) ---
MANAGER_PHONE = os.getenv("MANAGER_PHONE")

# --- Employee List ---
# Each employee has a name and phone number in international format (no +)
EMPLOYEES = [
    {"name": "Ranjit", "phone": "919979638667"},
]

# Quick lookup: phone → name
EMPLOYEE_PHONE_MAP = {emp["phone"]: emp["name"] for emp in EMPLOYEES}

# All valid employee phones (used to verify sender)
VALID_EMPLOYEE_PHONES = set(EMPLOYEE_PHONE_MAP.keys())
