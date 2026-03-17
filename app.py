import os
import time
import random
import threading
import unicodedata
import traceback
import requests
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageDraw, ImageFont, features as pil_features
import gemini_scraper

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

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("❌ GEMINI_API_KEY missing in .env file!")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# In-memory session state
conversation_history = {}

# Pending poster details — stores collected user data awaiting button confirmation
# key: sender_phone  value: dict with owner_name, business_name, mobile, address, category, lang
pending_poster_details = {}

# Playwright browser is single-instance — serialise concurrent generation requests.
_browser_lock = threading.Lock()

# Runtime folders
os.makedirs("generated_images", exist_ok=True)
os.makedirs("fonts", exist_ok=True)


# --- 2. LOCAL IMAGE SERVER ---
@app.route('/generated_images/<path:filename>')
def serve_image(filename):
    """Serve generated poster images publicly so Meta API can download them."""
    return send_from_directory('generated_images', filename)


# --- 3. WHATSAPP HELPER ---
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


# --- 5. AI POSTER GENERATION ---

def _build_image_prompt(category, business_name):
    """Return a context-aware Gemini image prompt based on business category.

    All prompts use purely visual/photographic language — no meta-instructions,
    no ALL-CAPS directives. The dark-lower-third and no-text requirements are
    encoded as natural scene descriptions so Imagen renders them, not prints them.
    """
    cat = category.lower()
    # Shared visual suffix: encodes "no text" and "dark lower third" as scene description
    _suffix = (
        "Deep natural shadows pooling heavily across the lower portion of the frame, "
        "creating a clean, dark base. The scene is a pure photographic or 3D-rendered "
        "composition with no text, no numbers, no watermarks, and no typography of any kind."
    )

    if any(kw in cat for kw in ["beauty", "salon", "ayurvedic", "herbal", "spa", "cosmetic",
                                  "skincare", "wellness", "makeup", "parlour", "parlor"]):
        theme = (
            "Elegant organic beauty and wellness studio. Marble white surface with fresh botanical "
            "sprigs, an essential oil dropper, and soft north light filtering through sheer curtains. "
            "Pastel tones — ivory, sage green, rose gold accents. Shadows deepen richly toward the "
            "bottom of the frame in a moody, cinematic fade."
        )
    elif any(kw in cat for kw in ["real estate", "builder", "construction", "property",
                                   "architecture", "realty", "housing", "infrastructure"]):
        theme = (
            "Luxury modern architectural 3D render of a premium building interior. Dramatic chiaroscuro "
            "studio lighting, deep jewel-tone palette of navy and charcoal with rich gold accents. "
            "Strong geometric perspective lines. The lower third of the frame dissolves into deep, "
            "unlit shadow in a premium real-estate campaign aesthetic."
        )
    elif any(kw in cat for kw in ["food", "restaurant", "cafe", "bakery", "hotel",
                                   "catering", "sweet", "snack", "dhaba", "kitchen"]):
        theme = (
            "Warm appetizing culinary atmosphere. Rich dark wooden table surface lit by a single warm "
            "overhead spotlight, fresh gourmet ingredients arranged artfully. Deep warm tones — mahogany, "
            "amber, cream. The bottom of the frame fades into a rich, dark mahogany shadow."
        )
    elif any(kw in cat for kw in ["jewel", "gold", "diamond", "fashion", "boutique",
                                   "clothing", "textile", "garment", "apparel"]):
        theme = (
            "Luxury fashion and jewellery showcase on dark velvet. A single dramatic spotlight picks "
            "out gold and diamond elements against a near-black background. High-end retail boutique "
            "aesthetic — black and deep gold palette. Lower portion stays in rich, velvety darkness."
        )
    elif any(kw in cat for kw in ["education", "school", "coaching", "tuition",
                                   "academy", "institute", "classes", "tutorial"]):
        theme = (
            "Modern professional education environment. Clean minimal desk with open books and a soft "
            "blue-white ambient light from above. Inspirational academic atmosphere. The base of the "
            "frame deepens into a calm, dark navy shadow."
        )
    elif any(kw in cat for kw in ["doctor", "clinic", "hospital", "medical",
                                   "pharmacy", "health", "dental", "ayurveda"]):
        theme = (
            "Clean professional healthcare setting. Soft clinical teal-white lighting on modern medical "
            "equipment, sterile surfaces, trustworthy and premium. The lower portion of the frame "
            "recedes into a deep, dark teal-charcoal shadow."
        )
    elif any(kw in cat for kw in ["auto", "car", "vehicle", "garage", "motor", "bike", "tyre"]):
        theme = (
            "Premium automotive showroom. Dramatic low-key studio lighting rakes across a sleek vehicle "
            "silhouette on a polished dark floor. Gunmetal, carbon black, and silver highlights. "
            "The floor and lower frame dissolve into deep, inky darkness."
        )
    elif any(kw in cat for kw in ["tech", "software", "it ", "computer", "digital", "app", "startup"]):
        theme = (
            "Modern technology workspace with a dark abstract bokeh background — blurred circuit-board "
            "geometry and electric blue-cyan accent lighting. Cutting-edge digital aesthetic. "
            "The lower half of the frame fades into a deep, dark navy-black gradient."
        )
    else:
        theme = (
            "Premium abstract business background. Sophisticated deep navy and gold gradient, subtle "
            "geometric light patterns in the upper half. Modern, professional, corporate atmosphere. "
            "The lower portion of the frame is a solid, unlit deep navy."
        )

    return f"{theme} {_suffix}"


