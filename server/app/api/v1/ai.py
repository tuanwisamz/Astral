"""AI explanations and the Decision Assistant (T7.1, T7.2; architechture.md §12).

Guardrails: numbers come only from the database; explain() rejects any AI text containing a
number it wasn't given and falls back to a template; the assistant uses read-only tools, at
most five calls per question, cites segment IDs, and every answer is labelled AI-suggested.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import segments as segments_api
from app.api.v1.priority import _zone_summary as zone_summary
from app.core import db
from app.core.auth import STAFF, CurrentUser, require_role
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import priority as ranking
from app.queries import segments
from app.services import gemini, scope, usage

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_TOOL_CALLS = 5
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class ExplainIn(BaseModel):
    segment_id: int
    language: str = Field(default="en", pattern="^(en|ms)$")


class Explanation(BaseModel):
    text: str = Field(description="2 or 3 short sentences in plain language")
    numbers_used: list[str] = Field(description="Keys of the facts the text relies on")


def _facts(a: dict) -> dict[str, Any]:
    """The only numbers the model may use, flattened with stable keys."""
    p = a.get("priority") or {}
    facts = {
        "road": a.get("name") or "this road",
        "route": a.get("ref"),
        "district": a.get("district"),
        "owner": a.get("owner"),
        "length_km": a.get("length_km"),
        "priority_score": p.get("score"),
        "rank_in_district": p.get("rank_in_district"),
        "recommended_action": p.get("recommended_action"),
        "adt": a["traffic"]["adt"],
        "heavy_pct": round((a["traffic"]["heavy_pct"] or 0) * 100),
        "adt_is_estimate": a["traffic"]["estimated"],
        "potholes_12m": sum(m["count"] for m in a["pothole_frequency"]["series"]),
        "potholes_last_3m": sum(m["count"] for m in a["pothole_frequency"]["series"][-3:]),
        "deaths_3y": a["safety"]["deaths_3y"],
        "injuries_3y": a["safety"]["injuries_3y"],
        "rain_7d_mm": (a.get("weather") or {}).get("rain_7d"),
        "forecast_rain_7d_mm": (a.get("weather") or {}).get("forecast_7d"),
        "karst": a["geology"]["karst"],
    }
    for pred in a.get("predictions", []):
        if pred["horizon_days"] == 30:
            facts[f"chance_30d_{pred['hazard_type'].lower()}_pct"] = round(pred["probability"] * 100)
    return {k: v for k, v in facts.items() if v is not None}


def _template(f: dict, language: str) -> str:
    if language == "ms":
        return (
            f"{f['road']} di {f.get('district', '')} mempunyai skor keutamaan {f.get('priority_score', '-')}. "
            f"{f['potholes_12m']} lubang jalan dilaporkan dalam 12 bulan, dan {f['adt']} kenderaan sehari."
        )
    return (
        f"{f['road']} in {f.get('district', '')} has a priority score of {f.get('priority_score', '-')}. "
        f"{f['potholes_12m']} potholes were reported in 12 months, with about {f['adt']} vehicles a day."
    )


def _numbers_are_grounded(text_out: str, facts: dict) -> bool:
    allowed = {str(v) for v in facts.values() if isinstance(v, int | float)}
    allowed |= {f"{v:,}" for v in facts.values() if isinstance(v, int) and v >= 1000}
    allowed |= {str(round(v)) for v in facts.values() if isinstance(v, float)}
    allowed |= {"1", "2", "3", "7", "12", "30", "24"}  # durations and counts used as words in the facts' keys
    return all(n.replace(",", "") in {a.replace(",", "") for a in allowed} for n in NUMBER.findall(text_out))


@router.post("/explain")
async def explain(
    body: ExplainIn, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    model = get_settings().gemini_model_lite
    version = (
        await db.scalar(session, "select max(model_version) from predictions where segment_id = :s", s=body.segment_id)
        or "none"
    )
    cached = await db.row(
        session,
        """
        select body, numbers_used from ai_explanations
        where segment_id = :s and language = :l and model_version = :v and day = current_date""",
        s=body.segment_id,
        l=body.language,
        v=version,
    )
    if cached:
        return {
            "text": cached["body"],
            "numbers_used": cached["numbers_used"],
            "cached": True,
            "model": model,
            "ai_suggested": True,
        }
    analysis = await segments_api.analysis(body.segment_id, 12, user, session)
    facts = _facts(analysis)
    await usage.take(session, "explain", user.clerk_id)
    lang = "Bahasa Melayu" if body.language == "ms" else "English"
    prompt = (
        f"Explain in {lang}, in 2 or 3 short plain sentences, why this road matters for repair planning. "
        "Use only these facts; do not add any number that is not listed. Mention the most important "
        "reasons first. Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False)
    )
    try:
        out = await gemini.generate(session, model, [prompt], Explanation)
        text_out, used, grounded = out.text.strip(), out.numbers_used, _numbers_are_grounded(out.text, facts)
    except ApiError:
        text_out, used, grounded = _template(facts, body.language), ["priority_score", "potholes_12m", "adt"], False
    if not grounded:
        text_out, used = _template(facts, body.language), ["priority_score", "potholes_12m", "adt"]
    await session.execute(
        text("""
        insert into ai_explanations (segment_id, language, model_version, day, body, numbers_used)
        values (:s, :l, :v, current_date, :b, :u) on conflict do nothing"""),
        {"s": body.segment_id, "l": body.language, "v": version, "b": text_out, "u": used},
    )
    await session.commit()
    return {
        "text": text_out,
        "numbers_used": used,
        "cached": False,
        "model": model if grounded else "template",
        "ai_suggested": grounded,
    }


# --- Decision Assistant (T7.2) --------------------------------------------------------------


class AssistantIn(BaseModel):
    message: str = Field(min_length=2, max_length=600)
    history: list[dict] = Field(default_factory=list, max_length=10)
    language: str = Field(default="en", pattern="^(en|ms)$")


def _schema(props: dict, required: list[str] | None = None) -> types.Schema:
    return types.Schema(
        type="OBJECT", properties={k: types.Schema(**v) for k, v in props.items()}, required=required or []
    )


TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="find_segments",
                description="Find roads by name or route number (e.g. FT1, A13).",
                parameters=_schema({"query": {"type": "STRING"}}, ["query"]),
            ),
            types.FunctionDeclaration(
                name="get_priority_list",
                description="Roads ranked by repair priority within a scope.",
                parameters=_schema(
                    {
                        "state": {"type": "STRING", "description": "State name or code, e.g. Perak or A"},
                        "district": {"type": "STRING", "description": "District name, e.g. Kinta"},
                        "road_class": {"type": "STRING", "enum": ["FEDERAL", "STATE", "MUNICIPAL", "EXPRESSWAY"]},
                        "limit": {"type": "INTEGER"},
                    }
                ),
            ),
            types.FunctionDeclaration(
                name="get_segment_analysis",
                description="Potholes, traffic, safety, weather and priority for one road segment.",
                parameters=_schema({"segment_id": {"type": "INTEGER"}}, ["segment_id"]),
            ),
            types.FunctionDeclaration(
                name="get_zone_summary",
                description="Open incidents, overdue repairs and top roads for a district.",
                parameters=_schema({"district": {"type": "STRING"}}, ["district"]),
            ),
            types.FunctionDeclaration(
                name="get_predictions",
                description="Hazard chances in the next 7 and 30 days for a road segment.",
                parameters=_schema({"segment_id": {"type": "INTEGER"}}, ["segment_id"]),
            ),
            types.FunctionDeclaration(
                name="get_active_warnings",
                description="Weather and flood warnings in force now.",
                parameters=_schema({"state": {"type": "STRING"}}),
            ),
        ]
    )
]

SYSTEM = """You help JKR officers in Malaysia decide which roads to repair first. Answer only from tool
results; never invent numbers, roads or agencies. Always cite the segment IDs you rely on, like
(segment 5594). Keep answers short: a ranked list or 2–4 sentences. If tools return nothing
useful, say what you couldn't find."""


