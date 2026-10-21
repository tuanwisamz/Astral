"""Gemini calls with guardrails (architechture.md §12): model IDs from env, JSON-schema output,
backoff on 429/5xx, a daily usage counter, and AI_UNAVAILABLE so callers fall back to manual.

Never send personal data here (NFR-03): callers pass photos without EXIF and text without names.
"""

import asyncio
import logging
from typing import Literal, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.services import usage

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
RETRIES = 3

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    key = get_settings().gemini_api_key
    if not key:
        raise ApiError(503, "AI_UNAVAILABLE", "AI isn't configured on this server", {"fallback": "manual"})
    if _client is None:
        _client = genai.Client(api_key=key)
    return _client


async def generate(
    session: AsyncSession | None, model: str, contents: list, schema: type[T], system: str | None = None
) -> T:
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, system_instruction=system
    )  # no temperature: deprecated from Gemini 3.6 Flash on
    delay = 1.0
    for attempt in range(RETRIES):
        try:
            resp = await client().aio.models.generate_content(model=model, contents=contents, config=config)
            if session is not None:
                await usage.bump(session, "gemini")
            if resp.parsed is not None:
                return resp.parsed
            return schema.model_validate_json(resp.text or "{}")
        except genai_errors.APIError as exc:
            retryable = getattr(exc, "code", None) in (429, 500, 503, 504)
            log.warning("Gemini %s failed (attempt %d): %s", model, attempt + 1, getattr(exc, "code", exc))
            if not retryable or attempt == RETRIES - 1:
                break
            await asyncio.sleep(delay)
            delay *= 3
        except Exception:
            log.warning("Gemini %s returned something unusable", model, exc_info=True)
            break
    raise ApiError(503, "AI_UNAVAILABLE", "AI analysis isn't available right now", {"fallback": "manual"})


# --- photo classification (T4.2) --------------------------------------------------------------


class PhotoAnalysis(BaseModel):
    is_road_hazard: bool = Field(description="True only for a pothole, fallen tree or sinkhole on or beside a road")
    hazard_type: Literal["POTHOLE", "FALLEN_TREE", "SINKHOLE"] | None = None
    severity: int = Field(ge=1, le=5, description="1 minor, 2 low, 3 moderate, 4 high, 5 critical")
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(description="Up to 3 short visual reasons, under 12 words each")
    faces_visible: bool
    plates_visible: bool


PHOTO_PROMPT = """You check photos that members of the public send to report road hazards in Malaysia.
Decide whether the photo shows one of: POTHOLE (hole or broken patch in the road surface),
FALLEN_TREE (tree or large branch on or across a road), SINKHOLE (ground collapsed or sunken under
or beside a road). Anything else, including blurry or unrelated photos, is not a road hazard.

Severity: 1 minor; 2 low; 3 moderate; 4 high (could damage a vehicle or endanger a motorcyclist);
5 critical (a lane is unsafe or blocked). Give at most 3 short visual reasons. Report whether any
face or vehicle number plate is readable. Do not describe people."""


async def classify_photo(session: AsyncSession, image: bytes, mime_type: str) -> PhotoAnalysis:
    model = get_settings().gemini_model_vision
    result = await generate(
        session, model, [types.Part.from_bytes(data=image, mime_type=mime_type), PHOTO_PROMPT], PhotoAnalysis
    )
    if not result.is_road_hazard:
        result.hazard_type = None
    result.reasons = [r.strip() for r in result.reasons if r.strip()][:3]
    return result