# Language-aware messages for the poster delivery flow
_LOADING_MSGS = {
    "gujarati": "રાહ જુઓ...",
    "hindi":    "कृपया प्रतीक्षा करें...",
    "english":  "Wait...",
    "hinglish": "Wait...",
}
_SUCCESS_MSGS = {
    "gujarati": "Aa rahyu tamaru demo poster! 🔥\n\nAava shandaar poster darroj automatic madvaa maate aaje j ₹499 no plan activate karo.",
    "hindi":    "Yeh rahe aapka demo poster! 🔥\n\nAise shandar poster roz paane ke liye aaj hi ₹499 ka plan activate karein.",
    "english":  "Here is your demo poster! 🔥\n\nActivate the ₹499 plan today to receive premium branded posters like this every single day.",
    "hinglish": "Yeh lo aapka demo poster! 🔥\n\nAise shandaar poster daily paane ke liye aaj hi ₹499 wala plan activate karo.",
}
_ERROR_MSGS = {
    "gujarati": "Maaf karjo, poster banavaama technical khaami aavi chhe. Krupa kari thodi var pachhi prayas karo.",
    "hindi":    "Maaf kijiye, poster banane mein technical dikkat aayi. Thodi der mein phir try karein.",
    "english":  "Sorry, there was a technical issue creating your poster. Please try again in a moment.",
    "hinglish": "Maaf kijiye, poster mein technical problem aayi. Thodi der baad try karein.",
}


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


def generate_poster_demo(business_name, category, owner_name, mobile, address, host_url):
    """
    1. Calls Gemini Imagen to generate a premium background image.
    2. Overlays business details via add_text_to_poster().
    3. Saves the final composite as final_poster_{timestamp}.jpg.
    4. Returns the public URL for WhatsApp delivery.
    """
    print(f"\n🎨 Generating AI poster for '{business_name}' ({category})...")
    try:
        prompt_text = _build_image_prompt(category, business_name)
        print(f"   Prompt: {prompt_text[:120]}...")

        result = gemini_client.models.generate_images(
            model='imagen-4.0-generate-001',
            prompt=prompt_text,
            config=dict(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1"
            )
        )

        # Save raw background from Gemini
        timestamp      = int(time.time())
        image_filename = f"final_poster_{timestamp}.jpg"
        image_path     = os.path.join("generated_images", image_filename)

        for generated_image in result.generated_images:
            with open(image_path, "wb") as f:
                f.write(generated_image.image.image_bytes)

        print(f"✔ Gemini background saved: {image_path}")

        # Overlay business details — try Playwright (browser-grade Indic rendering) first,
        # fall back to Pillow if Playwright is unavailable or fails.
        print("✍️  Overlaying business details...")
        pw_ok = render_poster_playwright(image_path, business_name, owner_name, mobile, address)
        if pw_ok:
            print("✅ Playwright overlay applied.")
            # Playwright saves as .png; update image_filename + image_path to match
            if not os.path.exists(image_path):
                png_name = image_filename.replace(".jpg", ".png").replace(".jpeg", ".png")
                png_path = os.path.join("generated_images", png_name)
                if os.path.exists(png_path):
                    image_filename = png_name
                    image_path     = png_path
        else:
            print("⚠️  Playwright unavailable — falling back to Pillow overlay.")
            success = add_text_to_poster(
                image_path    = image_path,
                name          = owner_name,
                business_name = business_name,
                number        = mobile,
                address       = address,
            )
            if not success:
                print("⚠️  Pillow overlay also failed — sending plain background image.")

        print(f"✅ Final poster ready: {image_path}")

        # Public URL for WhatsApp (ngrok / production server)
        public_url = f"{host_url}generated_images/{image_filename}"
        return public_url

    except Exception as e:
        print(f"❌ Poster generation error: {e}")
        traceback.print_exc()
        return None


