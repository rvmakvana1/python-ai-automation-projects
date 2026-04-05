import os
import re
import time
import random
import queue
import threading
import unicodedata
import traceback
import requests
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, features as pil_features
from gemini_scraper import generate_image_from_browser
import json as _json
from google import genai as _genai

# Playwright for browser-grade Indic text rendering (optional — Pillow is fallback)
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    print("⚠️  playwright not installed — Pillow fallback will be used for text overlay.")


# --- 1. CONFIGURATION & SETUP ---
load_dotenv()
app = Flask(__name__)

# Meta WhatsApp API
WHATSAPP_TOKEN  = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN    = os.getenv("VERIFY_TOKEN", "promope_secure_webhook_123")

# Gemini API client for text extraction (NOT image generation — that uses gemini_scraper.py)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_gemini_text_client = None
if GEMINI_API_KEY:
    try:
        _gemini_text_client = _genai.Client(api_key=GEMINI_API_KEY)
        print("Gemini text client initialized (gemini-2.5-flash).")
    except Exception as _e:
        print(f"WARNING: Gemini text client init failed: {_e} — will use basic parser.")
else:
    print("WARNING: GEMINI_API_KEY not set — Gemini extraction disabled, basic parser only.")

# ── State machine globals ──────────────────────────────────────────────────────
user_states      = {}   # {phone: {"state": int, "lang": str}}
human_mode_users = set()

# State constants
STATE_GREETING   = 0   # Greeting sent, waiting for language choice
STATE_SAMPLES_Q  = 1   # Welcome sent, waiting for yes/no on sample posters
STATE_DEMO_Q     = 2   # Samples done (or skipped), waiting for yes/no on demo
STATE_COLLECT    = 3   # "Send your details" prompt sent, waiting for details text
STATE_CONFIRM    = 4   # Confirmation button shown, waiting for button tap
STATE_GENERATING = 5   # Poster is being generated — ignore incoming text
STATE_FEEDBACK   = 6   # Poster delivered, waiting for feedback yes/no
STATE_PAYMENT    = 7   # QR code sent, waiting for payment screenshot (image msg)
STATE_DONE       = 8   # End of flow — next message restarts from greeting
STATE_RETRY      = 9   # Ask "want another poster?" — yes → STATE_COLLECT, no → STATE_DONE
STATE_ASK_MORE_INFO  = 10  # Ask "any extra tagline/offer?"
STATE_WAIT_MORE_INFO = 11  # Waiting for extra info text or "no"
STATE_ASK_USE_SAVED  = 12  # Ask "use old details or new?"

# ── Configurable sample media ─────────────────────────────────────────────────
# Populate these with real public URLs or local absolute paths.
# Empty strings ("") are silently skipped when sending samples.
SAMPLE_IMAGES = ["1.jpg", "2.jpg", "3.jpg", "4.jpg"]
SAMPLE_VIDEOS = ["v1.mp4", "v2.mp4"]

# Pending poster details — stores collected user data awaiting button confirmation
# key: sender_phone  value: dict with owner_name, business_name, mobile, address, category, lang
pending_poster_details = {}

# Queue for serialised poster generation — ensures only one Playwright instance runs at a time
poster_queue = queue.Queue()

# Demo limit tracking — max 3 free posters per phone number
demo_limits    = {}   # {phone: int}
DEMO_LIMIT_MAX = 3
_DEMO_LIMIT_MSG_LANG = {
    "gujarati": (
        "તમારી ફ્રી ડેમો લિમિટ (3 પોસ્ટર) પૂરી થઈ ગઈ છે. "
        "રોજ નવા પોસ્ટર મેળવવા માટે કૃપા કરીને ₹499 નો પ્લાન એક્ટિવ કરો."
    ),
    "hindi": (
        "Aapki free demo limit (3 poster) khatam ho gayi hai. "
        "Roz naye poster paane ke liye ₹499 ka plan activate karein."
    ),
    "english": (
        "Your free demo limit (3 posters) has been reached. "
        "Please activate the ₹499 plan to receive new posters daily."
    ),
    "hinglish": (
        "Aapki free demo limit (3 poster) khatam ho gayi hai. "
        "Daily naye poster ke liye ₹499 wala plan activate karo."
    ),
}
_DEMO_LIMIT_MSG = _DEMO_LIMIT_MSG_LANG["gujarati"]  # backward-compat alias

# Runtime folders
os.makedirs("generated_images", exist_ok=True)
os.makedirs("fonts", exist_ok=True)


# --- 2. LOCAL IMAGE SERVER ---
@app.route('/generated_images/<path:filename>')
def serve_image(filename):
    """Serve generated poster images publicly so Meta API can download them."""
    return send_from_directory('generated_images', filename)


@app.route('/samples/<path:filename>')
def serve_sample(filename):
    """Serve sample poster images and videos so Meta API can download them."""
    return send_from_directory('samples', filename)


@app.route('/qr_code.jpg')
def serve_qr_code():
    """Serve the payment QR code image so Meta API can download it."""
    return send_from_directory(os.path.abspath('.'), 'qr_code.jpg')


# --- 3. WHATSAPP HELPERS ---
def send_whatsapp_message(to_phone, message_text, media_url=None):
    """Send a WhatsApp text or image message with anti-ban delay."""
    delay = random.randint(10, 15)
    print(f"⏳ Anti-Ban: Waiting {delay}s before replying to {to_phone}...")
    time.sleep(delay)

    url     = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

    if media_url:
        payload = {
            "messaging_product": "whatsapp", "to": to_phone, "type": "image",
            "image": {"link": media_url, "caption": message_text}
        }
    else:
        payload = {
            "messaging_product": "whatsapp", "to": to_phone, "type": "text",
            "text": {"body": message_text}
        }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"❌ WhatsApp Error {response.status_code}: {response.text}")
    else:
        print(f"✅ Message sent to {to_phone} successfully!")
    return response.json()


def send_whatsapp_button_message(to_phone, body_text, button_label, button_id):
    """
    Send an interactive WhatsApp button message (Quick Reply style).

    Meta supports up to 3 buttons per interactive message.
    button_id is what comes back in the webhook when the user taps.
    Applies the same anti-ban delay as send_whatsapp_message().
    """
    delay = random.randint(10, 15)
    print(f"⏳ Anti-Ban: Waiting {delay}s before sending button to {to_phone}...")
    time.sleep(delay)

    url     = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": button_id, "title": button_label}
                    }
                ]
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"❌ WhatsApp Button Error {response.status_code}: {response.text}")
    else:
        print(f"✅ Button message sent to {to_phone} — button_id='{button_id}'")
    return response.json()


def send_whatsapp_image_only(to_phone, media_url):
    """Send a WhatsApp image with no caption text."""
    delay = random.randint(10, 15)
    print(f"⏳ Anti-Ban: Waiting {delay}s before sending image to {to_phone}...")
    time.sleep(delay)

    url     = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "image",
        "image": {"link": media_url},
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"❌ WhatsApp Image Error {response.status_code}: {response.text}")
    else:
        print(f"✅ Image sent to {to_phone} successfully!")
    return response.json()


def send_whatsapp_video(to_phone, media_url):
    """Send a WhatsApp video with no caption text."""
    delay = random.randint(10, 15)
    print(f"⏳ Anti-Ban: Waiting {delay}s before sending video to {to_phone}...")
    time.sleep(delay)

    url     = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "video",
        "video": {"link": media_url},
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"❌ WhatsApp Video Error {response.status_code}: {response.text}")
    else:
        print(f"✅ Video sent to {to_phone} successfully!")
    return response.json()