async def _resolve_state(session, value: str | None) -> str | None:
    if not value:
        return None
    return await db.scalar(session, "select code from states where upper(code) = upper(:v) or name ilike :v", v=value)


async def _district_id(session, name: str | None) -> str | None:
    if not name:
        return None
    return await db.scalar(
        session, "select id::text from districts where name ilike :n order by name limit 1", n=name.strip()
    )


async def _run_tool(session: AsyncSession, user: CurrentUser, sc: scope.Scope, name: str, args: dict) -> dict:
    if name == "find_segments":
        found = await segments.search(session, str(args.get("query", "")), sc.sql, 8, **sc.params)
        return {
            "roads": [
                {k: r[k] for k in ("segment_id", "name", "ref", "road_class", "district", "owner")}
                | {"length_km": float(r["length_km"] or 0)}
                for r in found
            ]
        }
    if name == "get_priority_list":
        state = await _resolve_state(session, args.get("state"))
        district = await _district_id(session, args.get("district"))
        req, params = scope.requested(state, district, args.get("road_class"))
        profile = await ranking.default_profile(session)
        items, total = await ranking.rank(
            session,
            profile["weights"],
            sc.sql,
            req,
            {**sc.params, **params},
            limit=min(int(args.get("limit") or 5), 10),
        )
        return {
            "total_roads_in_scope": total,
            "roads": [
                {
                    k: i[k]
                    for k in (
                        "rank",
                        "segment_id",
                        "name",
                        "ref",
                        "road_class",
                        "district",
                        "owner",
                        "score",
                        "recommended_action",
                    )
                }
                | {"top_reasons": sorted(i["components"], key=lambda c: -i["components"][c]["contribution"])[:3]}
                for i in items
            ],
        }
    if name in ("get_segment_analysis", "get_predictions"):
        a = await segments_api.analysis(int(args["segment_id"]), 12, user, session)
        return (
            {"segment_id": a["segment_id"], "predictions": a["predictions"]}
            if name == "get_predictions"
            else _facts(a) | {"segment_id": a["segment_id"]}
        )
    if name == "get_zone_summary":
        district = await _district_id(session, args.get("district"))
        if not district:
            return {"error": "district not found"}
        return await zone_summary(session, user, district)
    if name == "get_active_warnings":
        state = await _resolve_state(session, args.get("state"))
        rows = await db.rows(
            session,
            """
            select kind, severity, left(area_text, 200) as area, valid_to from weather_warnings w
            where now() between coalesce(valid_from, now()) and coalesce(valid_to, now())
              and (cast(:s as text) is null or ST_Intersects(w.geom, (select geom from states where code = :s)))
            limit 10""",
            s=state,
        )
        return {"warnings": [{**r, "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None} for r in rows]}
    return {"error": f"unknown tool {name}"}


def _segment_ids(value: Any) -> set[int]:
    found: set[int] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "segment_id" and isinstance(v, int):
                found.add(v)
            else:
                found |= _segment_ids(v)
    elif isinstance(value, list):
        for v in value:
            found |= _segment_ids(v)
    return found


@router.post("/assistant")
async def assistant(
    body: AssistantIn, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    await usage.take(session, "assistant", user.clerk_id)
    sc = await scope.for_user(session, user)
    contents: list[types.Content] = []
    for turn in body.history[-6:]:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=str(turn.get("content", ""))[:1500])]))
    lang = " Reply in Bahasa Melayu." if body.language == "ms" else ""
    contents.append(types.Content(role="user", parts=[types.Part(text=body.message + lang)]))
    config = types.GenerateContentConfig(
        tools=TOOLS,
        system_instruction=SYSTEM,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    calls_made: list[dict] = []
    cited: set[int] = set()
    model = get_settings().gemini_model_vision
    try:
        for _ in range(MAX_TOOL_CALLS + 1):
            resp = await gemini.client().aio.models.generate_content(model=model, contents=contents, config=config)
            await usage.bump(session, "gemini")
            calls = resp.function_calls or []
            if not calls or len(calls_made) >= MAX_TOOL_CALLS:
                answer = (resp.text or "").strip()
                break
            contents.append(resp.candidates[0].content)
            parts = []
            for call in calls[: MAX_TOOL_CALLS - len(calls_made)]:
                args = dict(call.args or {})
                result = await _run_tool(session, user, sc, call.name, args)
                cited |= _segment_ids(result)
                calls_made.append({"tool": call.name, "args": args})
                parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            contents.append(types.Content(role="tool", parts=parts))
        else:
            answer = ""
    except (genai_errors.APIError, ApiError) as exc:
        await session.commit()
        raise ApiError(503, "AI_UNAVAILABLE", "The assistant isn't available right now. Try again shortly.") from exc
    await session.commit()
    mentioned = {int(n) for n in re.findall(r"segment\s+(\d+)", answer, re.I)}
    segment_ids = sorted(mentioned & cited) or sorted(mentioned) or sorted(cited)[:10]
    if not answer:
        answer = "I couldn't find an answer in the system data. Try naming a district or a road."
    return {
        "answer": answer,
        "segments": segment_ids,
        "tool_calls": calls_made,
        "map_action": {"type": "highlight_segments", "segment_ids": segment_ids} if segment_ids else None,
        "disclaimer": f"AI-suggested. Figures come from system data as of {datetime.now(UTC):%d %b %Y}.",
    }
