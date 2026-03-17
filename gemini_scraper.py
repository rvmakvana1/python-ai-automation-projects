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
CHROME_PROFILE_DIR = os.path.abspath("./chrome_profile")

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

def _build_scraper_prompt(details: dict) -> str:
    """
    Build a photorealistic image-generation prompt using a hybrid architecture:
    predefined optimised scenes for known categories, dynamic fallback for unknown ones.
    """
    business_name = details.get("business_name", "Business")
    category      = details.get("category", "premium business")
    owner_name    = details.get("owner_name", "")
    mobile        = details.get("mobile", "")
    address       = details.get("address", "")

    # SMART CATEGORY DICTIONARY (Max 25 words per scene)
    category_scenes = {
        ("mobile", "electronics", "appliance", "gadget", "computer"):
            "Premium electronics and mobile showroom interior with sleek glass displays, glowing neon accents, and modern tech gadgets on luxury marble counters.",

        ("real estate", "builder", "architect", "interior", "property", "construction"):
            "Hyper-realistic luxury 3D architectural render of a modern high-rise apartment complex and premium villas at golden hour with lush landscaping.",

        ("restaurant", "food", "bakery", "dairy", "seafood", "catering", "cafe", "fast food"):
            "Cozy and premium restaurant table setup with warm bokeh lighting, a pristine wooden table, and elegant gourmet presentation vibes.",

        ("clothes", "textile", "fashion", "tailor", "footwear", "boutique", "garment"):
            "Luxurious fashion boutique interior with elegant mannequins, premium fabric rolls, and warm cinematic spotlighting on modern clothing racks.",

        ("beauty", "salon", "cosmetic", "parlour", "wellness", "tattoo", "spa"):
            "Elegant beauty and wellness salon interior with warm rose-gold accents, premium skincare products on a marble shelf, and soft ambient lighting.",

        ("hospital", "clinic", "medical", "pharmaceutical", "homeopathy", "physiotherapy"):
            "Ultra-clean, modern hospital clinic interior with high-tech medical equipment, soft white clinical lighting, and a premium healthcare atmosphere.",

        ("automobile", "transport", "logistics", "driving", "courier", "travels"):
            "Sleek automotive showroom with polished reflective floors, dramatic cinematic lighting, showcasing modern high-end vehicle silhouettes.",

        ("hardware", "ceramic", "steel", "glass", "paints", "building material", "plywood"):
            "Premium industrial construction and building materials showcase with neatly arranged ceramic tiles, polished steel, and dramatic studio lighting.",

        ("furniture", "home decor", "wood"):
            "Luxurious modern living room interior design with a premium leather sofa, elegant wooden textures, and warm inviting sunlight.",

        ("jewellery", "watch", "gift"):
            "High-end luxury jewelry store display with sparkling diamonds and gold ornaments on dark velvet, illuminated by crisp focused spotlights.",

        ("photography", "camera", "events", "videography", "printing"):
            "Photorealistic modern photography studio with professional lighting gear, softboxes, and a premium DSLR camera on a sleek dark desk.",

        ("agriculture", "nursery", "poultry", "animal food"):
            "Vibrant and lush green modern agricultural farm or plant nursery at sunrise with organic, fresh, and healthy nature vibes.",

        ("education", "school", "academy", "stationery", "classes"):
            "Modern bright classroom or library setting with neatly stacked premium books, a laptop, and warm sunlight filtering through a window.",
    }

    # MATCHING LOGIC
    scene_description = f"A photorealistic, luxury promotional poster background specifically tailored for a {category} business, featuring premium environment."  # Fallback
    for keywords, scene in category_scenes.items():
        if any(kw in category.lower() for kw in keywords):
            scene_description = scene
            break

    prompt_text = (
        f"{scene_description} Prominently render the exact text '{business_name}' in large, elegant, 3D golden typography at the top. "
        f"Below it, clearly render 'Owner: {owner_name}', 'Mobile: {mobile}', and 'Location: {address}'. "
        "Aspect ratio exactly 1:1. 4K cinematic quality. Output a single image only. No explanation text."
    )
    return ' '.join(prompt_text.split())


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

    prompt_text = _build_scraper_prompt(user_details_dict)
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
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
                viewport=None,          # let --start-maximized control the window size
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            # Reuse the first tab if one already exists, otherwise open a new one
            page = context.pages[0] if context.pages else context.new_page()
            # Override Playwright's default 30 s timeout for all operations.
            # Explicit timeout= arguments on individual calls still override this.
            page.set_default_timeout(10_000)
            print("      ✔ Browser opened.")

            # ── 2. Navigate to Gemini ─────────────────────────────────────────
            print(f"[2/6] Navigating to {GEMINI_WEB_URL} ...")
            page.goto(GEMINI_WEB_URL, wait_until="domcontentloaded", timeout=30_000)
            _jitter(2.0, 4.0)   # pause like a human reading the landing page

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
            _jitter(1.5, 3.0)   # let the page finish rendering before DOM checks

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

            # Check for Sign-in button
            needs_login = any(_is_visible(s, 4_000) for s in signin_selectors)

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
                # Verify avatar is actually visible (not just absence of sign-in btn)
                if any(_is_visible(s, 4_000) for s in avatar_selectors):
                    print("[3/6] ✔ Already logged in (avatar visible). Proceeding.")
                else:
                    # Edge case: neither sign-in button nor avatar found yet —
                    # page may still be loading; give it a few extra seconds.
                    print("[3/6] ⏳ Session state unclear, waiting for page to settle...")
                    _jitter(3.0, 5.0)
                    if any(_is_visible(s, 5_000) for s in avatar_selectors):
                        print("      ✔ Avatar detected after extra wait. Proceeding.")
                    else:
                        print("      ⚠️  Avatar not detected — proceeding cautiously.")

            # ── 3.5 Navigate to fresh chat (clean slate for every generation) ──
            print("[3.5/6] Navigating to fresh Gemini chat...")
            try:
                page.goto(
                    "https://gemini.google.com/app",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                print("      ✔ Fresh chat page loaded.")
            except Exception:
                print("      ⚠ Fresh chat navigation timed out — continuing on current page.")

            # ── 4. Locate chat input (AFTER login is confirmed) ───────────────
            print("[4/6] Locating chat input box...")
            _jitter(1.0, 2.0)   # brief settle before searching for input

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
            _jitter(1.0, 2.5)           # human pause before clicking the input
            prompt_input.click(timeout=30_000)   # explicit: 10 s default is too tight post-login
            _jitter(0.8, 1.8)           # brief pause after focus before typing

            # CRITICAL: collapse all whitespace (\n, \t, multiple spaces) into
            # single spaces — the chat box treats \n as Enter = premature submit.
            sanitized_prompt = " ".join(prompt_text.split())
            page.keyboard.type(sanitized_prompt, delay=150)
            print("      ✔ Prompt typed.")
            _jitter(1.5, 3.0)           # pause after finishing, like a human re-reading

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
                        sent = True
                        print(f"      ✔ Submitted via button ({sel}).")
                        break
                except Exception:
                    continue

            if not sent:
                page.keyboard.press("Enter")
                print("      ✔ Submitted via Enter key.")

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
                    page.wait_for_selector(_rsel, timeout=60_000)
                    print(f"      ✔ Response container appeared ({_rsel}).")
                    _response_started = True
                    break
                except PlaywrightTimeout:
                    continue
            if not _response_started:
                print("      ⚠️  No response container — proceeding to image poll.")

            # Phase B — poll for the actual image element (up to 120 s)
            print("      ⏳ Waiting for image generation (up to 120 s)...")
            img_selectors = [
                'img[src^="https://generativelanguage.googleapis.com"]',
                'img[src^="https://aidev-pa.googleapis.com"]',
                'img[src*="bard-image-generation"]',
                'img.generated-image',
                'model-response img[src]:not([src*="avatar"]):not([src*="icon"])',
                'div[data-message-author-role="model"] img[src]',
                'div.response-container img[src*="data:"]',
                'message-content img:not([src*="avatar"]):not([src*="icon"])',
            ]

            generated_img_el = None
            deadline = time.time() + 120

            while time.time() < deadline:
                for sel in img_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=2_000):
                            src = el.get_attribute("src") or ""
                            if src and len(src) > 50:   # non-trivial src = real image
                                generated_img_el = el
                                print(f"      ✔ Image element found ({sel}).")
                                break
                    except Exception:
                        continue
                if generated_img_el:
                    break
                print("      … still waiting for image …")
                time.sleep(5)

            # Fallback: screenshot response area / full page if no img element found
            if generated_img_el is None:
                print("⚠️  Image element not found — screenshotting response area.")
                response_selectors = [
                    'model-response',
                    'div.response-container',
                    'div[data-message-author-role="model"]',
                ]
                for sel in response_selectors:
                    try:
                        area = page.locator(sel).last
                        if area.is_visible(timeout=3_000):
                            area.screenshot(path=save_path)
                            print(f"      ✔ Response area screenshot → {save_path}")
                            context.close()     # saves cookies/session
                            return save_path
                    except Exception:
                        continue

                # Absolute last resort
                page.screenshot(path=save_path, full_page=True)
                print(f"      ⚠️  Full-page screenshot → {save_path}")
                context.close()
                return save_path

            # ── 7. Download the image ─────────────────────────────────────────
            print(f"[6/6] Saving image to {save_path}...")
            src = generated_img_el.get_attribute("src") or ""

            if src.startswith("data:"):
                _, b64data = src.split(",", 1)
                img_bytes = base64.b64decode(b64data)
                with open(save_path, "wb") as f:
                    f.write(img_bytes)
                print(f"      ✔ Saved base64 image ({len(img_bytes):,} bytes).")

            elif src.startswith("http"):
                # Google CDN URLs require auth cookies — requests.get() gets 403.
                # Use Playwright's native screenshot: the browser already holds the session.
                generated_img_el.wait_for(state="visible", timeout=10_000)
                generated_img_el.screenshot(path=save_path)
                print("      ✔ Element screenshot saved (bypassed CDN auth).")

            else:
                generated_img_el.screenshot(path=save_path)
                print("      ✔ Element screenshot saved.")

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
    test_details = {
        "business_name": "Om Builders",
        "owner_name":    "Rajesh Patel",
        "mobile":        "9876543210",
        "address":       "Satellite, Ahmedabad",
        "category":      "Real Estate",
    }
    result = generate_image_from_browser(test_details)
    print(f"\nResult: {result}")