# --- 4. POSTER TEXT OVERLAY ENGINE ---
def add_text_to_poster(image_path, name, business_name, number, address):
    """
    Bulletproof Pillow poster engine with comprehensive step-by-step logging.

    Font priority:
      1. fonts/NotoSansGujarati_Condensed-Bold.ttf  (local, best Gujarati shaping)
      2. C:\\Windows\\Fonts\\NirmalaB.ttf            (Windows bold Indic)
      3. C:\\Windows\\Fonts\\Nirmala.ttf
      4. C:\\Windows\\Fonts\\NirmalaUI.ttf
      5. C:\\Windows\\Fonts\\mangal.ttf

    Design:
      - Solid semi-transparent black rectangle at bottom 35%
      - Business name: large, Gold (#D4AF37)
      - Contact details: white, Gujarati labels (નામ: / મોબાઈલ: / સરનામું:)
    """
    print()
    print("=" * 65)
    print("  POSTER ENGINE: Starting text overlay")
    print("=" * 65)
    print(f"  Image path : {image_path}")
    print(f"  Business   : {business_name}")
    print(f"  Name       : {name}")
    print(f"  Mobile     : {number}")
    print(f"  Address    : {address}")
    print("=" * 65)

    try:
        # -------------------------------------------------------
        # STEP 1 — Load background image
        # -------------------------------------------------------
        print("\n[1/7] Loading background image...")
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        img           = Image.open(image_path).convert("RGBA")
        width, height = img.size
        print(f"      ✔ Loaded: {width} x {height} px")

        # -------------------------------------------------------
        # STEP 2 — Load font
        # -------------------------------------------------------
        print("\n[2/7] Loading font...")
        local_font = os.path.join("fonts", "NotoSansGujarati_Condensed-Bold.ttf")
        candidates = [
            local_font,
            "C:\\Windows\\Fonts\\NirmalaB.ttf",
            "C:\\Windows\\Fonts\\Nirmala.ttf",
            "C:\\Windows\\Fonts\\NirmalaUI.ttf",
            "C:\\Windows\\Fonts\\mangal.ttf",
        ]
        font_path = next((p for p in candidates if os.path.exists(p)), None)
        if font_path is None:
            raise FileNotFoundError(
                "No font found! Add NotoSansGujarati_Condensed-Bold.ttf to the 'fonts/' folder "
                "or install Nirmala.ttf on Windows."
            )
        print(f"      ✔ Font: {font_path}")

        # Detect RAQM for better Indic shaping (silently falls back to BASIC)
        try:
            layout_engine = (
                ImageFont.Layout.RAQM
                if hasattr(ImageFont, "Layout") and pil_features.check_feature("raqm")
                else ImageFont.Layout.BASIC
            )
        except AttributeError:
            layout_engine = ImageFont.Layout.BASIC

        engine_label = "RAQM (full shaping)" if layout_engine == ImageFont.Layout.RAQM else "BASIC (NFC fallback)"
        print(f"      ✔ Layout engine: {engine_label}")

        # Large sizes — better matra clarity, especially without RAQM
        title_size    = max(int(height * 0.075), 65)
        subtitle_size = max(int(height * 0.042), 36)
        print(f"      ✔ Title: {title_size}px  |  Subtitle: {subtitle_size}px")

        title_font    = ImageFont.truetype(font_path, title_size,    layout_engine=layout_engine)
        subtitle_font = ImageFont.truetype(font_path, subtitle_size, layout_engine=layout_engine)
        print("      ✔ Font objects created.")

        # NFC normalise helper — pre-composes Gujarati matras/conjuncts
        def _n(text):
            return unicodedata.normalize("NFC", str(text))

        # -------------------------------------------------------
        # STEP 3 — Draw semi-transparent black overlay rectangle
        # -------------------------------------------------------
        print("\n[3/7] Drawing semi-transparent overlay rectangle...")
        overlay_top    = int(height * 0.65)      # bottom 35% of image
        overlay_canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_overlay   = ImageDraw.Draw(overlay_canvas)
        draw_overlay.rectangle(
            [(0, overlay_top), (width, height)],
            fill=(0, 0, 0, 200)                  # solid semi-transparent black, alpha=200/255
        )
        img  = Image.alpha_composite(img, overlay_canvas).convert("RGB")
        draw = ImageDraw.Draw(img)
        print(f"      ✔ Rectangle drawn: y={overlay_top} → y={height}  (alpha=200)")

        # -------------------------------------------------------
        # STEP 4 — Calculate text positions (3-band grid)
        # -------------------------------------------------------
        print("\n[4/7] Calculating text positions...")
        margin_x   = int(width * 0.06)
        band_h     = height - overlay_top

        title_y    = overlay_top + int(band_h * 0.06)
        divider_y  = overlay_top + int(band_h * 0.50)
        contact_y  = overlay_top + int(band_h * 0.55)
        contact_y2 = contact_y + int(subtitle_size * 1.7)

        print(f"      ✔ overlay_top={overlay_top}  title_y={title_y}  "
              f"divider_y={divider_y}  contact_y={contact_y}  contact_y2={contact_y2}")

        # Centred text helper with 2px drop shadow
        def _draw_center(text, font, y, color):
            text = _n(text)
            try:
                bbox   = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
            except AttributeError:
                # Pillow < 8.0 fallback
                text_w, _ = font.getsize(text)
            x = max(margin_x, int((width - text_w) / 2))
            draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0))    # shadow
            draw.text((x,     y),     text, font=font, fill=color)

        # -------------------------------------------------------
        # STEP 5 — Draw business name (Gold, large)
        # -------------------------------------------------------
        print(f"\n[5/7] Drawing business name: '{business_name}'...")
        _draw_center(business_name, title_font, title_y, "#D4AF37")
        print("      ✔ Business name drawn in Gold (#D4AF37).")

        # Gold divider line between title and contact bands
        inner_pad = int(width * 0.08)
        draw.line(
            [(inner_pad, divider_y), (width - inner_pad, divider_y)],
            fill="#D4AF37", width=2
        )
        print("      ✔ Gold divider line drawn.")

        # -------------------------------------------------------
        # STEP 6 — Draw contact details (White, Gujarati labels)
        # -------------------------------------------------------
        print("\n[6/7] Drawing contact details...")
        line1 = f"નામ: {name}   |   મોબાઈલ: {number}"
        line2 = f"સરનામું: {address}"
        print(f"      Line 1: {line1}")
        print(f"      Line 2: {line2}")
        _draw_center(line1, subtitle_font, contact_y,  "#F5F5F5")
        _draw_center(line2, subtitle_font, contact_y2, "#F5F5F5")
        print("      ✔ Contact details drawn in Soft White (#F5F5F5).")

        # -------------------------------------------------------
        # STEP 7 — Save final image at high quality
        # -------------------------------------------------------
        print(f"\n[7/7] Saving final poster to: {image_path}")
        img.save(image_path, quality=95)
        print(f"      ✔ Saved at quality=95.")

        print()
        print("=" * 65)
        print("  POSTER ENGINE: Text overlay COMPLETE ✔")
        print("=" * 65)
        print()
        return True

    except Exception as e:
        print(f"\n[ERROR] Poster engine failed: {e}")
        traceback.print_exc()
        return False


# --- 5. MESSAGE DICTS (poster delivery flow — unchanged) ---

# Language-aware messages for the poster delivery flow
_LOADING_MSGS = {
    "gujarati": "રાહ જુઓ...",
    "hindi":    "कृपया प्रतीक्षा करें...",
    "english":  "Wait...",
    "hinglish": "Wait...",
}
_SUCCESS_MSGS = {
    "gujarati": "આ રહ્યું તમારું demo poster!\n\nઆવા સરસ poster દરરોજ automatic મેળવવા માટે આજે જ ₹499 નો plan activate કરો.",
    "hindi":    "यह रहा आपका demo poster!\n\nऐसे शानदार poster रोज़ पाने के लिए आज ही ₹499 का plan activate करें।",
    "english":  "Here is your demo poster!\n\nActivate the ₹499 plan today to receive premium branded posters like this every single day.",
    "hinglish": "Yeh lo aapka demo poster!\n\nAise shandaar poster daily paane ke liye aaj hi ₹499 wala plan activate karo.",
}
_ERROR_MSGS = {
    "gujarati": "Maaf karjo, poster banavaama technical khaami aavi chhe. Krupa kari thodi var pachhi prayas karo.",
    "hindi":    "Maaf kijiye, poster banane mein technical dikkat aayi. Thodi der mein phir try karein.",
    "english":  "Sorry, there was a technical issue creating your poster. Please try again in a moment.",
    "hinglish": "Maaf kijiye, poster mein technical problem aayi. Thodi der baad try karein.",
}

# Caption sent alongside the QR code image after user confirms they liked the poster
_QR_CAPTION = (
    "તમારું poster તૈયાર છે. જો તમે ઈચ્છો છો કે આવા professional posters રોજ તમારા "
    "WhatsApp પર મળે, તો અમારો ₹499 નો yearly plan activate કરી શકો છો.\n\n"
    "🔴 પ્રીમિયમ ડિજિટલ પેક - ફક્ત ₹499/-\n"
    "🔥 એટલી ઓછી કિંમતમાં સંપૂર્ણ ડિજિટલ માર્કેટિંગ સેટઅપ! 🔥\n"
    "🚀 રોજિંદા ફેસ્ટિવલ વીડિયો અને પોસ્ટર\n"
    "📢 બિઝનેસ પ્રમોશનલ પોસ્ટર\n"
    "🖼️ 2 કસ્ટમ ફ્રેમ (તમારા નામ સાથે)\n"
    "🎨 પ્રોફેશનલ લોગો ડિઝાઇન\n"
    "💳 ડિજિટલ વિઝિટિંગ કાર્ડ\n"
    "📲 રોજ પોસ્ટર અને વીડિયો સીધા WhatsApp પર\n"
    "⏳ આખા 1 વર્ષ માટે માન્ય\n"
    "💥 એટલે કે એક વખત પેમેન્ટ – આખું વર્ષ ટેન્શન ફ્રી!\n\n"
    "Payment કરવા માટે ઉપર આપેલા QR Code અથવા નીચે આપેલી UPI ID પર payment કરો "
    "અને screenshot મોકલો.\n"
    "UPI ID: <YOUR_UPI_ID_HERE>"
)

