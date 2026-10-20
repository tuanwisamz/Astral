"""Synthetic demo data (T1.8, architechture.md §16): 12 months of incidents and 3 years of
accidents on real pilot segments (Kinta, Kuala Lumpur), with seasonality and geology.

Rules from the plan:
- Its own weights and per-road noise, deliberately different from the rule-based baseline,
  so "the model beats the baseline" (T6.3) means something.
- A fixed seed, so every run gives the same data.
- Every row is_synthetic; a rerun replaces only synthetic rows.
- The M0 demo storyline is planted on top (see plant_storyline).

    .venv\\Scripts\\python -m app.ml.synthetic          (from server/)
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.ml.common import connect, pilot_segments, weather
from app.services import sla

SEED = 20261019
DAYS = 365
TARGETS = {"POTHOLE": 5200, "SINKHOLE": 32, "FALLEN_TREE": 480}  # expected per year across both pilots
ACCIDENTS_3Y = 950
CLASS_POTHOLE = {"FEDERAL": 1.3, "STATE": 1.0, "MUNICIPAL": 0.55, "EXPRESSWAY": 0.45, "UNKNOWN": 0.7}
CLASS_CRASH = {"FEDERAL": 1.5, "STATE": 1.0, "MUNICIPAL": 0.45, "EXPRESSWAY": 1.2, "UNKNOWN": 0.6}
SEVERITY_P = {
    "POTHOLE": [0.15, 0.30, 0.30, 0.18, 0.07],
    "FALLEN_TREE": [0.05, 0.15, 0.30, 0.20, 0.30],
    "SINKHOLE": [0.0, 0.05, 0.25, 0.35, 0.35],
}
SOURCES = (["PUBLIC", "NEWS", "OFFICER"], [0.72, 0.13, 0.15])
LIFECYCLE = ["REPORTED", "VERIFIED", "ASSIGNED", "MITIGATED", "RESOLVED"]
ACTOR = "synthetic"


@dataclass
class Event:
    segment: int
    day: int  # index into the simulated days
    hazard: str


def _daily_factors(w: pd.DataFrame, cells: list[str], days: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per day × cell weather drivers. Missing cells or days fall back to the pilot average."""
    pivot = {
        k: w.pivot_table(index="date", columns="cell_id", values=k).reindex(index=days, columns=cells)
        for k in ("rain", "rain_hr", "gust")
    }
    for k, p in pivot.items():
        pivot[k] = p.apply(lambda col: col.fillna(col.mean())).fillna(p.stack().mean() if p.size else 0)
    rain, rain_hr, gust = (pivot[k].to_numpy() for k in ("rain", "rain_hr", "gust"))
    r = pd.DataFrame(rain)
    rain_7d = r.rolling(7, min_periods=1).sum().to_numpy()
    rain_30d = r.rolling(30, min_periods=1).sum().to_numpy()
    prev_30d = r.shift(30).rolling(30, min_periods=1).sum().fillna(r.mean()).to_numpy()
    heavy_72h = pd.DataFrame(rain_hr).rolling(3, min_periods=1).max().to_numpy()
    month = days.month.to_numpy()[:, None]
    intermonsoon = np.where(np.isin(month, [4, 5, 10, 11]), 1.8, 1.0)
    swing = np.clip(rain_30d / (prev_30d + 20) - 1, 0, 3)  # a wet month after a dry one
    return {
        "POTHOLE": 1 + 1.2 * np.minimum(rain_7d / 120, 2.5),
        "SINKHOLE": (1 + 2 * swing) * (1 + heavy_72h / 40),
        "FALLEN_TREE": (1 + gust / 45) ** 2 * intermonsoon * (1 + rain_hr / 25),
    }


