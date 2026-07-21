import traceback
from io import BytesIO

import cloudinary
import cloudinary.uploader

from config import (
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
)

_FOLDER = "promope-screenshots"
_CONFIGURED = False


def _configure() -> bool:
    """Configure the Cloudinary SDK on first use. Returns True if ready."""
    global _CONFIGURED
    if _CONFIGURED:
        return True

    if not (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        print("[Cloudinary] ❌ Missing credentials — check CLOUDINARY_CLOUD_NAME / "
              "CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET in .env")
        return False

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )
    _CONFIGURED = True
    print(f"[Cloudinary] Configured with cloud_name={CLOUDINARY_CLOUD_NAME}")
    return True


def upload_image(image_bytes: bytes, filename: str) -> str | None:
    """Upload raw image bytes to Cloudinary and return the secure URL.

    Args:
        image_bytes: Raw image content.
        filename: Desired public_id (without extension) — used as a human-readable name.

    Returns:
        The secure_url of the uploaded image, or None on failure.
    """
    if not image_bytes:
        print("[Cloudinary] ❌ No image bytes provided")
        return None

    if not _configure():
        return None

    # Strip any extension — Cloudinary adds its own based on detected format
    public_id = filename.rsplit(".", 1)[0] if "." in filename else filename

    print("\n" + "=" * 60)
    print(f"[Cloudinary] Uploading '{filename}' to folder '{_FOLDER}'")
    print("=" * 60)

    try:
        result = cloudinary.uploader.upload(
            BytesIO(image_bytes),
            folder=_FOLDER,
            public_id=public_id,
            resource_type="image",
            overwrite=True,
        )
        secure_url = result.get("secure_url")
        if not secure_url:
            print(f"[Cloudinary] ❌ Upload returned no secure_url: {result}")
            return None

        print(f"[Cloudinary] ✅ Uploaded: {secure_url}")
        return secure_url

    except Exception as e:
        print(f"[Cloudinary] ❌ Upload failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None