# Button title for the confirmation interactive message (WhatsApp max = 20 chars)
_CONFIRM_BTN_LABELS = {
    "gujarati": "Generate Demo Poster",
    "hindi":    "Generate Demo Poster",
    "english":  "Generate Demo Poster",
    "hinglish": "Generate Demo Poster",
}

# --- 6. STATE MACHINE MESSAGE DICTS ---

_GREETING_MSG = (
    "Namaste! Main Brandnio ka AI Consultant hoon. "
    "Aap kis language mein baat karna chahte hain? (Gujarati / Hindi / English)"
)

_LANG_UNCLEAR_MSG = (
    "Sorry, I didn't catch that. "
    "Please reply with your preferred language: Gujarati / Hindi / English"
)

_WELCOME_MSGS = {
    "gujarati": (
        "Hello! Brandnio માં તમારું સ્વાગત છે.\n\n"
        "અમે તમારા business માટે દરરોજ festival અને promotion posters બનાવીએ છીએ.\n\n"
        "શું તમારે અમારા કેટલાક demo sample posters જોવા છે? બોલો, બતાવું?"
    ),
    "hindi": (
        "Hello! Brandnio mein aapka swagat hai.\n\n"
        "Hum aapke business ke liye daily festival aur promotion posters banate hain.\n\n"
        "Kya aap hamare kuch demo sample posters dekhna chahte hain? Bataun kya?"
    ),
    "english": (
        "Hello! Welcome to Brandnio.\n\n"
        "We create daily festival and promotion posters for your business.\n\n"
        "Would you like to see some of our demo sample posters? Just say the word!"
    ),
    "hinglish": (
        "Hello! Brandnio mein aapka swagat hai.\n\n"
        "Hum aapke business ke liye daily festival aur promotion posters banate hain.\n\n"
        "Kya aap hamare kuch demo sample posters dekhna chahte hain? Bataun kya?"
    ),
}

_ASK_DEMO_MSGS = {
    "gujarati": "શું તમારે તમારા business ને લગતો FREE demo poster બનાવવો છે? બોલો, બનાવું?",
    "hindi":    "Kya aap apne business ke liye ek FREE demo poster banvana chahte hain? Bol dijiye, bana deta hoon!",
    "english":  "Would you like us to create a FREE demo poster for your business? Just let me know!",
    "hinglish": "Kya aap apne business ke liye ek FREE demo poster banvana chahte hain? Bol dijiye, bana deta hoon!",
}

_COLLECT_DETAILS_MSGS = {
    "gujarati": (
        "ખૂબ સરસ! કૃપા કરીને તમારા business ની આ details એકસાથે મોકલો:\n\n"
        "1. Owner / Proprietor નું નામ\n"
        "2. Business / Shop નું નામ\n"
        "3. Mobile Number\n"
        "4. Address\n"
        "5. Other / અન્ય વિગત (tagline, offer, etc.) — ન હોય તો 'No' લખો"
    ),
    "hindi": (
        "Bahut badhiya! Kripaya apne business ki ye details ek saath bhejein:\n\n"
        "1. Owner / Proprietor ka naam\n"
        "2. Business / Shop ka naam\n"
        "3. Mobile Number\n"
        "4. Address\n"
        "5. Other / Anya vivaran (tagline, offer, etc.) — nahi ho to 'No' likhein"
    ),
    "english": (
        "Great! Please send your business details together:\n\n"
        "1. Owner / Proprietor Name\n"
        "2. Business / Shop Name\n"
        "3. Mobile Number\n"
        "4. Address\n"
        "5. Other details (tagline, offer, etc.) — if none, just write 'No'"
    ),
    "hinglish": (
        "Bahut badhiya! Kripaya apne business ki ye details ek saath bhejein:\n\n"
        "1. Owner / Proprietor ka naam\n"
        "2. Business / Shop ka naam\n"
        "3. Mobile Number\n"
        "4. Address\n"
        "5. Other details (tagline, offer, etc.) — nahi ho to 'No' likhein"
    ),
}

_REASK_DETAILS_MSGS = {
    "gujarati": (
        "માફ કરો, મને તમારી details સમજાઈ નહીં. "
        "કૃપા કરીને આ format માં ફરીથી મોકલો:\n\n"
        "1. Owner નું નામ\n2. Business / Shop નું નામ\n3. Mobile Number\n"
        "4. Address\n5. Other (tagline, offer, etc.) — ન હોય તો 'No'"
    ),
    "hindi": (
        "Maaf kijiye, mujhe aapki details samajh nahi aayi. "
        "Kripaya is format mein dobara bhejein:\n\n"
        "1. Owner ka naam\n2. Business / Shop ka naam\n3. Mobile Number\n"
        "4. Address\n5. Other (tagline, offer) — nahi ho to 'No'"
    ),
    "english": (
        "Sorry, I couldn't understand your details. "
        "Please resend in this format:\n\n"
        "1. Owner Name\n2. Business / Shop Name\n3. Mobile Number\n"
        "4. Address\n5. Other details — if none, write 'No'"
    ),
    "hinglish": (
        "Maaf kijiye, mujhe aapki details samajh nahi aayi. "
        "Kripaya is format mein dobara bhejein:\n\n"
        "1. Owner ka naam\n2. Business / Shop ka naam\n3. Mobile Number\n"
        "4. Address\n5. Other (tagline, offer) — nahi ho to 'No'"
    ),
}

_NO_DEMO_MSGS = {
    "gujarati": "ઠીક છે! જ્યારે પણ તૈયાર હો ત્યારે contact કરો. આભાર!",
    "hindi":    "Theek hai! Jab bhi taiyar ho, hum yahan hain. Shukriya!",
    "english":  "No problem! Reach out whenever you are ready. Thank you!",
    "hinglish": "Theek hai! Jab bhi taiyar ho, contact karein. Shukriya!",
}

_CONFIRM_REMINDER_MSGS = {
    "gujarati": "કૃપા કરીને ઉપર આપેલ button tap કરો — demo poster ready થઈ જશે.",
    "hindi":    "Kripaya upar diye gaye button ko tap karein — demo poster taiyar ho jaayega.",
    "english":  "Please tap the button above to generate your demo poster.",
    "hinglish": "Kripaya upar diye gaye button ko tap karein — demo poster taiyar ho jaayega.",
}

_FEEDBACK_QUESTION_MSGS = {
    "gujarati": "શું તમને અમારા પોસ્ટરો સારા લાગ્યા? તમને કેવા લાગ્યા?",
    "hindi":    "Kya aapko hamare posters achhe lage? Kaisa laga aapko?",
    "english":  "Did you like our posters? How did you find them?",
    "hinglish": "Kya aapko hamare posters achhe lage? Kaisa laga aapko?",
}

_PAYMENT_WAIT_MSGS = {
    "gujarati": "Plan activate કરવા માટે payment screenshot મોકલો.",
    "hindi":    "Plan activate karne ke liye payment screenshot bhejein.",
    "english":  "Please send the payment screenshot to activate your plan.",
    "hinglish": "Plan activate karne ke liye payment screenshot bhejein.",
}

_PAYMENT_THANKS_MSGS = {
    "gujarati": (
        "ખૂબ ખૂબ આભાર! તમારું payment મળી ગયું. "
        "તમારું Brandnio plan 24 કલાકમાં activate થઈ જશે. "
        "કોઈ સવાલ હોય તો contact કરો."
    ),
    "hindi": (
        "Bahut bahut shukriya! Aapka payment mil gaya. "
        "Aapka Brandnio plan 24 ghante mein activate ho jaayega. "
        "Koi sawaal ho to contact karein."
    ),
    "english": (
        "Thank you so much! Your payment has been received. "
        "Your Brandnio plan will be activated within 24 hours. "
        "Feel free to reach out if you have any questions."
    ),
    "hinglish": (
        "Bahut bahut shukriya! Aapka payment mil gaya. "
        "Aapka Brandnio plan 24 ghante mein activate ho jaayega. "
        "Koi sawaal ho to contact karein."
    ),
}

_HUMAN_HANDOFF_MSGS = {
    "gujarati": "કૃપા કરીને રાહ જુઓ, અમારા executive થોડીવારમાં તમારી સાથે વાત કરશે.",
    "hindi":    "Kripaya rukhiye, hamare executive thodi der mein aapse baat karenge.",
    "english":  "Please wait, our executive will get in touch with you shortly.",
    "hinglish": "Kripaya rukhiye, hamare executive thodi der mein aapse baat karenge.",
}