def simulate(
    segs: pd.DataFrame, factors: dict[str, np.ndarray], cell_idx: np.ndarray, rng: np.random.Generator
) -> list[Event]:
    km = np.maximum(segs.length_m.to_numpy() / 1000, 0.02)
    # Heavy-tailed per-road proneness: a minority of worn segments fail again and again, as
    # real roads do. History features can reveal it; static attributes can't.
    noise = {
        "POTHOLE": rng.lognormal(0, 1.3, len(segs)),
        "SINKHOLE": rng.lognormal(0, 0.8, len(segs)),
        "FALLEN_TREE": rng.lognormal(0, 1.0, len(segs)),
    }
    static = {
        "POTHOLE": segs.road_class.map(CLASS_POTHOLE).to_numpy()
        * (segs.adt.to_numpy() / 10000) ** 0.6
        * (1 + 2 * segs.heavy_pct.to_numpy())
        * km
        * noise["POTHOLE"],
        "SINKHOLE": (1 + 7 * segs.karst.to_numpy() + 4 * segs.ex_mining.to_numpy()) * km * noise["SINKHOLE"],
        "FALLEN_TREE": (0.02 + segs.tree_cover.to_numpy()) ** 1.5 * km * noise["FALLEN_TREE"],
    }
    base = {h: TARGETS[h] / (static[h] * factors[h][:, cell_idx]).sum() * (DAYS / len(factors[h])) for h in TARGETS}
    last_pothole = np.full(len(segs), -10_000)
    events: list[Event] = []
    for d in range(len(factors["POTHOLE"])):
        for h in TARGETS:
            rate = base[h] * static[h] * factors[h][d, cell_idx]
            if h == "POTHOLE":
                rate = rate * np.where(d - last_pothole <= 45, 2.5, 1.0)  # a fresh pothole means a weak base
            hits = np.flatnonzero(rng.poisson(rate))
            if h == "POTHOLE":
                last_pothole[hits] = d
            events += [Event(int(segs.id.iloc[i]), d, h) for i in hits]
    return events


def lifecycle(reported: datetime, now: datetime, rng: np.random.Generator) -> tuple[str, dict[str, datetime]]:
    """Pick a final status by age, then fill transition times; anything in the future isn't reached."""
    age_days = (now - reported).total_seconds() / 86400
    if rng.random() < 0.04:
        return "REJECTED", {"REJECTED": reported + timedelta(hours=float(rng.uniform(1, 12)))}
    if age_days > 14:
        target = rng.choice(["RESOLVED", "MITIGATED", "ASSIGNED"], p=[0.92, 0.05, 0.03])
    elif age_days > 3:
        target = rng.choice(
            ["RESOLVED", "MITIGATED", "ASSIGNED", "VERIFIED", "REPORTED"], p=[0.4, 0.25, 0.2, 0.1, 0.05]
        )
    else:
        target = rng.choice(["REPORTED", "VERIFIED", "ASSIGNED", "MITIGATED"], p=[0.35, 0.3, 0.25, 0.1])
    times = {"VERIFIED": reported + timedelta(hours=float(rng.uniform(0.5, 6)))}
    times["ASSIGNED"] = times["VERIFIED"] + timedelta(hours=float(rng.uniform(0.5, 4)))
    # Most temporary patches land inside 24 h; a tail runs late, which creates overdue history.
    times["MITIGATED"] = times["ASSIGNED"] + timedelta(hours=float(rng.gamma(2.0, 8.0)))
    times["RESOLVED"] = times["MITIGATED"] + timedelta(days=float(rng.uniform(1, 5)))
    reached = {s: t for s, t in times.items() if LIFECYCLE.index(s) <= LIFECYCLE.index(target) and t <= now}
    status = max(reached, key=lambda s: LIFECYCLE.index(s)) if reached else "REPORTED"
    return status, reached


def build_incidents(
    segs: pd.DataFrame, events: list[Event], start: datetime, now: datetime, rng: np.random.Generator
) -> tuple[list[dict], list[dict]]:
    by_id = segs.set_index("id")
    incidents, timeline = [], []
    for e in events:
        hour = rng.uniform(13, 19) if e.hazard == "FALLEN_TREE" else rng.uniform(7, 21)
        reported = start + timedelta(days=e.day, hours=float(hour) - 8)  # local hour → UTC
        if reported > now:
            continue
        incidents.append(make_incident(by_id.loc[e.segment], e.segment, e.hazard, reported, now, rng))
    for inc in incidents:
        timeline += inc.pop("_events")
    return incidents, timeline


