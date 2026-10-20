from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import STAFF, CurrentUser, require_role
from app.core.db import get_session
from app.queries import priority as ranking
from app.queries import segments
from app.services import scope

router = APIRouter(prefix="/segments", tags=["segments"])


def _agency(r: dict, prefix: str) -> dict:
    out = {"id": str(r[f"{prefix}_id"]) if r[f"{prefix}_id"] else None, "name": r[prefix], "type": r[f"{prefix}_type"]}
    if prefix == "owner" and r.get("owner_contact"):
        out["contact"] = r["owner_contact"]
    if prefix == "maintainer":
        out["last_verified"] = r["maintainer_last_verified"].isoformat() if r["maintainer_last_verified"] else None
        out["contract_valid_to"] = (
            r["maintainer_contract_valid_to"].isoformat() if r["maintainer_contract_valid_to"] else None
        )
    return out


@router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    sc = await scope.for_user(session, user)
    found = await segments.search(session, q, sc.sql, limit, **sc.params)
    items = [
        {
            **{k: r[k] for k in ("segment_id", "name", "ref", "road_class", "district", "owner")},
            "state": {"code": r["state_code"], "name": r["state_name"]},
            "segments": int(r["segments"]),
            "length_km": float(r["length_km"] or 0),
        }
        for r in found
    ]
    return {"items": items, "total": len(items), "page": 1, "page_size": limit}


@router.get("/locate")
async def locate(
    lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), session: AsyncSession = Depends(get_session)
):
    """Who owns and maintains the road here (FR-MAP-06). Open to everyone."""
    r, distance = await segments.nearest(session, lat, lng)
    return {
        "segment_id": r["segment_id"],
        "distance_m": round(distance),
        "name": r["name"],
        "ref": r["ref"],
        "road_class": r["road_class"],
        "federal_category": r["federal_category"],
        "state": {"code": r["state_code"], "name": r["state_name"]},
        "district": r["district"],
        "owner": _agency(r, "owner"),
        "maintainer": _agency(r, "maintainer"),
        "jurisdiction_source": r["jurisdiction_source"],
    }


