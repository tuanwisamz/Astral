"""Feature builder (T6.1): one row per segment × date, for all three hazards (architechture.md §10).

History counts use cumulative day arrays (segment × day, cell × day), so any window is one
subtraction. "Forecast" features are the next 7 days' weather: actual weather in training,
Open-Meteo's forecast at prediction time.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.ml.common import frame

CLASSES = ["FEDERAL", "STATE", "MUNICIPAL", "EXPRESSWAY", "UNKNOWN"]
HAZARDS = ["POTHOLE", "SINKHOLE", "FALLEN_TREE"]
EAST_COAST = {"C", "T", "D"}  # NE monsoon Nov–Mar hits these hardest

FEATURES = {
    "POTHOLE": [
        "rain_7d",
        "rain_30d",
        "rain_max_hr_3d",
        "forecast_rain_7d",
        "adt_k",
        "heavy_pct",
        "potholes_30d",
        "potholes_90d",
        "potholes_365d",
        "potholes_per_km_365d",
        "length_km",
        "paved",
        "lanes",
        "class_federal",
        "class_state",
        "class_municipal",
        "class_expressway",
        "monsoon_flag",
    ],
    "SINKHOLE": [
        "karst",
        "ex_mining",
        "sinkholes_cell_365d",
        "dry_wet_swing",
        "rain_max_hr_3d",
        "rain_30d",
        "forecast_rain_7d",
        "class_federal",
        "class_state",
    ],
    "FALLEN_TREE": [
        "forecast_gust_7d",
        "gust_3d",
        "rain_1d",
        "rain_3d",
        "tree_cover",
        "trees_cell_365d",
        "intermonsoon_flag",
        "class_municipal",
        "class_state",
    ],
}


@dataclass
class Context:
    segs: pd.DataFrame
    days: pd.DatetimeIndex
    cells: list[str]
    cell_idx: np.ndarray
    weather: dict[str, np.ndarray]  # name -> day × cell
    seg_cum: dict[str, np.ndarray]  # hazard -> segment × (day + 1), incidents up to and including each day
    cell_cum: dict[str, np.ndarray]  # hazard -> cell × (day + 1)
    hist_offset: int = 365  # index of the first feature day in the history arrays


def segments(conn, pilots_only: bool) -> pd.DataFrame:
    where = (
        (
            "join districts d on d.id = s.district_id where (d.state_code, d.name) in "
            "(('A', 'Kinta'), ('KUL', 'Kuala Lumpur'))"
        )
        if pilots_only
        else ""
    )
    return frame(
        conn,
        f"""
        select s.id, s.road_class, s.state_code, s.cell_id, coalesce(s.lanes, 0) as lanes,
               coalesce(s.surface, 'asphalt') as surface, s.adt, coalesce(s.heavy_pct, 0)::float as heavy_pct,
               coalesce(s.length_m, 0)::float / 1000 as length_km,
               s.karst, s.ex_mining, coalesce(s.tree_cover, 0)::float as tree_cover
        from road_segments s {where} order by s.id""",
    )


def load(conn, segs: pd.DataFrame, start: date, end: date) -> Context:
    """Everything needed for features on [start, end]: weather 60 days before and 7 after."""
    days = pd.date_range(start, end, freq="D")
    cells = sorted(segs.cell_id.dropna().unique())
    cell_pos = {c: i for i, c in enumerate(cells)}
    w = frame(
        conn,
        """
        select cell_id, date, rain_mm::float as rain, rain_max_hr::float as rain_hr, gust_max_kmh::float as gust
        from weather_daily where cell_id = any(%(cells)s) and date between %(a)s and %(b)s""",
        {"cells": cells, "a": start - timedelta(days=60), "b": end + timedelta(days=7)},
    )
    w["date"] = pd.to_datetime(w["date"])
    full = pd.date_range(start - timedelta(days=60), end + timedelta(days=7), freq="D")
    grids = {}
    for col in ("rain", "rain_hr", "gust"):
        g = w.pivot_table(index="date", columns="cell_id", values=col).reindex(index=full, columns=cells)
        # Gaps (cells outside the pilots have only recent history) fall back to that day's mean.
        grids[col] = g.T.fillna(g.mean(axis=1)).T.fillna(0).to_numpy()
    rain, rain_hr, gust = grids["rain"], grids["rain_hr"], grids["gust"]
    off = 60  # index of `start` in the full grid

    def roll(a, n):  # trailing sum over n days, ending at each day
        c = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(a, axis=0)])
        return c[n:] - c[:-n] if n else a

    def fwd_sum(a, n):  # the next n days after each day
        c = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(a, axis=0)])
        out = np.full_like(a, np.nan)
        out[: len(a) - n] = c[n + 1 :] - c[1 : len(a) - n + 1]
        return out

    def trail_max(a, n):
        return pd.DataFrame(a).rolling(n, min_periods=1).max().to_numpy()

    def fwd_max(a, n):
        return pd.DataFrame(a[::-1]).rolling(n, min_periods=1).max().to_numpy()[::-1]

    sel = slice(off, off + len(days))
    rain_7d = np.vstack([np.full((6, len(cells)), np.nan), roll(rain, 7)])
    rain_30d = np.vstack([np.full((29, len(cells)), np.nan), roll(rain, 30)])
    weather = {
        "rain_1d": rain[sel],
        "rain_3d": np.vstack([np.full((2, len(cells)), np.nan), roll(rain, 3)])[sel],
        "rain_7d": rain_7d[sel],
        "rain_30d": rain_30d[sel],
        "rain_prev30": np.vstack([np.full((30, len(cells)), np.nan), rain_30d[:-30]])[sel],
        "rain_max_hr_3d": trail_max(rain_hr, 3)[sel],
        "gust_3d": trail_max(gust, 3)[sel],
        "forecast_rain_7d": fwd_sum(rain, 7)[sel],
        "forecast_gust_7d": np.roll(fwd_max(gust, 7), -1, axis=0)[sel],
    }

    inc = frame(
        conn,
        """
        select segment_id, hazard_type, (reported_at at time zone 'Asia/Kuala_Lumpur')::date as day
        from incidents where status not in ('REJECTED', 'DUPLICATE') and segment_id = any(%(ids)s)
          and reported_at >= %(a)s""",
        {"ids": segs.id.tolist(), "a": start - timedelta(days=365)},
    )
    hist_days = pd.date_range(start - timedelta(days=365), end + timedelta(days=30), freq="D")
    seg_pos = pd.Series(np.arange(len(segs)), index=segs.id)
    seg_cell = segs.cell_id.map(cell_pos).to_numpy()
    seg_cum, cell_cum = {}, {}
    for h in HAZARDS:
        sub = inc[inc.hazard_type == h]
        d_idx = (pd.to_datetime(sub.day) - hist_days[0]).dt.days.to_numpy()
        ok = (d_idx >= 0) & (d_idx < len(hist_days))
        s_idx = seg_pos.reindex(sub.segment_id).to_numpy()[ok]
        counts = np.zeros((len(segs), len(hist_days)), dtype=np.int32)
        np.add.at(counts, (s_idx, d_idx[ok]), 1)
        seg_cum[h] = np.hstack([np.zeros((len(segs), 1), dtype=np.int32), np.cumsum(counts, axis=1)])
        cell_counts = np.zeros((len(cells), len(hist_days)), dtype=np.int32)
        np.add.at(cell_counts, (seg_cell[s_idx], d_idx[ok]), 1)
        cell_cum[h] = np.hstack([np.zeros((len(cells), 1), dtype=np.int32), np.cumsum(cell_counts, axis=1)])
    return Context(segs, days, cells, segs.cell_id.map(cell_pos).to_numpy(), weather, seg_cum, cell_cum)


def _window(cum: np.ndarray, rows: np.ndarray, t_hist: np.ndarray, back: int) -> np.ndarray:
    """Events in the `back` days up to and including day t."""
    return cum[rows, t_hist + 1] - cum[rows, np.maximum(t_hist + 1 - back, 0)]


def labels(ctx: Context, hazard: str, seg_rows: np.ndarray, t: np.ndarray, horizon: int) -> np.ndarray:
    """1 if an incident of this hazard is reported on the segment within (t, t + horizon]."""
    th = t + ctx.hist_offset
    cum = ctx.seg_cum[hazard]
    return (cum[seg_rows, np.minimum(th + 1 + horizon, cum.shape[1] - 1)] - cum[seg_rows, th + 1]) > 0


def build(ctx: Context, seg_rows: np.ndarray, t: np.ndarray) -> pd.DataFrame:
    """Feature frame for (segment row, day index) pairs."""
    s = ctx.segs.iloc[seg_rows]
    c = ctx.cell_idx[seg_rows]
    th = t + ctx.hist_offset
    month = ctx.days[t].month.to_numpy()
    out = {k: v[t, c] for k, v in ctx.weather.items()}
    out["dry_wet_swing"] = np.clip(out["rain_30d"] / (out.pop("rain_prev30") + 20), 0, 6)
    out["potholes_per_km_365d"] = _window(ctx.seg_cum["POTHOLE"], seg_rows, th, 365) / np.maximum(
        s.length_km.to_numpy(), 0.05
    )
    out.update(
        {
            "adt_k": s.adt.to_numpy() / 1000,
            "heavy_pct": s.heavy_pct.to_numpy(),
            "lanes": s.lanes.to_numpy(),
            "paved": (~s.surface.isin(["unpaved", "gravel", "dirt", "ground"])).to_numpy().astype(float),
            "karst": s.karst.to_numpy().astype(float),
            "ex_mining": s.ex_mining.to_numpy().astype(float),
            "tree_cover": s.tree_cover.to_numpy(),
            "potholes_30d": _window(ctx.seg_cum["POTHOLE"], seg_rows, th, 30),
            "potholes_90d": _window(ctx.seg_cum["POTHOLE"], seg_rows, th, 90),
            "potholes_365d": _window(ctx.seg_cum["POTHOLE"], seg_rows, th, 365),
            "length_km": s.length_km.to_numpy(),
            "sinkholes_cell_365d": _window(ctx.cell_cum["SINKHOLE"], c, th, 365),
            "trees_cell_365d": _window(ctx.cell_cum["FALLEN_TREE"], c, th, 365),
            "monsoon_flag": (np.isin(month, [11, 12, 1, 2, 3]) & s.state_code.isin(EAST_COAST).to_numpy()).astype(
                float
            ),
            "intermonsoon_flag": np.isin(month, [4, 5, 10, 11]).astype(float),
        }
    )
    for cls in ("federal", "state", "municipal", "expressway"):
        out[f"class_{cls}"] = (s.road_class.to_numpy() == cls.upper()).astype(float)
    return pd.DataFrame(out)