def make_incident(
    seg: pd.Series,
    segment_id: int,
    hazard: str,
    reported: datetime,
    now: datetime,
    rng: np.random.Generator,
    *,
    status: str | None = None,
    severity: int | None = None,
    confirmations: int | None = None,
) -> dict:
    inc_id = uuid.UUID(bytes=rng.bytes(16), version=4)
    source = str(rng.choice(SOURCES[0], p=SOURCES[1]))
    if status is None:
        status, times = lifecycle(reported, now, rng)
    else:
        times = {}
        for s in LIFECYCLE[1 : LIFECYCLE.index(status) + 1]:
            times[s] = reported + timedelta(minutes=30 * len(times) + 20)
    temp_due, perm_due = sla.deadlines(seg.road_class, reported)
    events = [
        {
            "incident_id": inc_id,
            "action": "CREATE",
            "from_status": None,
            "to_status": "REPORTED",
            "created_at": reported,
        }
    ]
    prev = "REPORTED"
    for s, t in sorted(times.items(), key=lambda kv: kv[1]):
        events.append({"incident_id": inc_id, "action": "STATUS", "from_status": prev, "to_status": s, "created_at": t})
        prev = s
    return {
        "id": inc_id,
        "hazard_type": hazard,
        "severity": severity or int(rng.choice(5, p=SEVERITY_P[hazard]) + 1),
        "status": status,
        "source": source,
        "confirmations": confirmations or 1 + int(rng.poisson(0.4)),
        "segment_id": segment_id,
        "frac": float(rng.uniform(0.05, 0.95)),
        "reported_at": reported,
        "verified_at": times.get("VERIFIED"),
        "assigned_at": times.get("ASSIGNED"),
        "mitigated_at": times.get("MITIGATED"),
        "resolved_at": times.get("RESOLVED"),
        "sla_temp_due_at": temp_due,
        "sla_perm_due_at": perm_due,
        "_events": events,
    }


def build_accidents(segs: pd.DataFrame, now: datetime, rng: np.random.Generator) -> list[dict]:
    km = np.maximum(segs.length_m.to_numpy() / 1000, 0.02)
    weight = (
        (segs.adt.to_numpy() / 10000)
        * km
        * segs.road_class.map(CLASS_CRASH).to_numpy()
        * rng.lognormal(0, 0.7, len(segs))
    )
    counts = rng.poisson(weight / weight.sum() * ACCIDENTS_3Y)
    out = []
    for i in np.flatnonzero(counts):
        for _ in range(counts[i]):
            fatal = rng.random() < 0.08
            out.append(
                {
                    "segment_id": int(segs.id.iloc[i]),
                    "frac": float(rng.uniform(0.05, 0.95)),
                    "occurred_on": (now - timedelta(days=float(rng.uniform(0, 3 * 365)))).date(),
                    "deaths": int(rng.integers(1, 3)) if fatal else 0,
                    "injuries": int(rng.poisson(1.3)),
                }
            )
    return out


def _pick(segs: pd.DataFrame, mask, prefer: str | None = None, sort: str = "length_m") -> pd.Series:
    """A named road for each scene, so the demo talks about places people recognise."""
    cand = segs[mask & segs.name.notna()]
    if prefer is not None:
        named = cand[cand.name.str.fullmatch(prefer, case=False)]
        cand = named if len(named) else cand
    return cand.sort_values([sort, "id"], ascending=[False, True]).iloc[0]