_ASK_ANOTHER_POSTER_MSG = {
    "gujarati": "તમારું પોસ્ટર આવી ગયું છે. શું તમારે અન્ય ડિટેલ્સ સાથે ફરી બીજું કોઈ ડેમો સેમ્પલ બનાવવું છે? બોલો, એક વધુ બનાવું?",
    "hindi":    "Aapka poster aa gaya hai. Kya aap alag details ke saath ek aur demo poster banana chahte hain? Bolo, ek aur bana doon?",
    "english":  "Your poster is ready. Would you like to create another demo poster with different details? Just say the word!",
    "hinglish": "Aapka poster aa gaya hai. Kya aap alag details ke saath ek aur demo poster banana chahte hain? Bolo, ek aur bana doon?",
}

_ASK_MORE_INFO_MSGS = {
    "gujarati": "બહુ સરસ! તમારી details મળી ગઈ. કોઈ extra tagline, offer, કે ખાસ info ઉમેરવી છે? ન હોય તો 'No' કહો.",
    "hindi":    "Bahut badhiya! Aapki details mil gayi. Koi extra tagline, offer, ya khaas info add karni hai? Nahi ho to 'No' bol dijiye.",
    "english":  "Great! Got your details. Would you like to add any tagline, offer, or specific info to the poster? If not, just say No.",
    "hinglish": "Bahut badhiya! Aapki details mil gayi. Koi extra tagline, offer, ya khaas info add karni hai? Nahi ho to 'No' bol dijiye.",
}

_ASK_USE_SAVED_MSGS = {
    "gujarati": "તમારી પહેલાની details હજુ save છે. એ જ details વાપરવી છે કે નવી details આપશો? (જૂની / નવી)",
    "hindi":    "Aapki pehle wali details abhi bhi save hain. Wohi use karein ya naye details denge? (Purani / Nayi)",
    "english":  "Your previous details are still saved. Use the same details or provide new ones? (Old / New)",
    "hinglish": "Aapki pehle wali details abhi bhi save hain. Wohi use karein ya naye details denge? (Purani / Nayi)",
}


# --- 7. STATE MACHINE HELPERS ---

def _detect_language(text):
    """
    Detect language from user's reply to the language selection prompt.
    Returns "gujarati", "hindi", "english", or None (unrecognised → re-ask).
    """
    t = text.lower().strip()
    # Full-word matches first
    if any(k in t for k in ["gujarati", "guj", "gujrati", "gujarti"]):
        return "gujarati"
    if any(k in t for k in ["hindi", "hind"]):
        return "hindi"
    if any(k in t for k in ["english", "eng", "angrezi"]):
        return "english"
    # Single-char / numeric shortcuts
    if t in ("gu", "g", "1"):
        return "gujarati"
    if t in ("hi", "h", "2"):
        return "hindi"
    if t in ("en", "e", "3"):
        return "english"
    return None   # unrecognised — caller will re-ask


def _is_yes(text):
    """Return True if the text is an affirmative reply (word-boundary matching)."""
    t = text.strip()
    return bool(re.search(
        r'\b(?:'
        r'yes|ha|haa|haan|ok|okay|ji|jii|bilkul'
        r'|ha ji|haji|zaroor|sure|haan ji|હા|हाँ|हां'
        r'|theek hai|thik hai|theek|thik|chalo|chalega'
        r'|karo|kar do|bana do|banao|ban jaye|banawo|banavo'
        r'|ho|hoji|sahi|accha|acha|badhiya|perfect'
        r'|correct|right|done|go ahead|proceed'
        r'|batao|bataao|batawo|dikha|dikhao'
        r'|please|pls|ya|yep|yup|yeah'
        r'|karo na|ready|le lo|moklo|ha banai do'
        r'|બનાવો|ચાલો|સારું|ઠીક|ઠીક છે'
        r'|हां जी|ठीक|ठीक है|अच्छा|बनाओ|करो'
        r')\b', t, re.IGNORECASE
    ))


def _is_no(text):
    """Return True if the text is a negative reply (word-boundary matching)."""
    t = text.strip()
    return bool(re.search(
        r'\b(?:'
        r'no|na|nahi|nai|nope|ni|naa|nahin'
        r'|nahi hai|ना|ના'
        r'|rehne do|rehne de|rehen de|chhodo|chod do|chord do'
        r'|bas|nahi chahiye|nhi chahiye|mat karo|mat karna'
        r'|mujhe nahi|nathi|na joiye|nako'
        r'|not now|later|baad mein|abhi nahi'
        r'|cancel|skip|pass|leave it'
        r'|રહેવા દો|નથી જોઈતું|છોડો'
        r'|रहने दो|नहीं चाहिए|मत करो|बस'
        r')\b', t, re.IGNORECASE
    ))


def _is_frustration(text):
    """Return True if the message signals frustration or a human-handoff request."""
    t = text.lower()
    triggers = [
        "human", "agent", "manager", "complaint", "fraud", "scam",
        "fake", "support", "helpline", "operator", "real person",
        "speak to someone", "talk to someone",
    ]
    return any(k in t for k in triggers)


def _is_retry_request(text):
    """Return True if the message signals the user wants another poster."""
    t = text.lower().strip()
    return any(k in t for k in [
        "another poster", "ek aur", "ek or", "fari banao", "fari banavo",
        "aur poster", "naya poster", "naya", "navi", "new poster",
        "one more", "ek aur bana", "again", "dobara",
        "bija poster", "biju poster", "bijhu",
        "ફરી બનાવો", "બીજું", "નવું", "एक और", "नया", "दोबारा",
    ])


# ── State context map for intent classification ────────────────────────────
_STATE_CONTEXT = {
    1:  ("Asked if they want to see sample posters", "So, shall I show you our samples?"),
    2:  ("Asked if they want a free demo poster for their business", "Shall I create a free demo poster for you?"),
    4:  ("Shown a confirmation button to generate the poster — waiting for button tap", "Please tap the button above to generate your poster."),
    6:  ("Poster delivered, asked if they liked it", "So, did you like the poster?"),
    7:  ("QR code sent for payment, waiting for payment screenshot", "Please send the payment screenshot to activate your plan."),
    9:  ("Asked if they want another demo poster", "Would you like another poster?"),
    10: ("Asked if they want to add extra tagline/offer info", "Any extra info for the poster, or shall we proceed?"),
    11: ("Asked if they want to add extra tagline/offer info", "Any extra info for the poster, or shall we proceed?"),
    12: ("Asked if they want to reuse old details or provide new ones", "Use old details or provide new ones?"),
}

_LANG_NAMES = {"gujarati": "Gujarati", "hindi": "Hindi", "english": "English", "hinglish": "Hinglish"}


def analyze_intent_with_gemini(user_text, current_state, lang):
    """
    AI-powered intent classifier & FAQ answerer.
    Returns {"intent": str, "ai_answer": str}.
    intent is one of: YES, NO, DETAILS_PROVIDED, QUESTION, GREETING, UNKNOWN.
    ai_answer is non-empty only when intent == QUESTION.
    Falls back to {"intent": "UNKNOWN", "ai_answer": ""} on any failure.
    """
    fallback = {"intent": "UNKNOWN", "ai_answer": ""}

    if _gemini_text_client is None:
        return fallback

    ctx_desc, ctx_nudge = _STATE_CONTEXT.get(current_state, ("In conversation", ""))
    lang_name = _LANG_NAMES.get(lang, "Hinglish")

    system_prompt = (
        "You are an intent classifier for Brandnio, a premium AI poster business.\n\n"
        "BUSINESS CONTEXT:\n"
        "- Brandnio offers a Rs.499/year plan\n"
        "- Plan includes: daily festival & promotional posters with business branding, "
        "2 custom frames, professional logo design, digital visiting card\n"
        "- All content delivered directly via WhatsApp\n"
        "- Free demo: users can get up to 3 free demo posters before subscribing\n\n"
        f"The user is currently at this stage: {ctx_desc}\n"
        f"Their language preference is: {lang_name}\n\n"
        "Classify the user's message into EXACTLY ONE of these intents:\n"
        "- YES: agreeing, accepting, confirming, or expressing interest "
        "(even indirectly, e.g. 'Can you make one for my shop?' = YES, "
        "'Yes please make a demo for me' = YES, 'mujhe banana hai' = YES)\n"
        "- NO: declining, refusing, or not interested\n"
        "- DETAILS_PROVIDED: providing business information (name, number, address, etc.)\n"
        "- QUESTION: asking about the service, pricing, delivery, poster quality, etc.\n"
        "- GREETING: just saying hello, hi, namaste, or a casual greeting\n\n"
        "If intent is QUESTION:\n"
        f"- Write a short, friendly answer in {lang_name} (2-3 sentences max)\n"
        "- You are Sandip, a human sales consultant at Brandnio. NEVER say you are AI or a bot.\n"
        "- Be warm and professional. Use short sentences.\n"
        f"- End with a gentle nudge: {ctx_nudge}\n\n"
        "Return ONLY valid JSON: {\"intent\": \"...\", \"ai_answer\": \"...\"}\n"
        "For non-QUESTION intents, set ai_answer to empty string.\n"
        "Do NOT wrap in ```json``` code fences. No markdown. No extra text."
    )

    try:
        response = _gemini_text_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_text,
            config={
                "system_instruction": system_prompt,
                "temperature": 0.0,
                "max_output_tokens": 300,
            },
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = _json.loads(raw)
        intent = str(result.get("intent", "UNKNOWN")).upper()
        ai_answer = str(result.get("ai_answer", "")).strip()

        if intent not in ("YES", "NO", "DETAILS_PROVIDED", "QUESTION", "GREETING"):
            intent = "UNKNOWN"

        print(f"[analyze_intent] intent={intent}, ai_answer_len={len(ai_answer)}")
        return {"intent": intent, "ai_answer": ai_answer}

    except Exception as e:
        print(f"[analyze_intent] Gemini failed: {e} — returning UNKNOWN.")
        return fallback