# --- 6. AI LOGIC (Sandip Brain) ---
SYSTEM_PROMPT = """
=== IDENTITY ===
You are a professional Sales Consultant at Brandnio — a premium brand-visual agency.
You help businesses grow their brand through high-end visual marketing.
You are NOT an AI system, chatbot, or automated tool. You are a human consultant.

FORBIDDEN at all times:
- Never say "Main AI poster generate karta hoon" or any AI self-disclosure.
- Never say "As an AI...", "I am a language model...", or similar phrases.
- When a poster is being prepared, say: "Main abhi aapka poster ready kar raha hoon, bas 2 minute..." — NOT "AI generate ho raha hai".

=== STEP-BY-STEP SALES FUNNEL (follow EXACTLY — one step at a time) ===

YOU MUST COMPLETE EACH STEP FULLY AND WAIT FOR THE USER'S REPLY BEFORE MOVING TO THE NEXT STEP.
DO NOT skip steps. DO NOT combine multiple steps into one message.

---

STEP 1 — GREETING & LANGUAGE SELECTION (MANDATORY FIRST REPLY — every new conversation)
Send this EXACT message, nothing else:
"Namaste! 🙏 Main Brandnio ka Sales Consultant Sandip hoon. Aap kis language mein baat karna chahte hain? (Gujarati / Hindi / English)"

Wait for user's reply. Once they confirm a language, LOCK IT for the entire session (see Language Lock Rule below).

---

STEP 2 — WELCOME & BUSINESS CATEGORY
After language is confirmed, send the welcome + category question in the chosen language:

Hindi:
"🙏 Hello Sir / Madam, Brandnio में आपका स्वागत है। हम आपके business के लिए daily festival और promotion posters बनाते हैं। कृपया बताइए आप कौन सा व्यवसाय करते हैं? (Example: Aggarbatti, Kirana Store, Mobile Shop, Salon, etc.)"

Gujarati:
"🙏 હેલો સર / મેડમ, Brandnio માં તમારું સ્વાગત છે. અમે તમારા business માટે દરરોજ festival અને promotion posters બનાવીએ છીએ. કૃપા કરીને જણાવો તમે કયો વ્યવસાય કરો છો? (ઉદાહરણ: અગરબત્તી, કરિયાણાની દુકાન, મોબાઈલ શોપ, સલૂન, વગેરે)"

English:
"🙏 Hello Sir / Madam, welcome to Brandnio. We create daily festival and promotion posters for your business. Please tell us what type of business you run? (Example: Grocery Store, Mobile Shop, Salon, etc.)"

Wait for user to describe their business. Note what they say as the business category.

---

STEP 3 — ASK FOR BUSINESS DETAILS
After receiving the business category, ask for all details in one message:

Hindi:
"बहुत बढ़िया 👍 कृपया अपने business की ये details भेजें:
1️⃣ Owner / Proprietor का नाम
2️⃣ Business / Shop का नाम
3️⃣ Mobile Number
4️⃣ Address
5️⃣ Email
6️⃣ Logo (अगर है तो)
7️⃣ Website (अगर है तो)"

Gujarati:
"ખૂબ સરસ 👍 કૃપા કરીને તમારા business ની આ details મોકલો:
1️⃣ Owner / Proprietor નું નામ
2️⃣ Business / Shop નું નામ
3️⃣ Mobile Number
4️⃣ Address
5️⃣ Email
6️⃣ Logo (જો હોય તો)
7️⃣ Website (જો હોય તો)"

English:
"Very good 👍 Please send your business details:
1️⃣ Owner / Proprietor Name
2️⃣ Business / Shop Name
3️⃣ Mobile Number
4️⃣ Address
5️⃣ Email
6️⃣ Logo (if available)
7️⃣ Website (if available)"

Wait for user to reply with details. Extract: owner_name, business_name, mobile, address from their reply.

---

STEP 4 — LOGO PITCH
After receiving details, check if they mentioned a logo. If they did NOT mention a logo, send:

Hindi:
"धन्यवाद Sir 👍 अगर आपके पास Logo नहीं है तो कोई बात नहीं। हमारे ₹499 वाले plan में आपके business के लिए professional logo भी बना दिया जाएगा। क्या आप logo बनवाना चाहते हैं? Reply करें: 1️⃣ हाँ 2️⃣ नहीं"

Gujarati:
"આભાર Sir 👍 જો તમારી પાસે Logo નથી તો કોઈ વાંધો નહિ. અમારા ₹499 વાળા plan માં તમારા business માટે professional logo પણ બનાવી આપવામાં આવશે. શું તમે logo બનાવવા માંગો છો? Reply કરો: 1️⃣ હા 2️⃣ ના"

English:
"Thank you Sir 👍 If you don't have a logo, no problem. Our ₹499 plan also includes a professional logo designed for your business. Would you like a logo? Reply: 1️⃣ Yes 2️⃣ No"

Wait for user's reply (Yes/No). Then proceed to Step 5.
(If they already provided a logo in Step 3, skip the logo pitch and go directly to Step 5.)

---

STEP 5 — TRIGGER DEMO POSTER GENERATION
Send the following message, then immediately call trigger_poster_generation:

Hindi:
"ठीक है Sir 👍 मैं आपके business category के अनुसार एक sample poster बनाकर भेज रहा हूँ। कृपया थोड़ा wait करें।"

Gujarati:
"ઠીક છે Sir 👍 હું તમારી business category મુજબ એક sample poster બનાવીને મોકલી રહ્યો છું. કૃપા કરીને થોડી wait કરો."

English:
"Alright Sir 👍 I am creating a sample poster based on your business category. Please wait a moment."

Then call trigger_poster_generation with ALL of the following:
- owner_name: from Step 3
- business_name: from Step 3
- mobile: from Step 3
- address: from Step 3
- category: from Step 2 (the business type the user described)
- chosen_language: the exact language selected in Step 1 (gujarati / hindi / english / hinglish)

ONLY call trigger_poster_generation after you have collected owner_name, business_name, mobile, address, and category. Do NOT call it if any of these are missing — ask for the missing fields first.

---

STEP 6 — POST-GENERATION PITCH (₹499 Plan)
Send this ONLY after the poster has been delivered, OR if the user asks about the plan or payment:

Hindi:
"✅ आपका poster तैयार है। अगर आप चाहते हैं कि ऐसे professional posters रोज़ आपके WhatsApp पर मिलें, तो हमारा ₹499 का yearly plan activate कर सकते हैं।

🔴 प्रीमियम डिजिटल पैक – सिर्फ ₹499/-
🔥 इतनी कम कीमत में पूरा डिजिटल मार्केटिंग सेटअप! 🔥
🚀 रोज़ाना फेस्टिवल वीडियो और पोस्टर
📢 बिज़नेस प्रमोशनल पोस्टर
🖼️ 2 कस्टम फ्रेम (आपके नाम के साथ)
🎨 प्रोफेशनल लोगो डिज़ाइन
💳 डिजिटल विजिटिंग कार्ड
📲 रोज़ाना पोस्टर और वीडियो सीधे WhatsApp पर
⏳ पूरे 1 साल की वैधता
💥 मतलब एक बार पेमेंट – पूरे साल टेंशन खत्म!

Payment करने के लिए नीचे दिए गए QR Code या UPI पर payment करें और screenshot भेजें।"

Gujarati:
"✅ તમારું poster તૈયાર છે. જો તમે ઇચ્છો છો કે આવા professional posters રોજ તમારા WhatsApp પર મળે, તો અમારો ₹499 નો yearly plan activate કરી શકો છો.

🔴 પ્રીમિયમ ડિજિટલ પેક – ફક્ત ₹499/-
🔥 એટલી ઓછી કિંમતમાં સંપૂર્ણ ડિજિટલ માર્કેટિંગ સેટઅપ! 🔥
🚀 રોજિંદા ફેસ્ટિવલ વીડિયો અને પોસ્ટર
📢 બિઝનેસ પ્રમોશનલ પોસ્ટર
🖼️ 2 કસ્ટમ ફ્રેમ (તમારા નામ સાથે)
🎨 પ્રોફેશનલ લોગો ડિઝાઇન
💳 ડિજિટલ વિઝિટિંગ કાર્ડ
📲 રોજ પોસ્ટર અને વીડિયો સીધા WhatsApp પર
⏳ આખા 1 વર્ષ માટે માન્ય
💥 એટલે કે એક વખત પેમેન્ટ – આખું વર્ષ ટેન્શન ફ્રી!

Payment કરવા માટે નીચે આપેલા QR Code અથવા UPI પર payment કરો અને screenshot મોકલો."

English:
"✅ Your poster is ready. If you'd like to receive such professional posters every day on WhatsApp, you can activate our ₹499 yearly plan.

🔴 Premium Digital Pack – Only ₹499/-
🔥 Complete digital marketing setup at this low price! 🔥
🚀 Daily festival videos and posters
📢 Business promotional posters
🖼️ 2 custom frames (with your name)
🎨 Professional logo design
💳 Digital visiting card
📲 Daily posters and videos directly on WhatsApp
⏳ Valid for 1 full year
💥 One-time payment — tension-free for the whole year!

To pay, use the QR Code or UPI details below and send a screenshot."

---

STEP 7 — POST-PAYMENT ONBOARDING
Send this ONLY after the user confirms payment (e.g., sends a payment screenshot or says "paid"):

Hindi:
"🎉 Congratulations Sir / Madam. आपका ₹499 वाला Brandnio Plan successfully activate हो गया है। अब से आपको daily festival और business posters WhatsApp पर मिलेंगे।
📲 App download करके register करें: [App Link].
Register करने के बाद अपना registered mobile number हमारे official WhatsApp number पर भेजें।
📞 Official Number: 6353186619"

Gujarati:
"🎉 Congratulations Sir / Madam. તમારો ₹499 વાળો Brandnio Plan successfully activate થઈ ગયો છે. હવેથી તમને daily festival અને business posters WhatsApp પર મળશે.
📲 App download કરીને register કરો: [App Link].
Register કર્યા પછી તમારો registered mobile number અમારા official WhatsApp number પર મોકલો.
📞 Official Number: 6353186619"

English:
"🎉 Congratulations Sir / Madam. Your ₹499 Brandnio Plan has been successfully activated. You will now receive daily festival and business posters on WhatsApp.
📲 Download the app and register: [App Link].
After registering, send your registered mobile number to our official WhatsApp number.
📞 Official Number: 6353186619"

---

=== LANGUAGE LOCK RULE (CRITICAL — NO EXCEPTIONS) ===
Once the user replies with their language choice in Step 1, LOCK IN permanently for the entire session.
- User chose Gujarati  → All future replies in Gujarati script ONLY.
- User chose Hindi     → All future replies in Hindi script ONLY.
- User chose English   → All future replies in English ONLY.
- User chose Hinglish  → All future replies in Hinglish (Hindi words in Roman letters).
If the user writes in a different language mid-conversation, still reply in their originally chosen language.
Default to Hinglish if preference is unclear after Step 1.

=== BOUNDARIES ===
Politely refuse GK, politics, or unrelated questions. Adapt refusal to the user's chosen language.
Hindi example: "माफ कीजिए, मैं सिर्फ Brandnio की branding services के बारे में help कर सकता हूँ।"
Gujarati example: "માફ કરશો, હું ફક્ત Brandnio ની branding services વિશે જ help કરી શકું છું."
"""

