from datetime import datetime

from flask import Blueprint, request, jsonify
from config import VERIFY_TOKEN, MANAGER_PHONE, EMPLOYEE_PHONE_MAP, VALID_EMPLOYEE_PHONES
import state
import whatsapp
import openai_helper
import sheets
import cloudinary_upload

# Flask Blueprint — registered in main.py
webhook_bp = Blueprint("webhook", __name__)

# The evening report prompt sent to employees
_EVENING_PROMPT = (
    "Shaam ki report time! Please yeh sab batao:\n\n"
    "1. Aaj kitni Brands dekhi? Aur kahan? (LinkedIn/Instagram/Facebook)\n"
    "2. Kitni Brands ko message kiya?\n"
    "3. Kitne Brands ka reply aaya?\n"
    "4. Kitne Influencers find kiye? Aur kahan?\n"
    "5. Kitne Influencers ko message kiya?\n"
    "6. Kitne Influencers ka reply aaya?\n\n"
    "Screenshot bhi bhejo!"
)


# ---------------------------------------------------------------------------
# GET /webhook — Meta webhook verification handshake
# ---------------------------------------------------------------------------

@webhook_bp.route("/webhook", methods=["GET"])
def verify():
    """Handle Meta's one-time webhook verification challenge.

    Meta sends hub.verify_token; we compare it to our VERIFY_TOKEN and
    echo back hub.challenge to confirm ownership of the endpoint.
    """
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[Webhook] Verification successful")
        return challenge, 200
    else:
        print("[Webhook] Verification FAILED — token mismatch")
        return "Forbidden", 403


# ---------------------------------------------------------------------------
# POST /webhook — Incoming messages from WhatsApp
# ---------------------------------------------------------------------------

