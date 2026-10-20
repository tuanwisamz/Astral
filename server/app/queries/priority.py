"""Priority ranking, computed live in SQL within the requested scope (spec §6, plan D1).

segment_components (materialized, refreshed after the nightly ML run) holds the slow raw
components. Severity, recurrence and SLA-overdue come live from incidents, so a status change
re-ranks at once. Percentile ranks are taken within the candidate set, which is exactly the
scope the person asked for. services.priority turns percentiles into a score and actions.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.queries.incidents import OPEN_SQL, OVERDUE_SQL
from app.services.priority import (
    COMPONENTS,
    DEFAULT_WEIGHTS,
    SegmentState,
    normalise_weights,
    recommended_action,
    score,
)

# Spec §6: severity weight per type; a fallen tree only counts double when it blocks a lane
# (severity 5, "lane unsafe or blocked").
TYPE_WEIGHT_SQL = """case i.hazard_type when 'SINKHOLE' then 3
                     when 'FALLEN_TREE' then (case when i.severity >= 5 then 2 else 1 end) else 1 end"""

RANK_SQL = f"""
with cand as (
    select s.id, s.district_id, s.road_class, sc.usage, sc.usage_estimated, coalesce(sc.safety, 0) as safety,
           sc.predicted, coalesce(sc.criticality, 0) as criticality
    from road_segments s
    join segment_components sc on sc.segment_id = s.id
    where ({{scope}}) and ({{requested}})
),
inc as (
    select i.segment_id,
        sum(case when {OPEN_SQL} then i.severity * {TYPE_WEIGHT_SQL} else 0 end) as severity,
        count(*) filter (where i.hazard_type = 'POTHOLE' and i.status not in ('REJECTED', 'DUPLICATE')
                         and i.reported_at > now() - interval '180 days') as recurrence,
        count(*) filter (where {OPEN_SQL} and {OVERDUE_SQL}) as sla,
        count(*) filter (where {OPEN_SQL} and i.hazard_type = 'SINKHOLE') as open_sinkholes,
        coalesce(bool_or({OPEN_SQL} and i.hazard_type = 'FALLEN_TREE' and i.severity >= 5), false) as blocking_tree,
        max(case when {OPEN_SQL} and i.hazard_type = 'POTHOLE' then i.severity end) as max_pothole_severity,
        count(*) filter (where i.hazard_type = 'POTHOLE' and i.status not in ('REJECTED', 'DUPLICATE')
                         and i.reported_at > now() - interval '90 days') as potholes_90d,
        count(*) filter (where {OPEN_SQL}) as open_incidents
    from incidents i
    where i.segment_id in (select id from cand)
    group by i.segment_id
),
-- percentile_cont isn't a window function, so district medians come from a grouped CTE.
med as (
    select district_id, percentile_cont(0.5) within group (order by predicted) as predicted_med
    from cand group by district_id
),
filled as (
    -- NULLs must be filled before ranking: percent_rank() sorts them last, i.e. as the worst roads.
    select c.id, c.district_id, c.usage, c.safety, c.criticality,
           coalesce(c.predicted, m.predicted_med, 0) as predicted,
           c.usage_estimated, c.predicted is null as predicted_estimated,
           coalesce(x.severity, 0) as severity, coalesce(x.recurrence, 0) as recurrence, coalesce(x.sla, 0) as sla,
           coalesce(x.open_sinkholes, 0) as open_sinkholes, coalesce(x.blocking_tree, false) as blocking_tree,
           coalesce(x.max_pothole_severity, 0) as max_pothole_severity,
           coalesce(x.potholes_90d, 0) as potholes_90d, coalesce(x.open_incidents, 0) as open_incidents
    from cand c left join inc x on x.segment_id = c.id left join med m on m.district_id = c.district_id
),
ranked as (
    select f.*,
        percent_rank() over (order by f.safety) as p_safety,
        percent_rank() over (order by f.usage) as p_usage,
        percent_rank() over (order by f.severity) as p_severity,
        percent_rank() over (order by f.predicted) as p_predicted,
        percent_rank() over (order by f.recurrence) as p_recurrence,
        percent_rank() over (order by f.criticality) as p_criticality,
        percent_rank() over (order by f.sla) as p_sla
    from filled f
),
scored as (
    select r.*, 100 * (:w_safety * p_safety + :w_usage * p_usage + :w_severity * p_severity
                       + :w_predicted * p_predicted + :w_recurrence * p_recurrence
                       + :w_criticality * p_criticality + :w_sla * p_sla) as score
    from ranked r
),
final as (
    select sc.*, rank() over (partition by sc.district_id order by sc.score desc, sc.id) as rank_in_district,
           row_number() over (order by sc.score desc, sc.id) as rank, count(*) over () as total
    from scored sc
)
select f.*, s.name, s.ref, s.road_class, s.state_code, d.name as district,
       ST_AsGeoJSON(ST_SimplifyPreserveTopology(s.geom, 0.00005), 6)::json as geometry,
       o.name as owner, m.name as maintainer