def _parse_details_basic(text):
    """
    Basic positional parser — fallback when Gemini extraction is unavailable.

    Expected user format (flexible — handles missing numbers / extra whitespace):
      1. Owner Name
      2. Business Name
      3. Mobile Number
      4. Address
      5. Other / tagline  (or 'No')

    Returns dict keys: owner_name, business_name, mobile, address,
    other_details, category (inferred = business_name for image generation).
    Never raises — returns empty strings for any unparsed fields.
    """
    try:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        clean = []
        for line in lines:
            # Strip leading "1. " / "1) " / "1 - " style prefixes
            m = re.match(r'^[1-5][\.\)\-]\s*(.+)$', line)
            if m:
                clean.append(m.group(1).strip())
            else:
                clean.append(line)

        owner_name    = clean[0] if len(clean) > 0 else ""
        business_name = clean[1] if len(clean) > 1 else ""
        mobile        = clean[2] if len(clean) > 2 else ""
        address       = clean[3] if len(clean) > 3 else ""
        raw_other     = clean[4] if len(clean) > 4 else ""
        other_details = "" if _is_no(raw_other) else raw_other

        return {
            "owner_name":    owner_name,
            "business_name": business_name,
            "mobile":        mobile,
            "address":       address,
            "other_details": other_details,
            "category":      business_name,
        }
    except Exception as e:
        print(f"[_parse_details_basic] Parse error: {e}")
        return {
            "owner_name": "", "business_name": "", "mobile": "",
            "address": "", "other_details": "", "category": "",
        }


def _extract_details_with_gemini(raw_text, lang="hinglish"):
    """
    Use Gemini 2.5 Flash to extract structured business details from
    free-form user text. Returns the same dict shape as _parse_details_basic().
    Falls back to _parse_details_basic() on any API failure.
    """
    if _gemini_text_client is None:
        print("[_extract_details_with_gemini] No Gemini client — falling back to basic parser.")
        return _parse_details_basic(raw_text)

    system_prompt = (
        "You are a structured data extractor. The user has sent a WhatsApp message "
        "containing their business details — possibly in Hindi, Gujarati, English, or Hinglish. "
        "Extract EXACTLY these 5 fields from the text. Strip all conversational filler "
        "(e.g., 'Mera naam Ankur hai' → just 'Ankur'). "
        "Return ONLY valid JSON with these exact keys:\n"
        '{"owner_name": "...", "business_name": "...", "mobile": "...", '
        '"address": "...", "other_details": "..."}\n\n'
        "Rules:\n"
        "- If a field is not found, use an empty string.\n"
        "- mobile should contain only digits (strip +91, spaces, dashes).\n"
        "- other_details captures any tagline, offer, or extra info. If user wrote 'No' or nothing, use empty string.\n"
        "- Do NOT add any explanation, markdown, or text outside the JSON object.\n"
        "- Do NOT wrap in ```json``` code fences."
    )

    try:
        response = _gemini_text_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Extract business details from this message:\n\n{raw_text}",
            config={
                "system_instruction": system_prompt,
                "temperature": 0.0,
                "max_output_tokens": 300,
            },
        )
        raw_json = response.text.strip()
        # Strip markdown code fences if Gemini adds them anyway
        if raw_json.startswith("```"):
            raw_json = raw_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = _json.loads(raw_json)

        result = {
            "owner_name":    str(parsed.get("owner_name", "")).strip(),
            "business_name": str(parsed.get("business_name", "")).strip(),
            "mobile":        re.sub(r"[^\d]", "", str(parsed.get("mobile", ""))),
            "address":       str(parsed.get("address", "")).strip(),
            "other_details": str(parsed.get("other_details", "")).strip(),
            "category":      str(parsed.get("business_name", "")).strip(),
        }
        if _is_no(result["other_details"]):
            result["other_details"] = ""

        print(f"[_extract_details_with_gemini] Gemini extracted: {result}")
        return result

    except Exception as e:
        print(f"[_extract_details_with_gemini] Gemini failed: {e} — falling back to basic parser.")
        return _parse_details_basic(raw_text)


def _send_samples(phone, host_url):
    """Send configured sample images and videos — skips missing files."""
    for fname in SAMPLE_IMAGES:
        fpath = os.path.join("samples", fname)
        if not os.path.isfile(fpath):
            print(f"[_send_samples] Skipping missing image: {fpath}")
            continue
        try:
            send_whatsapp_image_only(phone, f"{host_url}samples/{fname}")
        except Exception as e:
            print(f"[_send_samples] Error sending image {fname}: {e}")
    for fname in SAMPLE_VIDEOS:
        fpath = os.path.join("samples", fname)
        if not os.path.isfile(fpath):
            print(f"[_send_samples] Skipping missing video: {fpath}")
            continue
        try:
            send_whatsapp_video(phone, f"{host_url}samples/{fname}")
        except Exception as e:
            print(f"[_send_samples] Error sending video {fname}: {e}")


# --- 8. CONFIRMATION SUMMARY BUILDER ---

def _build_confirmation_summary(details, lang):
    """Build the interactive button body text summarising all collected fields."""
    biz   = details.get("business_name", "")
    owner = details.get("owner_name", "")
    mob   = details.get("mobile", "")
    addr  = details.get("address", "")
    other = details.get("other_details", "") or ""

    if lang == "gujarati":
        lines = [
            "તમારી વિગત confirm કરો:",
            f"બિઝનેસ: {biz}",
            f"માલિક: {owner}",
            f"મોબાઈલ: {mob}",
            f"સરનામું: {addr}",
        ]
        if other:
            lines.append(f"ટેગલાઇન: {other}")
        lines.append("\nબધું સાચું લાગે તો button tap કરો!")
    elif lang == "hindi":
        lines = [
            "अपनी जानकारी confirm करें:",
            f"बिजनेस: {biz}",
            f"मालिक: {owner}",
            f"मोबाइल: {mob}",
            f"पता: {addr}",
        ]
        if other:
            lines.append(f"टैगलाइन: {other}")
        lines.append("\nसही लगे तो button tap करें!")
    else:   # english / hinglish
        lines = [
            "Please confirm your details:",
            f"Business: {biz}",
            f"Owner: {owner}",
            f"Mobile: {mob}",
            f"Address: {addr}",
        ]
        if other:
            lines.append(f"Tagline: {other}")
        lines.append("\nAll correct? Tap the button to generate your poster!")

    return "\n".join(lines)


# --- 9. CORE STATE MACHINE ---