@webhook_bp.route("/webhook", methods=["POST"])
def receive_message():
    """Process every incoming message event from Meta's webhook.

    Handles:
      - Manager commands
      - Employee text replies (report submission)
      - Employee image messages (screenshot submission)
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "no data"}), 200

        # Dig into the nested WhatsApp payload structure
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Could be a status update (delivered/read), not a message — ignore
            return jsonify({"status": "ok"}), 200

        message = messages[0]
        sender_phone = message.get("from", "")
        msg_type     = message.get("type", "")

        print(f"[Webhook] Message from {sender_phone}, type={msg_type}")

        # --- Manager command check (highest priority, only for text starting with "/") ---
        # This runs BEFORE employee routing so the manager can issue commands
        # even if their phone number is also registered as an employee.
        if msg_type == "text" and sender_phone == MANAGER_PHONE:
            body = message.get("text", {}).get("body", "").strip()
            if body.startswith("/"):
                _handle_manager_command(sender_phone, body)
                return jsonify({"status": "ok"}), 200

        # --- Employee flow (default path for all known employees) ---
        if sender_phone in VALID_EMPLOYEE_PHONES:
            if msg_type == "text":
                _handle_employee_text(sender_phone, message)
            elif msg_type == "image":
                _handle_employee_image(sender_phone, message)
            else:
                print(f"[Webhook] Unsupported message type '{msg_type}' from {sender_phone}")
            return jsonify({"status": "ok"}), 200

        # --- Manager-only (phone is manager but NOT in employee list) ---
        # Non-slash messages from the manager land here — show help hint.
        if sender_phone == MANAGER_PHONE:
            whatsapp.send_message(
                sender_phone,
                "Manager commands:\n/broadcast <message>\n/status\n/report"
            )
            return jsonify({"status": "ok"}), 200

        # --- Unknown sender ---
        print(f"[Webhook] Unknown sender {sender_phone}, ignoring")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"[Webhook] Unhandled exception: {e}")
        return jsonify({"status": "error"}), 200  # always return 200 to Meta


# ---------------------------------------------------------------------------
# Manager Command Handler
# ---------------------------------------------------------------------------

def _handle_manager_command(phone: str, body: str) -> None:
    """Handle a slash-prefixed command from the manager.

    Supported commands:
      /broadcast <message> → send the given message to every employee
      /status              → list each employee's current conversation step
      /report              → trigger the evening report flow for all employees
    """
    # Preserve original body for /broadcast argument extraction
    stripped = body.strip()
    lower = stripped.lower()
    print(f"[Webhook] Manager command: '{stripped}'")

    from config import EMPLOYEES  # local import to avoid any circularity

    # /broadcast <message>
    if lower.startswith("/broadcast"):
        # Everything after the command word becomes the broadcast text
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            whatsapp.send_message(phone, "Usage: /broadcast <your message>")
            return

        broadcast_text = parts[1].strip()
        sent = 0
        for emp in EMPLOYEES:
            if whatsapp.send_message(emp["phone"], broadcast_text):
                sent += 1
        whatsapp.send_message(phone, f"📢 Broadcast sent to {sent}/{len(EMPLOYEES)} employees.")

    # /status
    elif lower == "/status":
        lines = ["*Employee Status:*"]
        for emp in EMPLOYEES:
            step = state.get_state(emp["phone"])["step"]
            lines.append(f"• {emp['name']}: {step}")
        whatsapp.send_message(phone, "\n".join(lines))

    # /report
    elif lower == "/report":
        for emp in EMPLOYEES:
            whatsapp.send_message(emp["phone"], _EVENING_PROMPT)
            state.set_step(emp["phone"], "evening_started")
        whatsapp.send_message(phone, "✅ Evening report request sent to all employees!")

    # Unknown slash command
    else:
        whatsapp.send_message(
            phone,
            "Unknown command. Available:\n"
            "/broadcast <message> — Send message to all employees\n"
            "/status              — Show employee steps\n"
            "/report              — Request evening report from all"
        )


# ---------------------------------------------------------------------------
# Employee Text Handler
# ---------------------------------------------------------------------------

def _handle_employee_text(phone: str, message: dict) -> None:
    """Handle a text message received from a known employee.

    If the employee is in 'evening_started' step, save the report text
    and ask them to send a screenshot next.
    """
    text = message.get("text", {}).get("body", "").strip()
    emp_name = EMPLOYEE_PHONE_MAP[phone]
    current_step = state.get_state(phone)["step"]

    print(f"[Webhook] Text from {emp_name} (step={current_step}): {text[:60]}")

    if current_step == "evening_started":
        # Save raw report text; OpenAI will parse it later (when screenshot arrives)
        state.save_data(phone, "raw_report", text)
        state.set_step(phone, "waiting_screenshot")
        whatsapp.send_message(
            phone,
            "Shukriya! 🙏 Ab apna screenshot bhejo please. 📸"
        )

    elif current_step == "idle":
        # Employee texted outside of a scheduled flow
        whatsapp.send_message(
            phone,
            f"Hey {emp_name}! Abhi koi active task nahi hai. Shaam 6 baje report bhejo. 😊"
        )

    else:
        # Any other state — gentle nudge
        whatsapp.send_message(phone, "Screenshot bhejo please! 📸")


# ---------------------------------------------------------------------------
# Employee Image Handler
# ---------------------------------------------------------------------------

def _handle_employee_image(phone: str, message: dict) -> None:
    """Handle an image (screenshot) received from a known employee.

    Expects the employee to be in 'waiting_screenshot' step.
    Triggers OpenAI parsing + Google Sheets save.
    """
    emp_name     = EMPLOYEE_PHONE_MAP[phone]
    current_step = state.get_state(phone)["step"]
    media_id     = message.get("image", {}).get("id", "")

    print(f"[Webhook] Image from {emp_name} (step={current_step}), media_id={media_id}")

    if current_step != "waiting_screenshot":
        whatsapp.send_message(
            phone,
            "Pehle report text bhejo, phir screenshot. 🙏"
        )
        return

    # Save media_id to state (for debugging / audit)
    state.save_data(phone, "screenshot_media_id", media_id)

    # Download the actual image bytes from WhatsApp
    image_bytes = whatsapp.download_media(media_id)
    if not image_bytes:
        print(f"[Webhook] Could not download image from {emp_name} ({media_id})")
        whatsapp.send_message(
            phone,
            "Screenshot download nahi ho paya. Please dobara bhejo. 🙏"
        )
        return

    # Upload to Cloudinary and get a public URL
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{emp_name}_{timestamp}.jpg"
    image_url = cloudinary_upload.upload_image(image_bytes, filename)
    if not image_url:
        print(f"[Webhook] Cloudinary upload failed for {emp_name}")
        whatsapp.send_message(
            phone,
            "Screenshot save karne mein error aayi. Please dobara bhejo ya manager se baat karo."
        )
        return

    # Parse the previously saved text report via OpenAI
    raw_report = state.get_data(phone).get("raw_report", "")
    parsed_data = openai_helper.parse_report(raw_report)

    # Persist the report to Google Sheets with the Cloudinary image URL
    success = sheets.save_report(emp_name, phone, parsed_data, image_url)

    if success:
        state.set_step(phone, "done")
        whatsapp.send_message(
            phone,
            f"Bahut badhiya {emp_name}! 🎉 Aapki report save ho gayi. Kal milte hain! 😊"
        )
        state.reset_state(phone)
    else:
        whatsapp.send_message(
            phone,
            "Kuch error aayi report save karte waqt. Please dobara screenshot bhejo ya manager se baat karo."
        )