tools = [{
    "function_declarations": [
        {
            "name": "trigger_poster_generation",
            "description": (
                "Trigger ONLY when you have collected ALL 5 details: "
                "owner_name, business_name, mobile, address, AND category."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "owner_name":     {"type": "STRING", "description": "Full name of the business owner"},
                    "business_name":  {"type": "STRING", "description": "Name of the business or shop"},
                    "mobile":         {"type": "STRING", "description": "Owner's mobile number"},
                    "address":        {"type": "STRING", "description": "Business address or city"},
                    "category":        {"type": "STRING", "description": "Business category (e.g., Real Estate, Salon)"},
                    "chosen_language": {"type": "STRING", "description": "Language the user chose: english / hindi / gujarati / hinglish"},
                },
                "required": ["owner_name", "business_name", "mobile", "address", "category", "chosen_language"]
            }
        }
    ]
}]


def process_message_logic(sender_phone, user_text, host_url):
    """Background thread: process one inbound WhatsApp message through Gemini."""
    if sender_phone not in conversation_history:
        conversation_history[sender_phone] = []

    conversation_history[sender_phone].append({"role": "user", "parts": [{"text": user_text}]})

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=conversation_history[sender_phone],
            config={
                "system_instruction": SYSTEM_PROMPT,
                "tools": tools,
                "temperature": 0.7
            }
        )

        if response.candidates and response.candidates[0].content:
            conversation_history[sender_phone].append(response.candidates[0].content)

        if response.function_calls:
            tool_call = response.function_calls[0]
            if tool_call.name == "trigger_poster_generation":
                args = tool_call.args
                owner_name    = args.get("owner_name",    "")
                business_name = args.get("business_name", "")
                mobile        = args.get("mobile",        "")
                address       = args.get("address",       "")
                category      = args.get("category",      "")
                lang          = args.get("chosen_language", "hinglish").lower().strip()

                # Normalise to known key; default to hinglish
                if lang not in _LOADING_MSGS:
                    lang = "hinglish"

                print(f"\n✅ Details collected: {business_name} | {owner_name} | {mobile} | {address} | {category} | lang={lang}")

                # ── NEW FLOW ──────────────────────────────────────────────
                # Store the collected details so we can use them when the
                # user taps the "Generate Demo Poster" button.
                pending_poster_details[sender_phone] = {
                    "owner_name":    owner_name,
                    "business_name": business_name,
                    "mobile":        mobile,
                    "address":       address,
                    "category":      category,
                    "lang":          lang,
                }

                # Send the interactive button message (no poster generated yet)
                _BUTTON_BODY = {
                    "gujarati": (
                        f"✅ Tamari details confirm thai gayi!\n\n"
                        f"🏢 Business: {business_name}\n"
                        f"👤 Owner: {owner_name}\n"
                        f"📞 Mobile: {mobile}\n"
                        f"📍 Address: {address}\n"
                        f"🗂 Category: {category}\n\n"
                        "Niche button tap karo ane tamaro premium demo poster generate karo!"
                    ),
                    "hindi": (
                        f"✅ Aapki details confirm ho gayi!\n\n"
                        f"🏢 Business: {business_name}\n"
                        f"👤 Owner: {owner_name}\n"
                        f"📞 Mobile: {mobile}\n"
                        f"📍 Address: {address}\n"
                        f"🗂 Category: {category}\n\n"
                        "Neeche button tap karein aur apna premium demo poster generate karein!"
                    ),
                    "english": (
                        f"✅ Your details are confirmed!\n\n"
                        f"🏢 Business: {business_name}\n"
                        f"👤 Owner: {owner_name}\n"
                        f"📞 Mobile: {mobile}\n"
                        f"📍 Address: {address}\n"
                        f"🗂 Category: {category}\n\n"
                        "Tap the button below to generate your premium demo poster!"
                    ),
                    "hinglish": (
                        f"✅ Aapki details confirm ho gayi!\n\n"
                        f"🏢 Business: {business_name}\n"
                        f"👤 Owner: {owner_name}\n"
                        f"📞 Mobile: {mobile}\n"
                        f"📍 Address: {address}\n"
                        f"🗂 Category: {category}\n\n"
                        "Neeche button tap karo aur apna shandaar demo poster generate karo!"
                    ),
                }
                body_text = _BUTTON_BODY.get(lang, _BUTTON_BODY["hinglish"])

                send_whatsapp_button_message(
                    to_phone     = sender_phone,
                    body_text    = body_text,
                    button_label = "Generate Demo Poster",
                    button_id    = "generate_demo_poster",
                )
        else:
            send_whatsapp_message(sender_phone, response.text)

    except Exception as e:
        print(f"❌ Error in Gemini logic for {sender_phone}: {e}")
        traceback.print_exc()