def plant_storyline(
    segs: pd.DataFrame, now: datetime, rng: np.random.Generator
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """The demo script's scenes (task.md), on real roads: Kinta's #1 federal road, an open
    sinkhole on Kinta karst, a lane-blocking tree in KL, and a few overdue repairs."""
    notes, incs, accs = [], [], []
    kinta = segs.district == "Kinta"
    top = _pick(segs, kinta & (segs.road_class == "FEDERAL"), "Jalan Sultan Azlan Shah")
    for days_ago, sev in ((80, 3), (55, 4), (30, 3)):
        incs.append(make_incident(top, int(top.id), "POTHOLE", now - timedelta(days=days_ago), now, rng, severity=sev))
    incs.append(
        make_incident(
            top,
            int(top.id),
            "POTHOLE",
            now - timedelta(hours=30),
            now,
            rng,
            status="VERIFIED",
            severity=4,
            confirmations=3,
        )
    )
    for deaths, injuries, days_ago in ((1, 2, 400), (1, 4, 210), (0, 3, 60)):
        accs.append(
            {
                "segment_id": int(top.id),
                "frac": 0.5,
                "occurred_on": (now - timedelta(days=days_ago)).date(),
                "deaths": deaths,
                "injuries": injuries,
            }
        )
    notes.append(f"#1 road: {top['name'] or 'unnamed'} ({top.ref}) segment {top.id}")

    sink = _pick(segs, kinta & segs.karst & segs.road_class.isin(["FEDERAL", "STATE"]), "Jalan Tambun")
    incs.append(
        make_incident(
            sink,
            int(sink.id),
            "SINKHOLE",
            now - timedelta(hours=9, minutes=40),
            now,
            rng,
            status="VERIFIED",
            severity=5,
            confirmations=3,
        )
    )
    notes.append(f"open sinkhole: {sink['name'] or 'unnamed'} ({sink.ref}) segment {sink.id}")

    kl = segs.district == "Kuala Lumpur"
    tree = _pick(segs, kl & segs.name.notna() & (segs.tree_cover > 0.3), sort="tree_cover")
    incs.append(
        make_incident(
            tree,
            int(tree.id),
            "FALLEN_TREE",
            now - timedelta(hours=3),
            now,
            rng,
            status="ASSIGNED",
            severity=5,
            confirmations=2,
        )
    )
    notes.append(f"fallen tree blocking a lane: {tree['name']} segment {tree.id}")

    fed = (
        segs[kinta & (segs.road_class == "FEDERAL") & segs.name.notna() & (segs.name != top["name"])]
        .sort_values(["length_m", "id"], ascending=[False, True])
        .head(3)
    )
    for _, seg in fed.iterrows():
        incs.append(
            make_incident(
                seg,
                int(seg.id),
                "POTHOLE",
                now - timedelta(hours=float(rng.uniform(30, 50))),
                now,
                rng,
                status="ASSIGNED",
                severity=4,
            )
        )
    notes.append(f"overdue potholes on {len(fed)} more Kinta federal segments")
    timeline = [e for i in incs for e in i.pop("_events")]
    return incs, accs, timeline, notes


def _copy(cur, sql: str, rows: list[tuple]) -> None:
    with cur.copy(sql) as cp:
        for r in rows:
            cp.write_row(r)


def write(conn, incidents: list[dict], timeline: list[dict], accidents: list[dict]) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from incident_events where incident_id in (select id from incidents where is_synthetic)")
        cur.execute("delete from incidents where is_synthetic")
        cur.execute("delete from accidents where is_synthetic")
        cur.execute("""create temp table syn_inc (id uuid, hazard_type text, severity smallint, status text, source text,
            confirmations int, segment_id bigint, frac float, reported_at timestamptz, verified_at timestamptz,
            assigned_at timestamptz, mitigated_at timestamptz, resolved_at timestamptz, sla_temp_due_at timestamptz,
            sla_perm_due_at timestamptz) on commit drop""")
        cols = [
            "id",
            "hazard_type",
            "severity",
            "status",
            "source",
            "confirmations",
            "segment_id",
            "frac",
            "reported_at",
            "verified_at",
            "assigned_at",
            "mitigated_at",
            "resolved_at",
            "sla_temp_due_at",
            "sla_perm_due_at",
        ]
        _copy(cur, f"copy syn_inc ({', '.join(cols)}) from stdin", [tuple(i[c] for c in cols) for i in incidents])
        cur.execute("""
            insert into incidents (id, ref_no, hazard_type, severity, status, source, confirmations, segment_id,
                                   reported_by, reported_at, verified_at, assigned_at, mitigated_at, resolved_at,
                                   sla_temp_due_at, sla_perm_due_at, is_synthetic, geom)
            select t.id, 'SAR-' || to_char(t.reported_at at time zone 'Asia/Kuala_Lumpur', 'YYYY') || '-'
                       || lpad(nextval('incident_ref_seq')::text, 6, '0'),
                   t.hazard_type, t.severity, t.status, t.source, t.confirmations, t.segment_id, null, t.reported_at,
                   t.verified_at, t.assigned_at, t.mitigated_at, t.resolved_at, t.sla_temp_due_at, t.sla_perm_due_at,
                   true, ST_LineInterpolatePoint(s.geom, t.frac)
            from syn_inc t join road_segments s on s.id = t.segment_id
            order by t.reported_at""")
        _copy(
            cur,
            "copy incident_events (incident_id, actor, action, from_status, to_status, created_at) from stdin",
            [
                (e["incident_id"], ACTOR, e["action"], e["from_status"], e["to_status"], e["created_at"])
                for e in timeline
            ],
        )
        cur.execute("""create temp table syn_acc (segment_id bigint, frac float, occurred_on date, deaths int,
            injuries int) on commit drop""")
        _copy(
            cur,
            "copy syn_acc (segment_id, frac, occurred_on, deaths, injuries) from stdin",
            [(a["segment_id"], a["frac"], a["occurred_on"], a["deaths"], a["injuries"]) for a in accidents],
        )
        cur.execute("""
            insert into accidents (segment_id, occurred_on, deaths, injuries, source, is_synthetic, geom)
            select t.segment_id, t.occurred_on, t.deaths, t.injuries, 'SYNTHETIC', true, ST_LineInterpolatePoint(s.geom, t.frac)
            from syn_acc t join road_segments s on s.id = t.segment_id""")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("refresh materialized view segment_components")
    conn.commit()


def main() -> None:
    rng = np.random.default_rng(SEED)
    now = datetime.now(UTC)
    with connect() as conn:
        segs = pilot_segments(conn)
        cells = sorted(segs.cell_id.unique())
        today = pd.Timestamp(now.astimezone(None).date())
        days = pd.date_range(today - pd.Timedelta(days=DAYS), today - pd.Timedelta(days=1), freq="D")
        w = weather(conn, cells)
        print(f"{len(segs):,} pilot segments, {len(cells)} cells, {len(w):,} weather rows")
        factors = _daily_factors(w, cells, days)
        cell_idx = np.array([cells.index(c) for c in segs.cell_id])
        start = datetime.combine(days[0].date(), datetime.min.time(), UTC)
        events = simulate(segs, factors, cell_idx, rng)
        incidents, timeline = build_incidents(segs, events, start, now, rng)
        story_inc, story_acc, story_events, notes = plant_storyline(segs, now, np.random.default_rng(SEED + 1))
        accidents = build_accidents(segs, now, rng) + story_acc
        incidents += story_inc
        timeline += story_events
        write(conn, incidents, timeline, accidents)
        counts = pd.Series([i["hazard_type"] for i in incidents]).value_counts().to_dict()
        open_now = sum(i["status"] in ("REPORTED", "VERIFIED", "ASSIGNED", "MITIGATED") for i in incidents)
        print(
            f"incidents {len(incidents):,} {counts}; open now {open_now}; events {len(timeline):,}; "
            f"accidents {len(accidents):,} ({sum(a['deaths'] for a in accidents)} deaths)"
        )
        print("storyline:", *notes, sep="\n  ")


if __name__ == "__main__":
    main()