from final f
join road_segments s on s.id = f.id
left join jurisdiction_overrides jo on jo.segment_id = s.id
left join districts d on d.id = s.district_id
left join agencies o on o.id = coalesce(jo.owner_agency_id, s.owner_agency_id)
left join agencies m on m.id = coalesce(jo.maintainer_agency_id, s.maintainer_agency_id)
where {{page_filter}}
order by f.rank
limit :limit offset :offset
"""


def _item(r: dict, weights: dict[str, float]) -> dict:
    estimated = {k for k, flag in (("usage", r["usage_estimated"]), ("predicted", r["predicted_estimated"])) if flag}
    total, components = score({k: float(r[f"p_{k}"]) for k in COMPONENTS}, weights, estimated)
    action, refer = recommended_action(
        SegmentState(
            road_class=r["road_class"],
            owner=r["owner"],
            maintainer=r["maintainer"],
            open_sinkhole=r["open_sinkholes"] > 0,
            blocking_tree=r["blocking_tree"],
            max_pothole_severity=int(r["max_pothole_severity"]),
            potholes_90d=int(r["potholes_90d"]),
            max_predicted=float(r["predicted"] or 0),
            open_incidents=int(r["open_incidents"]),
            pbt=r["owner"] if r["road_class"] == "MUNICIPAL" else None,
        )
    )
    if r["open_sinkholes"] > 0:
        refer = [a if a != "JMG" else "Jabatan Mineral dan Geosains Malaysia" for a in refer]
    return {
        "rank": int(r["rank"]),
        "rank_in_district": int(r["rank_in_district"]),
        "segment_id": r["id"],
        "name": r["name"],
        "ref": r["ref"],
        "road_class": r["road_class"],
        "district": r["district"],
        "owner": r["owner"],
        "maintainer": r["maintainer"],
        "score": total,
        "components": components,
        "recommended_action": action,
        "geometry": r["geometry"],
        "refer_to": refer,
    }


async def rank(
    session: AsyncSession,
    weights: dict[str, float],
    scope_sql: str,
    requested_sql: str,
    params: dict,
    limit: int = 50,
    offset: int = 0,
    segment_id: int | None = None,
) -> tuple[list[dict], int]:
    w = normalise_weights(weights)
    page_filter = "f.id = :only_segment" if segment_id is not None else "true"
    sql = RANK_SQL.format(scope=scope_sql, requested=requested_sql, page_filter=page_filter)
    extra = {"only_segment": segment_id} if segment_id is not None else {}
    found = await db.rows(
        session, sql, limit=limit, offset=offset, **{f"w_{k}": v for k, v in w.items()}, **params, **extra
    )
    total = int(found[0]["total"]) if found else 0
    return [_item(r, w) for r in found], total


async def default_profile(session: AsyncSession) -> dict:
    found = await db.row(
        session,
        """
        select id::text as id, name, weights from priority_profiles where is_default order by name limit 1""",
    )
    if found is None:
        return {"id": None, "name": "Default", "weights": dict(DEFAULT_WEIGHTS)}
    return found
