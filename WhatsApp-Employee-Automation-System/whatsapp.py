import requests
from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID

# Base URL for Meta WhatsApp Cloud API
_BASE_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}"

# Common headers reused across all API calls
_HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


def send_message(phone: str, text: str) -> bool:
    """Send a plain text WhatsApp message to the given phone number.

    Args:
        phone: Recipient phone in international format without '+' (e.g. 919876543210)
        text:  Message body to send

    Returns:
        True if the API responded with 200, False otherwise.
    """
    url = f"{_BASE_URL}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(url, headers=_HEADERS, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"[WhatsApp] Message sent to {phone}")
            return True
        else:
            print(f"[WhatsApp] Failed to send to {phone}: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"[WhatsApp] Exception while sending to {phone}: {e}")
        return False


def download_media(media_id: str) -> bytes | None:
    """Download binary media (image) sent by an employee using its media_id.

    The process is two-step:
      1. Fetch the media URL from Meta's media endpoint.
      2. Download the actual file bytes from that URL.

    Args:
        media_id: The media_id received in the incoming webhook payload.

    Returns:
        Raw bytes of the media file, or None if any step fails.
    """
    try:
        # Step 1: Get the temporary media download URL
        url_endpoint = f"https://graph.facebook.com/v19.0/{media_id}"
        meta_response = requests.get(url_endpoint, headers=_HEADERS, timeout=10)

        if meta_response.status_code != 200:
            print(f"[WhatsApp] Could not fetch media URL for {media_id}: {meta_response.text}")
            return None

        media_url = meta_response.json().get("url")
        if not media_url:
            print(f"[WhatsApp] No URL in media response for {media_id}")
            return None

        # Step 2: Download the actual image bytes
        # Meta requires the same Authorization header for this request too
        file_response = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30,
        )

        if file_response.status_code == 200:
            print(f"[WhatsApp] Media {media_id} downloaded successfully ({len(file_response.content)} bytes)")
            return file_response.content
        else:
            print(f"[WhatsApp] Failed to download media {media_id}: {file_response.status_code}")
            return None

    except Exception as e:
        print(f"[WhatsApp] Exception while downloading media {media_id}: {e}")
        return None
