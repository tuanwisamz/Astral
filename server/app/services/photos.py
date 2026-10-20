"""Photo hygiene before anything leaves the server (NFR-03): decode, drop EXIF and other
metadata, cap the size, re-encode as WebP."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ApiError

MAX_SIDE = 1280
MAX_BYTES = 3 * 1024 * 1024
ALLOWED = {"JPEG", "PNG", "WEBP", "MPO", "HEIF"}


def clean(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ApiError(422, "VALIDATION_ERROR", "Photo must be 3 MB or smaller")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED:
            raise ApiError(422, "VALIDATION_ERROR", "Send a JPEG, PNG or WebP photo")
        img = ImageOps.exif_transpose(img)  # keep the orientation the phone intended, then drop EXIF
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="WEBP", quality=80)  # a fresh image carries no metadata
    except (UnidentifiedImageError, OSError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "That file isn't a photo we can read") from exc
    return out.getvalue()