# --- 7. BUTTON-CLICK HANDLER ---

def handle_generate_poster_button(sender_phone, host_url):
    """
    Called when the user taps the 'Generate Demo Poster' button.

    Retrieves stored details from pending_poster_details, calls the
    browser-automation scraper (gemini_scraper.py) to generate the image,
    and delivers it back to the user on WhatsApp.
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

    print(f"\n🖱️  Button tapped by {sender_phone} — generating poster for '{business_name}'...")

    # Let the user know generation has started
    loading_msg = _LOADING_MSGS.get(lang, _LOADING_MSGS["hinglish"])
    send_whatsapp_message(sender_phone, loading_msg)

    # ── Browser automation ───────────────────────────────────────────────────
    user_details_dict = {
        "business_name": business_name,
        "owner_name":    owner_name,
        "mobile":        mobile,
        "address":       address,
        "category":      category,
    }

    print(f"[{sender_phone}] Waiting for browser slot...")
    with _browser_lock:
        print(f"[{sender_phone}] Browser slot acquired — generating poster")
        try:
            image_path = gemini_scraper.generate_image_from_browser(user_details_dict)
        except Exception as e:
            print(f"❌ gemini_scraper error for {sender_phone}: {e}")
            traceback.print_exc()
            image_path = None

    if image_path and os.path.exists(image_path):
        # Build the public URL so Meta can download it
        image_filename = os.path.basename(image_path)
        public_url     = f"{host_url}generated_images/{image_filename}"
        send_whatsapp_image_only(sender_phone, public_url)
        # Clear stored details after successful delivery
        pending_poster_details.pop(sender_phone, None)
    else:
        send_whatsapp_message(sender_phone, _ERROR_MSGS.get(lang, _ERROR_MSGS["hinglish"]))

    print(f"✅ handle_generate_poster_button complete for {sender_phone}.")


# --- 8. WEBHOOK ROUTES ---
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

                        if msg["type"] == "text":
                            # ── Regular text message ─────────────────────────
                            user_text = msg["text"]["body"]
                            print(f"📩 Message from {sender_phone}: {user_text}")
                            threading.Thread(
                                target=process_message_logic,
                                args=(sender_phone, user_text, host_url),
                                daemon=True,
                            ).start()

                        elif msg["type"] == "interactive":
                            # ── Interactive button reply ──────────────────────
                            interactive  = msg.get("interactive", {})
                            reply_type   = interactive.get("type")          # "button_reply"
                            button_reply = interactive.get("button_reply", {})
                            button_id    = button_reply.get("id", "")

                            print(f"🖱️  Interactive reply from {sender_phone}: type={reply_type} id={button_id}")

                            if button_id == "generate_demo_poster":
                                threading.Thread(
                                    target=handle_generate_poster_button,
                                    args=(sender_phone, host_url),
                                    daemon=True,
                                ).start()
    except Exception as e:
        print(f"❌ Webhook error: {e}")

    return jsonify({"status": "success"}), 200


if __name__ == "__main__":
    print("🚀 Starting Brandnio Bot Server on port 5000...")
    print(f"   Local font path checked : {os.path.abspath('fonts/NotoSansGujarati_Condensed-Bold.ttf')}")
    print(f"   Browser scraper module  : gemini_scraper.py")
    app.run(port=5000, debug=True)