@router.get("/{segment_id}/analysis")
async def analysis(
    segment_id: int,
    months: int = Query(default=12, ge=3, le=36),
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """Road Analysis (T6.9, FR-RA-02..05). Every number comes from the database."""
    sc = await scope.for_user(session, user)
    seg = await segments.get(session, segment_id, sc.sql, **sc.params)
    length_km = max(float(seg["length_m"] or 0) / 1000, 0.05)
    window = "date_trunc('month', now() at time zone 'Asia/Kuala_Lumpur') - make_interval(months => :months - 1)"
    monthly = await db.rows(
        session,
        f"""
        with m as (select generate_series({window}, date_trunc('month', now() at time zone 'Asia/Kuala_Lumpur'),
                                          interval '1 month')::date as month)
        select to_char(m.month, 'YYYY-MM') as month,
            (select count(*) from incidents i where i.segment_id = :sid and i.hazard_type = 'POTHOLE'
               and i.status not in ('REJECTED', 'DUPLICATE')
               and date_trunc('month', i.reported_at at time zone 'Asia/Kuala_Lumpur') = m.month) as potholes,
            (select count(*) from incidents i where i.segment_id = :sid and i.hazard_type = 'FALLEN_TREE'
               and i.status not in ('REJECTED', 'DUPLICATE')
               and date_trunc('month', i.reported_at at time zone 'Asia/Kuala_Lumpur') = m.month) as fallen_tree,
            (select count(*) from incidents i where i.segment_id = :sid and i.hazard_type = 'SINKHOLE'
               and i.status not in ('REJECTED', 'DUPLICATE')
               and date_trunc('month', i.reported_at at time zone 'Asia/Kuala_Lumpur') = m.month) as sinkhole,
            (select count(*) from weather_warnings w, road_segments s where s.id = :sid and w.kind <> 'FLOOD'
               and ST_Intersects(w.geom, s.geom)
               and w.valid_from < m.month + interval '1 month' and coalesce(w.valid_to, w.valid_from) >= m.month)
               as weather_warnings,
            (select count(*) from weather_warnings w, road_segments s where s.id = :sid and w.kind = 'FLOOD'
               and ST_DWithin(w.geom::geography, s.geom::geography, 0)
               and w.valid_from < m.month + interval '1 month' and coalesce(w.valid_to, w.valid_from) >= m.month)
               as flood_warnings
        from m order by m.month""",
        sid=segment_id,
        months=months,
    )
    reports = await db.rows(
        session,
        f"""
        select reported_at from incidents where segment_id = :sid and hazard_type = 'POTHOLE'
          and status not in ('REJECTED', 'DUPLICATE') and reported_at >= {window}
        order by reported_at""",
        sid=segment_id,
        months=months,
    )
    gaps = [(b["reported_at"] - a["reported_at"]).days for a, b in zip(reports, reports[1:], strict=False)]
    safety = await db.row(
        session,
        """
        select coalesce(sum(deaths), 0) as deaths, coalesce(sum(injuries), 0) as injuries,
               coalesce(json_agg(distinct jsonb_build_object('type', case when is_synthetic then 'SYNTHETIC' else source end,
                                                           'url', source_url)) filter (where id is not null), '[]')
                 as sources
        from accidents where segment_id = :sid and occurred_on >= current_date - interval '3 years'""",
        sid=segment_id,
    )
    congestion = await db.rows(
        session,
        """
        select ts::date as date, round(avg(current_speed / nullif(freeflow_speed, 0))::numeric, 2)::float as avg_ratio
        from traffic_snapshots where segment_id = :sid and ts > now() - interval '30 days'
        group by 1 order by 1""",
        sid=segment_id,
    )
    rain = await db.row(
        session,
        """
        select round(sum(rain_mm) filter (where w.date > current_date - 7 and not w.is_forecast)::numeric, 1)::float as rain_7d,
               round(sum(rain_mm) filter (where w.date > current_date - 30 and not w.is_forecast)::numeric, 1)::float as rain_30d,
               round(sum(rain_mm) filter (where w.is_forecast and w.date <= current_date + 7)::numeric, 1)::float
                 as forecast_7d
        from weather_daily w join road_segments s on s.cell_id = w.cell_id where s.id = :sid""",
        sid=segment_id,
    )
    predictions = await db.rows(
        session,
        """
        select hazard_type, horizon_days, round(probability::numeric, 3)::float as probability, risk_level,
               expand_factors(top_factors) as top_factors
        from predictions where segment_id = :sid order by hazard_type, horizon_days""",
        sid=segment_id,
    )
    profile = await ranking.default_profile(session)
    ranked, _ = await ranking.rank(
        session,
        profile["weights"],
        sc.sql,
        "s.district_id = cast(:d as uuid)",
        {**sc.params, "d": str(seg["district_id"])},
        limit=1,
        segment_id=segment_id,
    )
    flood_known = await db.scalar(session, "select exists(select 1 from weather_warnings where kind = 'FLOOD')")
    total_potholes = sum(m["potholes"] for m in monthly)
    return {
        "segment_id": segment_id,
        **segments.summary(seg),
        "length_km": round(length_km, 2),
        "pothole_frequency": {
            "per_km_per_month": round(total_potholes / length_km / months, 2),
            "recurrence_days": round(sum(gaps) / len(gaps)) if gaps else None,
            "series": [{"month": m["month"], "count": m["potholes"]} for m in monthly],
        },
        "traffic": {
            "adt": seg["adt"],
            "heavy_pct": float(seg["heavy_pct"]) if seg["heavy_pct"] is not None else None,
            "adt_source": seg["adt_source"],
            "estimated": seg["adt_source"] == "CLASS_DEFAULT",
            "congestion_series": congestion,
        },
        "natural_events": {
            "flood_available": bool(flood_known),
            "series": [
                {
                    "month": m["month"],
                    "fallen_tree": m["fallen_tree"],
                    "sinkhole": m["sinkhole"],
                    "weather_warnings": m["weather_warnings"],
                    "flood_warnings": m["flood_warnings"] if flood_known else None,
                }
                for m in monthly
            ],
        },
        "weather": rain,
        "safety": {
            "deaths_3y": int(safety["deaths"]),
            "injuries_3y": int(safety["injuries"]),
            "sources": safety["sources"],
        },
        "predictions": predictions,
        "priority": (
            {
                "score": ranked[0]["score"],
                "rank_in_district": ranked[0]["rank_in_district"],
                "components": ranked[0]["components"],
                "recommended_action": ranked[0]["recommended_action"],
                "refer_to": ranked[0]["refer_to"],
            }
            if ranked
            else None
        ),
        "geology": {
            "karst": seg["karst"],
            "ex_mining": seg["ex_mining"],
            "tree_cover": float(seg["tree_cover"]) if seg["tree_cover"] is not None else None,
        },
    }


@router.get("/{segment_id}")
async def detail(
    segment_id: int, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    sc = await scope.for_user(session, user)
    r = await segments.get(session, segment_id, sc.sql, **sc.params)
    return {
        **segments.summary(r),
        "owner": _agency(r, "owner"),
        "maintainer": _agency(r, "maintainer"),
        "osm_highway": r["osm_highway"],
        "surface": r["surface"],
        "lanes": r["lanes"],
        "adt": r["adt"],
        "heavy_pct": float(r["heavy_pct"]) if r["heavy_pct"] is not None else None,
        "adt_source": r["adt_source"],
        "karst": r["karst"],
        "ex_mining": r["ex_mining"],
        "tree_cover": float(r["tree_cover"]) if r["tree_cover"] is not None else None,
        "criticality": float(r["criticality"]) if r["criticality"] is not None else None,
        "jurisdiction_source": r["jurisdiction_source"],
        "geometry": r["geometry"],
    }