def handle_state_machine(sender_phone, user_text, host_url):
    """
    Central dispatcher for all inbound text messages.
    Runs in a background daemon thread dispatched by webhook().

    State transitions:
      None → 0 (greeting sent)
      0    → 1 (language locked, welcome + samples-Q sent)
      1    → 2 (samples sent if yes, demo-Q sent)
      2    → 3 (yes to demo: collect-details prompt)  |  8 (no: close)
      3    → 4 (details parsed, confirmation button shown)
      4    → stays 4 (text reminder — tap the button)
      5    → stays 5 (silent ignore while worker runs)
      6    → 7 (yes: QR sent)  |  8 (no: close)
      7    → stays 7 (text: remind to send screenshot)
      8    → 0 (restart — treated as new user)
      any  → handoff (frustration keyword detected)
    """
    # ── Frustration / human-handoff check — fires at ANY state ───────────────
    if _is_frustration(user_text):
        lang = user_states.get(sender_phone, {}).get("lang", "hinglish")
        send_whatsapp_message(
            sender_phone,
            _HUMAN_HANDOFF_MSGS.get(lang, _HUMAN_HANDOFF_MSGS["hinglish"]),
        )
        human_mode_users.add(sender_phone)
        print(f"[{sender_phone}] Added to human_mode_users after frustration signal.")
        return

    # ── Global Jumper: detect "another poster" request at ANY state ────────
    state_rec_peek = user_states.get(sender_phone)
    if (state_rec_peek is not None
            and state_rec_peek["state"] not in (STATE_GENERATING, STATE_GREETING)
            and _is_retry_request(user_text)):
        lang = state_rec_peek.get("lang", "hinglish")
        # Demo limit guard
        if demo_limits.get(sender_phone, 0) >= DEMO_LIMIT_MAX:
            send_whatsapp_message(sender_phone, _DEMO_LIMIT_MSG_LANG.get(lang, _DEMO_LIMIT_MSG_LANG["hinglish"]))
            return
        # Smart retry: check for saved details
        saved = state_rec_peek.get("saved_details")
        if saved:
            user_states[sender_phone]["state"] = STATE_ASK_USE_SAVED
            send_whatsapp_message(
                sender_phone,
                _ASK_USE_SAVED_MSGS.get(lang, _ASK_USE_SAVED_MSGS["hinglish"]),
            )
            print(f"[{sender_phone}] Global jumper: retry request detected. Saved details found. State → 12.")
        else:
            user_states[sender_phone]["state"] = STATE_COLLECT
            send_whatsapp_message(
                sender_phone,
                _COLLECT_DETAILS_MSGS.get(lang, _COLLECT_DETAILS_MSGS["hinglish"]),
            )
            print(f"[{sender_phone}] Global jumper: retry request detected. No saved details. State → 3.")
        return

    state_rec = user_states.get(sender_phone)

    # ── STATE 8 (done) — answer questions, otherwise restart as new user ─────
    if state_rec is not None and state_rec["state"] == STATE_DONE:
        done_lang = state_rec.get("lang", "hinglish")
        done_intent = analyze_intent_with_gemini(user_text, STATE_DONE, done_lang)
        if done_intent["intent"] == "QUESTION" and done_intent.get("ai_answer"):
            send_whatsapp_message(sender_phone, done_intent["ai_answer"])
            print(f"[{sender_phone}] STATE_DONE: question answered, staying in done state.")
            return
        # Greeting or restart intent — delete state and restart flow
        del user_states[sender_phone]
        state_rec = None

    # ── No state record → new user → send greeting ───────────────────────────
    if state_rec is None:
        user_states[sender_phone] = {"state": STATE_GREETING, "lang": "hinglish"}
        send_whatsapp_message(sender_phone, _GREETING_MSG)
        print(f"[{sender_phone}] New user — greeting sent, state=0.")
        return

    state = state_rec["state"]
    lang  = state_rec.get("lang", "hinglish")

    # ── AI Intent Analysis (skip states where it is irrelevant) ─────────────
    intent = "UNKNOWN"
    _INTENT_SKIP_STATES = {STATE_GREETING, STATE_COLLECT, STATE_GENERATING}

    if state not in _INTENT_SKIP_STATES:
        intent_result = analyze_intent_with_gemini(user_text, state, lang)
        intent = intent_result.get("intent", "UNKNOWN")
        ai_answer = intent_result.get("ai_answer", "")

        if intent == "QUESTION" and ai_answer:
            send_whatsapp_message(sender_phone, ai_answer)
            print(f"[{sender_phone}] Intent=QUESTION at state {state}. AI answered. State unchanged.")
            return
        # YES, NO, DETAILS_PROVIDED, GREETING, UNKNOWN → fall through to normal processing

    # ── STATE 0: Waiting for language selection ───────────────────────────────
    if state == STATE_GREETING:
        detected = _detect_language(user_text)
        if detected is None:
            send_whatsapp_message(sender_phone, _LANG_UNCLEAR_MSG)
            print(f"[{sender_phone}] Language unclear — re-asking. Input: {user_text!r}")
            return
        user_states[sender_phone]["lang"]  = detected
        user_states[sender_phone]["state"] = STATE_SAMPLES_Q
        send_whatsapp_message(
            sender_phone,
            _WELCOME_MSGS.get(detected, _WELCOME_MSGS["hinglish"]),
        )
        print(f"[{sender_phone}] Language locked: {detected}. State → 1.")
        return

    # ── STATE 1: Waiting for yes/no on sample posters ────────────────────────
    if state == STATE_SAMPLES_Q:
        if intent == "YES" or (intent == "UNKNOWN" and _is_yes(user_text)):
            print(f"[{sender_phone}] User wants samples — sending...")
            _send_samples(sender_phone, host_url)
        # Whether yes or no, advance to demo question
        user_states[sender_phone]["state"] = STATE_DEMO_Q
        send_whatsapp_message(
            sender_phone,
            _ASK_DEMO_MSGS.get(lang, _ASK_DEMO_MSGS["hinglish"]),
        )
        print(f"[{sender_phone}] State → 2 (demo question).")
        return

    # ── STATE 2: Waiting for yes/no on free demo poster ──────────────────────
    if state == STATE_DEMO_Q:
        if intent == "NO" or (intent == "UNKNOWN" and _is_no(user_text)):
            send_whatsapp_message(
                sender_phone,
                _NO_DEMO_MSGS.get(lang, _NO_DEMO_MSGS["hinglish"]),
            )
            user_states[sender_phone]["state"] = STATE_DONE
            print(f"[{sender_phone}] User declined demo. State → 8 (done).")
            return
        # Default — yes / ambiguous / anything non-No → collect details
        user_states[sender_phone]["state"] = STATE_COLLECT
        send_whatsapp_message(
            sender_phone,
            _COLLECT_DETAILS_MSGS.get(lang, _COLLECT_DETAILS_MSGS["hinglish"]),
        )
        print(f"[{sender_phone}] User wants demo. State → 3 (collect details).")
        return

    # ── STATE 3: Waiting for business details text ────────────────────────────
    if state == STATE_COLLECT:
        # Demo limit guard
        if demo_limits.get(sender_phone, 0) >= DEMO_LIMIT_MAX:
            print(f"[{sender_phone}] Demo limit reached ({DEMO_LIMIT_MAX}) — blocking.")
            send_whatsapp_message(sender_phone, _DEMO_LIMIT_MSG_LANG.get(lang, _DEMO_LIMIT_MSG_LANG["hinglish"]))
            return

        parsed         = _extract_details_with_gemini(user_text, lang=lang)
        parsed["lang"] = lang

        # Quality gate — require at least owner_name AND business_name
        if not parsed.get("business_name", "").strip() or not parsed.get("owner_name", "").strip():
            print(f"[{sender_phone}] Parsed details too sparse — re-asking. Got: {parsed}")
            send_whatsapp_message(
                sender_phone,
                _REASK_DETAILS_MSGS.get(lang, _REASK_DETAILS_MSGS["hinglish"]),
            )
            return  # stay in STATE_COLLECT

        pending_poster_details[sender_phone] = parsed
        user_states[sender_phone]["state"]   = STATE_WAIT_MORE_INFO

        send_whatsapp_message(
            sender_phone,
            _ASK_MORE_INFO_MSGS.get(lang, _ASK_MORE_INFO_MSGS["hinglish"]),
        )
        print(f"[{sender_phone}] Details parsed, asking for extra info. State → 11.")
        return

    # ── STATE 10/11: Waiting for extra info or "no" ────────────────────────────
    if state in (STATE_ASK_MORE_INFO, STATE_WAIT_MORE_INFO):
        details = pending_poster_details.get(sender_phone, {})
        if intent == "NO" or (intent == "UNKNOWN" and _is_no(user_text)):
            # No extra info — proceed to confirmation
            user_states[sender_phone]["state"] = STATE_CONFIRM
            summary   = _build_confirmation_summary(details, lang)
            btn_label = _CONFIRM_BTN_LABELS.get(lang, "Generate Demo Poster")
            send_whatsapp_button_message(sender_phone, summary, btn_label, "generate_poster")
            print(f"[{sender_phone}] No extra info. Confirmation button sent. State → 4.")
        else:
            # User provided extra info — append to other_details
            existing = details.get("other_details", "") or ""
            separator = "; " if existing else ""
            details["other_details"] = existing + separator + user_text.strip()
            pending_poster_details[sender_phone] = details

            user_states[sender_phone]["state"] = STATE_CONFIRM
            summary   = _build_confirmation_summary(details, lang)
            btn_label = _CONFIRM_BTN_LABELS.get(lang, "Generate Demo Poster")
            send_whatsapp_button_message(sender_phone, summary, btn_label, "generate_poster")
            print(f"[{sender_phone}] Extra info added. Confirmation button sent. State → 4.")
        return

    # ── STATE 4: Waiting for button tap ───────────────────────────────────────
    if state == STATE_CONFIRM:
        # User typed text instead of tapping the button — remind them
        send_whatsapp_message(
            sender_phone,
            _CONFIRM_REMINDER_MSGS.get(lang, _CONFIRM_REMINDER_MSGS["hinglish"]),
        )
        return

    # ── STATE 5: Poster is being generated — ignore text ─────────────────────
    if state == STATE_GENERATING:
        print(f"[{sender_phone}] State 5 (generating) — ignoring text message.")
        return

    # ── STATE 6: Waiting for feedback yes/no ──────────────────────────────────
    if state == STATE_FEEDBACK:
        if intent == "YES" or (intent == "UNKNOWN" and _is_yes(user_text)):
            qr_path = os.path.abspath("qr_code.jpg")
            if os.path.exists(qr_path):
                qr_url = f"{host_url}qr_code.jpg"
                send_whatsapp_message(sender_phone, _QR_CAPTION, media_url=qr_url)
                print(f"[{sender_phone}] QR code sent. State → 7 (payment).")
            else:
                print(f"[{sender_phone}] WARNING: qr_code.jpg not found — sending UPI fallback.")
                send_whatsapp_message(
                    sender_phone,
                    "UPI ID: joshijigar543-1@okicici\n\nPayment karo aur screenshot bhejo.",
                )
            user_states[sender_phone]["state"] = STATE_PAYMENT
        else:
            # User not interested in plan — ask if they want another poster
            user_states[sender_phone]["state"] = STATE_RETRY
            send_whatsapp_message(
                sender_phone,
                _ASK_ANOTHER_POSTER_MSG.get(lang, _ASK_ANOTHER_POSTER_MSG["hinglish"]),
            )
            print(f"[{sender_phone}] User not interested in plan. State → 9 (retry).")
        return

    # ── STATE 7: Awaiting payment screenshot — text reminder ─────────────────
    if state == STATE_PAYMENT:
        send_whatsapp_message(
            sender_phone,
            _PAYMENT_WAIT_MSGS.get(lang, _PAYMENT_WAIT_MSGS["hinglish"]),
        )
        return

    # ── STATE 9: Asking "want another poster?" ─────────────────────────────
    if state == STATE_RETRY:
        if intent == "YES" or (intent == "UNKNOWN" and _is_yes(user_text)):
            # Demo limit guard
            if demo_limits.get(sender_phone, 0) >= DEMO_LIMIT_MAX:
                print(f"[{sender_phone}] Demo limit reached ({DEMO_LIMIT_MAX}) in retry — blocking.")
                send_whatsapp_message(sender_phone, _DEMO_LIMIT_MSG_LANG.get(lang, _DEMO_LIMIT_MSG_LANG["hinglish"]))
                user_states[sender_phone]["state"] = STATE_DONE
                return
            # Smart retry: check for saved details
            saved = user_states[sender_phone].get("saved_details")
            if saved:
                user_states[sender_phone]["state"] = STATE_ASK_USE_SAVED
                send_whatsapp_message(
                    sender_phone,
                    _ASK_USE_SAVED_MSGS.get(lang, _ASK_USE_SAVED_MSGS["hinglish"]),
                )
                print(f"[{sender_phone}] Retry: yes, saved details found → State 12.")
            else:
                user_states[sender_phone]["state"] = STATE_COLLECT
                send_whatsapp_message(
                    sender_phone,
                    _COLLECT_DETAILS_MSGS.get(lang, _COLLECT_DETAILS_MSGS["hinglish"]),
                )
                print(f"[{sender_phone}] Retry: yes, no saved details → State 3.")
            return
        elif intent == "NO" or (intent == "UNKNOWN" and _is_no(user_text)):
            send_whatsapp_message(
                sender_phone,
                _NO_DEMO_MSGS.get(lang, _NO_DEMO_MSGS["hinglish"]),
            )
            user_states[sender_phone]["state"] = STATE_DONE
            print(f"[{sender_phone}] Retry: no → State 8 (done). Farewell sent.")
            return
        else:
            # Ambiguous reply — re-ask
            send_whatsapp_message(
                sender_phone,
                _ASK_ANOTHER_POSTER_MSG.get(lang, _ASK_ANOTHER_POSTER_MSG["hinglish"]),
            )
            print(f"[{sender_phone}] Retry: unclear reply — re-asking.")
            return

    # ── STATE 12: Use saved details or new? ─────────────────────────────────
    if state == STATE_ASK_USE_SAVED:
        t = user_text.lower().strip()
        use_new = any(k in t for k in [
            "new", "navi", "nava", "nayi", "naya", "naye",
            "નવી", "નવા", "नई", "नया", "fresh", "different", "alag",
        ])

        if use_new:
            user_states[sender_phone]["state"] = STATE_COLLECT
            send_whatsapp_message(
                sender_phone,
                _COLLECT_DETAILS_MSGS.get(lang, _COLLECT_DETAILS_MSGS["hinglish"]),
            )
            print(f"[{sender_phone}] Smart retry: new details → State 3.")
            return

        # Default to old details (user said "old", "same", "juni", or anything ambiguous)
        saved = user_states[sender_phone].get("saved_details", {})
        saved_copy = dict(saved)
        saved_copy["lang"] = lang
        pending_poster_details[sender_phone] = saved_copy
        # Route through extra-info step so user can add a new tagline/offer
        user_states[sender_phone]["state"] = STATE_WAIT_MORE_INFO
        send_whatsapp_message(
            sender_phone,
            _ASK_MORE_INFO_MSGS.get(lang, _ASK_MORE_INFO_MSGS["hinglish"]),
        )
        print(f"[{sender_phone}] Smart retry: old details loaded → State 11 (ask extra info).")
        return


