"""Photo hygiene before anything leaves the server (NFR-03): decode, drop EXIF and other
metadata, cap the size, re-encode as WebP."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ApiError

MAX_SIDE = 1280
MAX_BYTES = 3 * 1024 * 1024
# A small file can declare a huge canvas (a "decompression bomb"): a 48 KB PNG of 20000 x 20000
# pixels, or one just under Pillow's own limit that costs ~300 MB to decode. The in-app camera
# sends at most MAX_SIDE on the long side (~1.2 MP), so 40 MP only ever refuses crafted uploads.
MAX_PIXELS = 40_000_000
ALLOWED = {"JPEG", "PNG", "WEBP", "MPO", "HEIF"}
TOO_LARGE = "Photo is too large to check. Take it again with the in-app camera."


def clean(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ApiError(422, "VALIDATION_ERROR", "Photo must be 3 MB or smaller")
    try:
        img = Image.open(io.BytesIO(data))  # reads the header only; nothing is decoded yet
        if img.format not in ALLOWED:
            raise ApiError(422, "VALIDATION_ERROR", "Send a JPEG, PNG or WebP photo")
        if img.width * img.height > MAX_PIXELS:
            raise ApiError(422, "VALIDATION_ERROR", TOO_LARGE, {"max_pixels": MAX_PIXELS})
        img = ImageOps.exif_transpose(img)  # keep the orientation the phone intended, then drop EXIF
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="WEBP", quality=80)  # a fresh image carries no metadata
    except Image.DecompressionBombError as exc:  # Pillow's own hard limit, hit before our check runs
        raise ApiError(422, "VALIDATION_ERROR", TOO_LARGE, {"max_pixels": MAX_PIXELS}) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "That file isn't a photo we can read") from exc
    return out.getvalue()
