"""
gemini_scraper.py — Browser Automation Image Generator
=======================================================
Uses Playwright (Chromium) with a PERSISTENT browser profile to navigate
to the Gemini web app, submit a detailed prompt, wait for the image to be
generated, and save the result to the generated_images/ folder.

First-run: the browser window will open and wait up to 3 minutes for you
to log in manually (including any 2FA / OTP). After login, the profile is
saved to ./chrome_profile and reused automatically on all future runs.

Usage:
    image_path = generate_image_from_browser(user_details_dict)

user_details_dict keys:
    business_name  — Name of the business
    owner_name     — Owner's full name
    mobile         — Contact number
    address        — Business address / city
    category       — Business category (e.g., Real Estate, Salon)
"""

import os
import time
import random
import base64
import traceback

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

# Persistent profile directory — login cookies/session are stored here
CHROME_PROFILE_DIR = os.path.abspath("./gemini_pro_profile")

# Target URL (override via .env if using a custom deployment)
GEMINI_WEB_URL = os.getenv("GEMINI_WEB_URL", "https://gemini.google.com")

os.makedirs("generated_images", exist_ok=True)
os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jitter(lo: float = 1.0, hi: float = 3.0):
    """Sleep for a random human-like duration between lo and hi seconds."""
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

def _build_scraper_prompt(details: dict, lang: str = "gujarati") -> str:
    """Build a language-aware promotional poster prompt from business details."""
    business_name = details.get("business_name", "")
    category      = details.get("category", "")
    owner_name    = details.get("owner_name", "")
    mobile        = details.get("mobile", "")
    address       = details.get("address", "")
    other_details = details.get("other_details", "")

    if lang == "hindi":
        details_block = (
            f"मेरा नाम {owner_name} है। मेरी दुकान/ऑफिस का नाम {business_name} है "
            f"और मैं {category} का काम करता हूँ। "
            f"मेरा मोबाइल नंबर {mobile} है। मेरा पता {address} है."
        )
        if other_details:
            details_block += f" अन्य जानकारी: {other_details}."
        lang_instruction = "in Hindi language"
    elif lang in ("english", "hinglish"):
        details_block = (
            f"My name is {owner_name}. My business name is {business_name} "
            f"and I work in {category}. "
            f"My mobile number is {mobile}. My address is {address}."
        )
        if other_details:
            details_block += f" Additional info: {other_details}."
        lang_instruction = "in English language"
    else:  # gujarati (default)
        details_block = (
            f"મારું નામ {owner_name} છે. મારી દુકાન/ઓફિસ નું નામ {business_name} છે "
            f"અને હું {category} નું કામ કરું છું. "
            f"મારો મોબાઈલ નંબર {mobile} છે. મારું સરનામું {address} છે."
        )
        if other_details:
            details_block += f" અન્ય વિગત: {other_details}."
        lang_instruction = "in Gujarati language"

    return (
        f"Generate a beautiful, high-quality promotional poster IMAGE for this business. "
        f"It is mandatory to generate an image. "
        f"Please creatively include the following details {lang_instruction} on the poster: "
        f"{details_block}. "
        f"Do not include any human faces or people in the image."
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_image_from_browser(user_details_dict: dict) -> str | None:
    """
    Launch a persistent Chromium browser, navigate to Gemini, wait for the
    chat interface (prompting manual login if needed), submit the poster
    prompt with human-like behaviour, and return the saved image path.

    Parameters
    ----------
    user_details_dict : dict
        Keys: business_name, owner_name, mobile, address, category

    Returns
    -------
    str | None
        Absolute path to the saved image file, or None on failure.
    """
    biz_name  = user_details_dict.get("business_name", "business")
    timestamp = int(time.time())
    filename  = f"browser_poster_{timestamp}.png"
    save_path = os.path.abspath(os.path.join("generated_images", filename))

    print()
    print("=" * 65)
    print("  BROWSER SCRAPER: Starting image generation")
    print("=" * 65)
    print(f"  Target URL     : {GEMINI_WEB_URL}")
    print(f"  Business       : {biz_name}")
    print(f"  Profile dir    : {CHROME_PROFILE_DIR}")
    print(f"  Save path      : {save_path}")
    print("=" * 65)

    prompt_text = _build_scraper_prompt(user_details_dict, lang=user_details_dict.get("lang", "gujarati"))
    print(f"\n📝 Prompt preview:\n   {prompt_text[:200]}...\n")

    try:
        with sync_playwright() as p:

            # ── 1. Launch persistent context ─────────────────────────────────
            # Cookies and session data are stored in CHROME_PROFILE_DIR so the
            # user only needs to log in once.  On subsequent runs the session
            # is restored automatically.
            print("[1/6] Launching persistent browser context...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                headless=False,
                channel="chrome",
                args=[
                    "--start-maximized",
                    "--window-size=1920,1080",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
                viewport=None,       # let --start-maximized set the real OS window size
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
            )

            # Reuse the first tab if one already exists, otherwise open a new one
            page = context.pages[0] if context.pages else context.new_page()
            # Override Playwright's default 30 s timeout for all operations.
            # Explicit timeout= arguments on individual calls still override this.
            page.set_default_timeout(10_000)
            print("      ✔ Browser opened.")

            # ── 2. Navigate to Gemini ─────────────────────────────────────────
            print("[2/6] Navigating to Gemini chat...")
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=30_000)
            _jitter(1.0, 2.0)   # brief settle for SPA render

            # ── 3. Login verification barrier ────────────────────────────────
            # Gemini now shows the chat input to unauthenticated (guest) users,
            # so we CANNOT use the chat input box as proof of login.
            # Strategy:
            #   a) Check for the Sign-in button (= not logged in).
            #   b) If found → print loud warning, HALT, and wait up to 3 min
            #      for the user's Google Account profile avatar to appear —
            #      the avatar is only rendered when the session is fully active.
            #   c) If not found (avatar already visible) → skip straight through.
            # Only after login is confirmed do we locate the chat input.

            print("[3/6] Checking login status...")

            # Selectors that indicate the user is NOT logged in
            signin_selectors = [
                'a:has-text("Sign in")',
                'button:has-text("Sign in")',
                'a[href*="accounts.google.com"]',
                '[data-view-component="true"]:has-text("Sign in")',
            ]

            # Selectors that confirm the user IS logged in
            avatar_selectors = [
                'a[aria-label*="Google Account"]',
                'img[alt*="profile photo"]',
                'div[data-ogsr-up]',        # Gemini 2025 account menu trigger
                'button[aria-label*="Google Account"]',
                'div.gb_d',                 # Google account avatar div (classic)
            ]

            def _is_visible(sel: str, t: int = 3_000) -> bool:
                """Return True if selector matches a visible element within t ms."""
                try:
                    return page.locator(sel).first.is_visible(timeout=t)
                except Exception:
                    return False

            # Fast path: check avatar first — authenticated sessions skip signin check entirely
            already_logged_in = any(_is_visible(s, 3_000) for s in avatar_selectors)

            if already_logged_in:
                print("[3/6] ✔ Already logged in (avatar visible). Proceeding.")
            else:
                needs_login = any(_is_visible(s, 3_000) for s in signin_selectors)
                if needs_login:
                    print()
                    print("┌──────────────────────────────────────────────────────────────┐")
                    print("│  🚨  NOT LOGGED IN — ACTION REQUIRED                         │")
                    print("│                                                              │")
                    print("│  Please manually click 'Sign in' in the browser window and  │")
                    print("│  complete the full Google login (including OTP / 2FA).       │")
                    print("│                                                              │")
                    print("│  The script will AUTOMATICALLY CONTINUE once your Google     │")
                    print("│  Account profile avatar is detected (login confirmed).       │")
                    print("│                                                              │")
                    print("│  You have up to 3 minutes.                                  │")
                    print("└──────────────────────────────────────────────────────────────┘")
                    print()

                    # Wait for any avatar selector — proof that login completed.
                    # CRITICAL: check page.url on every iteration. While the user is
                    # going through Google's auth flow, the browser is on accounts.google.com.
                    # Running Gemini locator checks against that domain either raises
                    # exceptions or exhausts timeouts.  Skip all locator work until
                    # the URL is back on gemini.google.com.
                    avatar_found = False
                    deadline = time.time() + 180
                    while time.time() < deadline:
                        try:
                            current_url = page.url
                        except Exception:
                            current_url = ""
                        if ("accounts.google.com" in current_url
                                or "myaccount.google.com" in current_url):
                            # On Google auth pages — wait quietly, no locator calls
                            print(f"      … on Google login page "
                                  f"({current_url[:70]}) — waiting for redirect …")
                            time.sleep(5)
                            continue
                        # URL is back on Gemini — safe to check for avatar
                        if any(_is_visible(s, 2_000) for s in avatar_selectors):
                            avatar_found = True
                            break
                        print("      … waiting for avatar on Gemini page …")
                        time.sleep(5)

                    if not avatar_found:
                        raise RuntimeError(
                            "Timed out waiting for Google Account avatar (3 min). "
                            "Please log in manually before running the script again."
                        )

                    print("[3/6] ✔ Avatar detected. Waiting for redirect back to Gemini...")
                    # Ensure the redirect chain has fully resolved to gemini.google.com
                    # before any locator operations happen.
                    try:
                        page.wait_for_url("*gemini.google.com*", timeout=60_000)
                        print("      ✔ URL confirmed on gemini.google.com.")
                    except PlaywrightTimeout:
                        print("      ⚠️  wait_for_url timed out — proceeding cautiously.")
                    # Wait for Gemini's DOM tree to be present before selector searches
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=30_000)
                        print("      ✔ DOM content loaded.")
                    except PlaywrightTimeout:
                        print("      ⚠️  wait_for_load_state timed out — DOM may be partial.")
                    _jitter(2.0, 3.0)
                    print("      ✔ Login confirmed and Gemini page settled.")

                else:
                    # Edge case: neither avatar nor sign-in button found yet —
                    # page may still be loading; give it a few extra seconds.
                    print("[3/6] ⏳ Session state unclear, waiting for page to settle...")
                    _jitter(1.5, 2.5)
                    if any(_is_visible(s, 5_000) for s in avatar_selectors):
                        print("      ✔ Avatar detected after extra wait. Proceeding.")
                    else:
                        print("      ⚠️  Avatar not detected — proceeding cautiously.")

            # ── 3.5 Navigate to fresh chat (only if we just completed a login flow) ──
            if not already_logged_in:
                print("[3.5/6] Navigating to fresh Gemini chat post-login...")
                try:
                    page.goto(
                        "https://gemini.google.com/app",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    print("      ✔ Fresh chat page loaded.")
                except Exception:
                    print("      ⚠ Fresh chat navigation timed out — continuing on current page.")
            else:
                print("[3.5/6] Skipped — already on chat page.")

            # ── 4. Locate chat input (AFTER login is confirmed) ───────────────
            print("[4/6] Locating chat input box...")
            _jitter(0.5, 1.0)   # brief settle before searching for input

            input_selectors = [
                'div[contenteditable="true"][data-placeholder]',  # Gemini 2025 UI
                'rich-textarea div[contenteditable="true"]',
                'textarea.input-area-textarea',
                'textarea[placeholder]',
                'div[contenteditable="true"]',
            ]

            prompt_input = None
            for sel in input_selectors:
                try:
                    page.wait_for_selector(sel, timeout=60_000)
                    prompt_input = page.locator(sel).first
                    print(f"      ✔ Chat input found ({sel}).")
                    break
                except PlaywrightTimeout:
                    continue

            if prompt_input is None:
                raise RuntimeError(
                    "Could not find the Gemini chat input box after login. "
                    "The UI may have changed — update input_selectors in gemini_scraper.py."
                )

            # ── 5. Type the prompt with human-like behaviour ──────────────────
            print("[5/6] Entering prompt...")
            _jitter(0.5, 1.0)           # human pause before clicking the input
            prompt_input.click(timeout=30_000)   # explicit: 10 s default is too tight post-login
            _jitter(0.5, 1.0)           # brief pause after focus before typing

            # CRITICAL: collapse all whitespace (\n, \t, multiple spaces) into
            # single spaces — the chat box treats \n as Enter = premature submit.
            sanitized_prompt = " ".join(prompt_text.split())
            page.keyboard.type(sanitized_prompt, delay=100)
            print("      ✔ Prompt typed.")
            _jitter(0.5, 1.0)           # pause after finishing, like a human re-reading

            # ── 6. Submit the prompt ──────────────────────────────────────────
            print("[6/6] Submitting prompt...")
            send_selectors = [
                'button[aria-label="Send message"]',
                'button[data-mat-icon-name="send"]',
                'button.send-button',
                'mat-icon:has-text("send")',
            ]
            sent = False
            for sel in send_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=3_000):
                        btn.hover()             # hover like a human deciding to click
                        _jitter(0.8, 1.5)
                        btn.click()
                        time.sleep(0.5)
                        sent = True
                        print(f"      ✔ Submitted via button ({sel}).")
                        break
                except Exception:
                    continue

            if not sent:
                page.keyboard.press("Control+Enter")
                print("      ✔ Submitted via Control+Enter key.")

            # ── 6. Wait for the generated image to appear ─────────────────────

            # Phase A — wait for Gemini to start a response (up to 60 s)
            print("      ⏳ Waiting for Gemini response to begin (up to 60 s)...")
            _response_container_selectors = [
                'model-response',
                'div[data-message-author-role="model"]',
                'div.response-container',
                'ms-chat-turn[author="model"]',
            ]
            _response_started = False
            for _rsel in _response_container_selectors:
                try:
                    page.wait_for_selector(_rsel, timeout=90_000)
                    print(f"      ✔ Response container appeared ({_rsel}).")
                    _response_started = True
                    break
                except PlaywrightTimeout:
                    continue
            if not _response_started:
                print("      ⚠️  No response container — proceeding to image poll.")

            # Phase B — poll for the AI-generated thumbnail (up to 120 s)
            # Strictly ignore avatars, icons, and logos via src + class filtering.
            print("      ⏳ Waiting for image generation (up to 120 s)...")
            img_selectors = [
                'img[src^="https://generativelanguage.googleapis.com"]:not([src*="avatar"]):not([src*="icon"])',
                'img[src^="https://aidev-pa.googleapis.com"]:not([src*="avatar"]):not([src*="icon"])',
                'img[src*="bard-image-generation"]',
                'img.generated-image',
                'message-content img[src^="https://"]:not([src*="avatar"]):not([src*="icon"]):not([src*="logo"])',
                'user-content img[src^="https://"]:not([src*="avatar"]):not([src*="icon"]):not([src*="logo"])',
                '.response-content img[src^="https://"]:not([src*="avatar"]):not([src*="icon"])',
                'model-response img[src]:not([src*="avatar"]):not([src*="icon"]):not([src*="logo"])',
                'div[data-message-author-role="model"] img[src]:not([src*="avatar"]):not([src*="icon"])',
                'div.response-container img[src*="data:"]',
            ]

            generated_img_el = None
            deadline = time.time() + 120

            while time.time() < deadline:
                for sel in img_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=2_000):
                            src = el.get_attribute("src") or ""
                            # Skip avatars/icons that slipped through via src content
                            if any(skip in src for skip in ("avatar", "icon", "logo", "profile")):
                                continue
                            if src and len(src) > 50:   # non-trivial src = real image
                                generated_img_el = el
                                print(f"      ✔ Thumbnail found ({sel}).")
                                break
                    except Exception:
                        continue
                if generated_img_el:
                    break
                print("      … still waiting for image …")
                time.sleep(5)

            # Fallback: try to screenshot ONLY the inner image/content wrapper,
            # NOT the full response container (which includes footer/disclaimer text).
            if generated_img_el is None:
                print("⚠️  Image element not found — trying targeted inner-content selectors.")
                inner_selectors = [
                    'message-content .image-wrapper',
                    'message-content user-content',
                    'user-content',
                    '.response-content',
                    'message-content',
                ]
                for sel in inner_selectors:
                    try:
                        area = page.locator(sel).last
                        if area.is_visible(timeout=3_000):
                            inner_imgs = area.locator('img[src]')
                            if inner_imgs.count() > 0:
                                area.screenshot(path=save_path)
                                print(f"      ✔ Inner content screenshot → {save_path}")
                                context.close()
                                return save_path
                    except Exception:
                        continue

                print("      ⚠️  Could not isolate image from response — returning None.")
                context.close()
                return None

            # ── Step 2: Click thumbnail to open full-screen modal ─────────────
            thumbnail_src = generated_img_el.get_attribute("src") or ""
            print("      🖱  Clicking thumbnail to open full-screen modal...")
            try:
                generated_img_el.click(timeout=10_000)
            except Exception as click_err:
                print(f"      ⚠️  Thumbnail click failed ({click_err}) — will use thumbnail directly.")

            # ── Step 3: Wait for modal animation ──────────────────────────────
            time.sleep(2)

            # ── Step 4: Find full-res image inside modal ───────────────────────
            modal_selectors = [
                '[role="dialog"] img[src]:not([src*="avatar"]):not([src*="icon"])',
                '[role="dialog"] img[src]',
                'div[data-testid="lightbox"] img[src]',
                '.modal img[src]:not([src*="avatar"])',
                'c-wiz img[src]:not([src*="avatar"]):not([src*="icon"])',
                'overlay-container img[src]',
            ]
            full_img_el = None
            for sel in modal_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3_000):
                        modal_src = el.get_attribute("src") or ""
                        if modal_src and len(modal_src) > 50 and modal_src != thumbnail_src:
                            full_img_el = el
                            print(f"      ✔ Full-res modal image found ({sel}).")
                            break
                except Exception:
                    continue

            if full_img_el is None:
                print("      ℹ️  No modal image found — using thumbnail directly.")
                full_img_el = generated_img_el

            # ── 7. Download the image ─────────────────────────────────────────
            print(f"[6/6] Saving image to {save_path}...")
            src = full_img_el.get_attribute("src") or ""

            if src.startswith("data:"):
                _, b64data = src.split(",", 1)
                img_bytes = base64.b64decode(b64data)
                with open(save_path, "wb") as f:
                    f.write(img_bytes)
                print(f"      ✔ Saved base64 image ({len(img_bytes):,} bytes).")

            elif src.startswith("http"):
                print(f"      ⏳ Downloading image from HTTP URL...")
                try:
                    resp = page.request.get(src)
                    if resp.ok:
                        img_bytes = resp.body()
                        with open(save_path, "wb") as f:
                            f.write(img_bytes)
                        print(f"      ✔ Downloaded image ({len(img_bytes):,} bytes).")
                    else:
                        raise RuntimeError(f"HTTP {resp.status} when fetching image URL")
                except Exception as dl_err:
                    print(f"      ⚠️  Direct download failed ({dl_err}) — falling back to bounding_box screenshot")
                    box = full_img_el.bounding_box()
                    if box:
                        page.screenshot(path=save_path, clip=box)
                        print("      ✔ Bounding-box clipped screenshot saved.")
                    else:
                        print("      ⚠️  bounding_box unavailable — cannot screenshot without clip, returning None.")
                        context.close()
                        return None

            else:
                # Unknown src format — use bounding_box screenshot only
                box = full_img_el.bounding_box()
                if box:
                    page.screenshot(path=save_path, clip=box)
                    print("      ✔ Bounding-box clipped screenshot saved (unknown src format).")
                else:
                    print("      ⚠️  bounding_box unavailable — returning None.")
                    context.close()
                    return None

            # Close context gracefully — this flushes cookies/session to disk
            context.close()

            print()
            print("=" * 65)
            print(f"  BROWSER SCRAPER: Complete ✔  →  {save_path}")
            print("=" * 65)
            print()
            return save_path

    except Exception as e:
        print(f"\n❌ generate_image_from_browser failed: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    details = {
    "owner_name": "મેહુલ દરજી",
    "business_name": "શ્રીજી ગાર્મેન્ટ્સ",
    "category": "કપડાંની દુકાન (Men's & Women's Wear)",
    "mobile": "9988776655",
    "address": "મેઈન બજાર, ચોકબજાર, સુરત"
}
    result = generate_image_from_browser(details)
    print(f"\nResult: {result}")