def _handle_payment_screenshot(sender_phone):
    """Called from webhook() when a user in STATE_PAYMENT sends an image message."""
    lang = user_states.get(sender_phone, {}).get("lang", "hinglish")
    send_whatsapp_message(
        sender_phone,
        _PAYMENT_THANKS_MSGS.get(lang, _PAYMENT_THANKS_MSGS["hinglish"]),
    )
    if sender_phone in user_states:
        user_states[sender_phone]["state"] = STATE_RETRY
    send_whatsapp_message(
        sender_phone,
        _ASK_ANOTHER_POSTER_MSG.get(lang, _ASK_ANOTHER_POSTER_MSG["hinglish"]),
    )
    print(f"[{sender_phone}] Payment screenshot received — thank-you sent. State → 9 (retry).")


# --- 10. POSTER QUEUE WORKER ---

def poster_worker():
    """
    Background worker thread — drains poster_queue one item at a time.

    Ensures only one Playwright/Chromium instance runs at any moment,
    preventing resource exhaustion when multiple users request posters simultaneously.
    """
    print("Poster worker thread started — queue ready.")
    while True:
        sender_phone, host_url = poster_queue.get()
        try:
            details  = pending_poster_details.get(sender_phone, {})
            lang     = details.get("lang", "hinglish")
            wait_msg = _LOADING_MSGS.get(lang, _LOADING_MSGS["hinglish"])
            send_whatsapp_message(sender_phone, wait_msg)
            handle_generate_poster_button(sender_phone, host_url)
        except Exception as e:
            print(f"Poster worker error for {sender_phone}: {e}")
            traceback.print_exc()
        finally:
            poster_queue.task_done()


# --- 11. PLAYWRIGHT POSTER RENDERER ---

def render_poster_playwright(image_path, business_name, owner_name, mobile, address):
    """
    Render the final poster by compositing the AI background with business text
    using a headless Chromium browser (Playwright).

    The browser's HarfBuzz shaping engine handles all Gujarati/Hindi/Indic conjuncts
    perfectly — something Pillow's BASIC layout engine cannot do.

    Returns True on success, False on any error (caller falls back to Pillow).
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return False

    try:
        # Build file:// URIs for local assets
        abs_image = os.path.abspath(image_path)
        abs_bold  = os.path.abspath(os.path.join("fonts", "NotoSansGujarati_Condensed-Bold.ttf"))
        abs_med   = os.path.abspath(os.path.join("fonts", "NotoSansGujarati_Condensed-Medium.ttf"))

        bg_uri   = abs_image.replace("\\", "/")
        font_b   = abs_bold.replace("\\", "/")
        font_m   = abs_med.replace("\\", "/")

        # Escape single quotes in user data for safe HTML embedding
        def _esc(t):
            return str(t).replace("'", "&#39;").replace("<", "&lt;").replace(">", "&gt;")

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'NotoGuj';
    src: url('file:///{font_b}') format('truetype');
    font-weight: 700;
  }}
  @font-face {{
    font-family: 'NotoGuj';
    src: url('file:///{font_m}') format('truetype');
    font-weight: 400;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 1080px; height: 1080px; overflow: hidden; }}
  .bg {{
    width: 1080px; height: 1080px;
    background: url('file:///{bg_uri}') center / cover no-repeat;
    position: relative;
  }}
  .scrim {{
    position: absolute; bottom: 0; left: 0; right: 0; height: 42%;
    background: linear-gradient(to bottom, transparent 0%, rgba(13,27,42,0.93) 100%);
  }}
  .card {{
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 28px 70px 44px;
    text-align: center;
  }}
  .biz-name {{
    font-family: 'NotoGuj', sans-serif; font-weight: 700;
    font-size: 68px; color: #D4AF37;
    line-height: 1.25;
    text-shadow: 2px 2px 8px rgba(0,0,0,0.85);
  }}
  .divider {{
    width: 84%; margin: 18px auto;
    height: 2px; background: #D4AF37; opacity: 0.9;
  }}
  .contact {{
    font-family: 'NotoGuj', sans-serif; font-weight: 400;
    font-size: 34px; color: #F5F5F5;
    line-height: 1.6;
    text-shadow: 1px 1px 5px rgba(0,0,0,0.9);
  }}
</style>
</head>
<body>
  <div class="bg">
    <div class="scrim"></div>
    <div class="card">
      <div class="biz-name">{_esc(business_name)}</div>
      <div class="divider"></div>
      <div class="contact">નામ: {_esc(owner_name)}&nbsp;&nbsp;|&nbsp;&nbsp;મોબાઈલ: {_esc(mobile)}</div>
      <div class="contact" style="margin-top:10px">સરનામું: {_esc(address)}</div>
    </div>
  </div>
</body>
</html>"""

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.set_content(html)
            page.wait_for_load_state("networkidle")
            # Save as PNG (overwrite the existing background file path)
            png_path = image_path.replace(".jpg", ".png").replace(".jpeg", ".png")
            page.screenshot(path=png_path, full_page=False)
            browser.close()

        # If a new .png was written, replace the original .jpg path reference
        if png_path != image_path and os.path.exists(png_path):
            if os.path.exists(image_path):
                os.remove(image_path)
            # Rename so the rest of the pipeline continues to use the original filename stem
            os.rename(png_path, image_path.replace(".jpg", ".png").replace(".jpeg", ".png"))
            # Signal caller to use the new path — we return the new path string on success
            # (caller already has image_filename; we just ensure the file exists at a known name)

        print("✅ Playwright render complete.")
        return True

    except Exception as e:
        print(f"⚠️  Playwright render failed: {e}")
        traceback.print_exc()
        return False


# --- 12. BUTTON-CLICK HANDLER ---

def handle_generate_poster_button(sender_phone, host_url):
    """
    Called when the user taps the 'Generate Demo Poster' button.

    Retrieves stored details from pending_poster_details, calls the
    browser-automation scraper (gemini_scraper.py) to generate the image,
    and delivers it back to the user on WhatsApp.

    After delivery, sends the feedback question (State 6).
    The QR code + payment pitch is sent only after the user confirms
    they liked the poster (State 6 → Yes → State 7).
    """
    details = pending_poster_details.get(sender_phone)
    if not details:
        print(f"⚠️  No pending poster details for {sender_phone} — ignoring button tap.")
        send_whatsapp_message(
            sender_phone,
            "Maaf kijiye, session expire ho gaya. Please aapki details dobara share karein.",
        )
        return

    lang          = details.get("lang", "hinglish")
    business_name = details["business_name"]
    owner_name    = details["owner_name"]
    mobile        = details["mobile"]
    address       = details["address"]
    category      = details["category"]

    print(f"\n🖱️  Generating poster for '{business_name}' ({sender_phone})...")
    # NOTE: loading message is already sent by poster_worker before calling this function.
    # Do NOT send it again here to avoid the user receiving it twice.

    # ── Strengthen language enforcement in the scraper prompt ──────────────
    _lang_names = {"gujarati": "Gujarati", "hindi": "Hindi", "english": "English", "hinglish": "English"}
    _enforce_lang = _lang_names.get(lang, "English")
    _lang_prefix = (
        f"CRITICAL: ALL text on the poster MUST be written STRICTLY in {_enforce_lang} script. "
        f"Do NOT use any other language or script."
    )
    existing_other = details.get("other_details", "") or ""
    details["other_details"] = f"{_lang_prefix} {existing_other}".strip()

    # ── Browser-automation image generation ──────────────────────────────────
    print(f"[{sender_phone}] Calling browser scraper (gemini_scraper.py)...")
    image_path = generate_image_from_browser(details)

    if image_path and os.path.exists(image_path):
        # Build the public URL so Meta can download it
        image_filename = os.path.basename(image_path)
        public_url     = f"{host_url}generated_images/{image_filename}"
        caption = _SUCCESS_MSGS.get(lang, _SUCCESS_MSGS["hinglish"])
        send_whatsapp_message(sender_phone, caption, media_url=public_url)
        # Persist details for smart retry — allows reuse without re-collecting
        if sender_phone in user_states:
            user_states[sender_phone]["saved_details"] = {
                "owner_name":    details.get("owner_name", ""),
                "business_name": details.get("business_name", ""),
                "mobile":        details.get("mobile", ""),
                "address":       details.get("address", ""),
                "other_details": details.get("other_details", ""),
                "category":      details.get("category", ""),
            }
        # Clear stored details after successful delivery
        pending_poster_details.pop(sender_phone, None)
        # Increment demo counter
        demo_limits[sender_phone] = demo_limits.get(sender_phone, 0) + 1
        print(f"[{sender_phone}] Demo count: {demo_limits[sender_phone]}/{DEMO_LIMIT_MAX}")
        # Transition to feedback state — QR code sent only after user confirms interest
        if sender_phone in user_states:
            user_states[sender_phone]["state"] = STATE_FEEDBACK
        feedback_q = _FEEDBACK_QUESTION_MSGS.get(lang, _FEEDBACK_QUESTION_MSGS["hinglish"])
        send_whatsapp_message(sender_phone, feedback_q)
    else:
        send_whatsapp_message(sender_phone, _ERROR_MSGS.get(lang, _ERROR_MSGS["hinglish"]))

    print(f"✅ handle_generate_poster_button complete for {sender_phone}.")


# --- 13. WEBHOOK ROUTES ---

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta webhook verification handshake."""
    if (request.args.get("hub.mode") == "subscribe" and
            request.args.get("hub.verify_token") == VERIFY_TOKEN):
        print("✅ Webhook verified.")
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive inbound WhatsApp messages / button replies and dispatch to background threads."""
    data     = request.json
    host_url = request.host_url

    try:
        if "entry" in data:
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if "messages" in value:
                        msg          = value["messages"][0]
                        sender_phone = msg["from"]

                        # ── Guard: human-handoff users get no replies ────────
                        if sender_phone in human_mode_users:
                            print(f"[{sender_phone}] Human-handoff active — message silently ignored.")
                            continue

                        if msg["type"] == "text":
                            # ── Regular text message ─────────────────────────
                            user_text = msg["text"]["body"]
                            print(f"📩 Message from {sender_phone}: {user_text}")
                            threading.Thread(
                                target=handle_state_machine,
                                args=(sender_phone, user_text, host_url),
                                daemon=True,
                            ).start()

                        elif msg["type"] == "interactive":
                            # ── Button reply ──────────────────────────────────
                            interactive = msg.get("interactive", {})
                            if interactive.get("type") == "button_reply":
                                button_id = interactive["button_reply"].get("id", "")
                                if button_id == "generate_poster":
                                    if demo_limits.get(sender_phone, 0) >= DEMO_LIMIT_MAX:
                                        _btn_lang = user_states.get(sender_phone, {}).get("lang", "hinglish")
                                        _btn_limit_msg = _DEMO_LIMIT_MSG_LANG.get(_btn_lang, _DEMO_LIMIT_MSG_LANG["hinglish"])
                                        threading.Thread(
                                            target=send_whatsapp_message,
                                            args=(sender_phone, _btn_limit_msg),
                                            daemon=True,
                                        ).start()
                                        print(f"[{sender_phone}] Demo limit reached on button tap — blocked.")
                                    else:
                                        # Mark as generating before queuing to prevent stale text replies
                                        if sender_phone in user_states:
                                            user_states[sender_phone]["state"] = STATE_GENERATING
                                        poster_queue.put((sender_phone, host_url))
                                        print(f"Queued poster generation for {sender_phone}. Queue size: {poster_queue.qsize()}")

                        elif msg["type"] == "image":
                            # ── Inbound image — payment screenshot handler ────
                            state_info = user_states.get(sender_phone, {})
                            if state_info.get("state") == STATE_PAYMENT:
                                threading.Thread(
                                    target=_handle_payment_screenshot,
                                    args=(sender_phone,),
                                    daemon=True,
                                ).start()
                                print(f"[{sender_phone}] Payment screenshot received — handling.")

    except Exception as e:
        print(f"❌ Webhook error: {e}")

    return jsonify({"status": "success"}), 200


if __name__ == "__main__":
    print("🚀 Starting Brandnio Bot Server on port 5000...")
    print(f"   Local font path checked : {os.path.abspath('fonts/NotoSansGujarati_Condensed-Bold.ttf')}")
    print(f"   Browser scraper module  : gemini_scraper.py")
    worker_thread = threading.Thread(target=poster_worker, daemon=True)
    worker_thread.start()
    app.run(port=5000, debug=True)
