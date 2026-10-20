"""Prediction engine (T6.2–T6.4, architechture.md §10).

    .venv\\Scripts\\python -m app.ml.models          (from server/; GitHub Actions runs it nightly)

For each hazard: build features, score the rule-based baseline, train a calibrated
HistGradientBoostingClassifier with a time-based split, keep whichever has the better PR-AUC on
the held-out months, then predict every segment for 7 and 30 days with top-3 factors. The
model card (model_versions) records the metrics and how much of the data is synthetic.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss

from app.ml import features as F
from app.ml.common import connect, frame
from app.services.domain import risk_level

SEED = 7
HORIZONS = (7, 30)
NEG_KEEP = 0.10  # keep 10% of negatives, weighted ×10, so training stays a few hundred thousand rows
HISTORY_DAYS = 365
TEST_SHARE = 0.25


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- baseline (T6.2): hand-set daily rates; only the overall level is fitted ------------------


def _clip(x, hi):
    return np.clip(np.nan_to_num(x), 0, hi)


BASELINE_TERMS = {
    "POTHOLE": lambda X: {
        "rain_7d": 0.6 * _clip(X.rain_7d / 100, 3),
        "adt_k": 0.35 * np.log1p(X.adt_k),
        "heavy_pct": 1.2 * X.heavy_pct,
        "potholes_90d": 0.5 * np.log1p(X.potholes_90d),
        "potholes_365d": 0.2 * np.log1p(X.potholes_365d),
        "class_federal": 0.2 * X.class_federal,
        "class_municipal": -0.35 * X.class_municipal,
    },
    "SINKHOLE": lambda X: {
        "karst": 1.5 * X.karst,
        "ex_mining": 1.0 * X.ex_mining,
        "sinkholes_cell_365d": 0.6 * np.log1p(X.sinkholes_cell_365d),
        "dry_wet_swing": 0.3 * _clip(X.dry_wet_swing, 3),
        "rain_max_hr_3d": 0.3 * _clip(X.rain_max_hr_3d / 30, 2),
    },
    "FALLEN_TREE": lambda X: {
        "forecast_gust_7d": 0.04 * (np.nan_to_num(X.forecast_gust_7d, nan=30) - 30),
        "tree_cover": 2.0 * X.tree_cover,
        "trees_cell_365d": 0.3 * np.log1p(X.trees_cell_365d),
        "intermonsoon_flag": 0.5 * X.intermonsoon_flag,
        "rain_3d": 0.2 * _clip(X.rain_3d / 50, 2),
    },
}


@dataclass
class Baseline:
    hazard: str
    level: float = 1e-4

    def _terms(self, X):
        return pd.DataFrame(BASELINE_TERMS[self.hazard](X.reset_index(drop=True)))

    def fit(self, X, y, w, horizon):
        target = np.average(y, weights=w)
        p = self.predict(X, horizon)
        self.level *= target / max(np.average(p, weights=w), 1e-9)  # match the observed base rate
        return self

    def predict(self, X, horizon):
        rate = self.level * np.exp(self._terms(X).sum(axis=1).to_numpy())
        return 1 - np.exp(-rate * np.asarray(horizon))

    def factors(self, X):
        return self._terms(X)


# --- training data -------------------------------------------------------------------------------


def training_rows(ctx: F.Context, hazard: str, rng: np.random.Generator):
    """Weekly snapshots × pilot segments, both horizons stacked, negatives downsampled."""
    t_grid = np.arange(30, len(ctx.days) - max(HORIZONS) - 1, 7)
    n = len(ctx.segs)
    seg_rows = np.repeat(np.arange(n), len(t_grid))
    t = np.tile(t_grid, n)
    parts = []
    for h in HORIZONS:
        y = F.labels(ctx, hazard, seg_rows, t, h)
        keep = y | (rng.random(len(y)) < NEG_KEEP)
        parts.append(
            pd.DataFrame(
                {
                    "seg": seg_rows[keep],
                    "t": t[keep],
                    "horizon": h,
                    "y": y[keep].astype(int),
                    "w": np.where(y[keep], 1.0, 1 / NEG_KEEP),
                }
            )
        )
    rows = pd.concat(parts, ignore_index=True)
    X = F.build(ctx, rows.seg.to_numpy(), rows.t.to_numpy())[F.FEATURES[hazard]]
    X["horizon"] = rows.horizon.to_numpy()
    return X, rows


class Calibrated:
    """Gradient boosting fitted on earlier months, then an isotonic map fitted on later months
    with the downsampling weights, so its probabilities match the true base rate directly."""

    def __init__(self, model, isotonic):
        self.model, self.isotonic = model, isotonic

    def predict_proba(self, X):
        p = self.isotonic.predict(self.model.predict_proba(X)[:, 1])
        return np.column_stack([1 - p, p])

    @property
    def estimator(self):
        return self.model


def evaluate(y, p, w) -> dict:
    return {
        "pr_auc": round(float(average_precision_score(y, p, sample_weight=w)), 4),
        "brier": round(float(brier_score_loss(y, p, sample_weight=w)), 5),
    }


def train_hazard(ctx: F.Context, hazard: str, rng: np.random.Generator, synthetic_share: float) -> dict:
    X, rows = training_rows(ctx, hazard, rng)
    split_t = ctx.days[int(len(ctx.days) * (1 - TEST_SHARE))]
    is_test = ctx.days[rows.t.to_numpy()] >= split_t
    tr, te = ~is_test, is_test
    y, w = rows.y.to_numpy(), rows.w.to_numpy()
    positives = int(y[tr].sum())
    log(f"{hazard}: {len(X):,} rows, {positives} positive train rows, {int(y[te].sum())} positive test rows")

    base = Baseline(hazard).fit(X[tr], y[tr], w[tr], X.horizon[tr])
    base_metrics = evaluate(y[te], base.predict(X[te], X.horizon[te]), w[te])

    model, model_metrics = None, None
    if positives >= 20 and y[te].sum() >= 5:
        cols = list(X.columns)
        hgb = HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.06,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=SEED,
            monotonic_cst=[1 if c == "horizon" else 0 for c in cols],
        )
        # Fit on the earlier training months, calibrate on the last two (time order kept throughout).
        calib_from = ctx.days[int(len(ctx.days) * (1 - TEST_SHARE)) - 60]
        is_calib = tr & (ctx.days[rows.t.to_numpy()] >= calib_from)
        fit = tr & ~is_calib
        hgb.fit(X[fit], y[fit])
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
        iso.fit(hgb.predict_proba(X[is_calib])[:, 1], y[is_calib], sample_weight=w[is_calib])
        model = Calibrated(hgb, iso)
        model_metrics = evaluate(y[te], model.predict_proba(X[te])[:, 1], w[te])
    # The model must rank better (PR-AUC) without being clearly worse calibrated (Brier).
    use_model = (
        model is not None
        and model_metrics["pr_auc"] > base_metrics["pr_auc"]
        and model_metrics["brier"] <= base_metrics["brier"] * 1.05
    )
    log(f"{hazard}: baseline {base_metrics}, model {model_metrics} -> using {'model' if use_model else 'baseline'}")
    stamp = date.today().strftime("%Y.%m.%d")
    return {
        "hazard": hazard,
        "use_model": use_model,
        "model": model,
        "baseline": base,
        "version": f"{hazard.lower()}-{'hgb' if use_model else 'baseline'}-{stamp}",
        "algorithm": (
            "HistGradientBoostingClassifier + isotonic calibration on held-out months"
            if use_model
            else "Rule-based baseline (hand-set weights, fitted level)"
        ),
        "training_rows": int(tr.sum()),
        "synthetic_share": synthetic_share,
        "metrics": {
            **(model_metrics or {}),
            "baseline_pr_auc": base_metrics["pr_auc"],
            "baseline_brier": base_metrics["brier"],
            "test_rows": int(te.sum()),
            "test_from": split_t.date().isoformat(),
            "chosen": "model" if use_model else "baseline",
        },
        "features": F.FEATURES[hazard],
    }


# --- prediction (T6.4) ---------------------------------------------------------------------------


def top_factors(contrib: pd.DataFrame, X: pd.DataFrame, k: int = 3) -> list[list[list]]:
    """The k features pushing risk up the most, with their raw values (labels come from i18n).
    Stored compact as [feature, value, direction] (migration 0006); the API expands them.
    Vectorised: one argsort and two gathers, no per-row pandas access."""
    names = list(contrib.columns)
    vals = contrib.to_numpy()
    raw = np.nan_to_num(X[names].to_numpy(dtype=float))
    order = np.argsort(-vals, axis=1)[:, :k]
    rows = np.arange(len(vals))[:, None]
    picked_vals, picked_raw = vals[rows, order], raw[rows, order]
    picked_raw = np.where(np.abs(picked_raw) < 10, np.round(picked_raw, 2), np.round(picked_raw))
    return [
        [[names[j], float(v), 1 if c >= 0 else -1] for j, v, c in zip(o, r, cv, strict=True)]
        for o, r, cv in zip(order, picked_raw, picked_vals, strict=True)
    ]


def explain(trained: dict, X: pd.DataFrame) -> pd.DataFrame:
    if not trained["use_model"]:
        return trained["baseline"].factors(X)
    import shap  # heavy import, only needed when a trained model is active

    est = trained["model"].estimator
    values = shap.TreeExplainer(est).shap_values(X)
    values = values[1] if isinstance(values, list) else values
    return pd.DataFrame(values, columns=X.columns).drop(columns=["horizon"])


def predict_all(conn, trained: dict[str, dict]) -> pd.DataFrame:
    segs = F.segments(conn, pilots_only=False)
    today = date.today()
    ctx = F.load(conn, segs, today, today)
    rows = np.arange(len(segs))
    base = F.build(ctx, rows, np.zeros(len(segs), dtype=int))
    out = []
    for hazard, tr in trained.items():
        for h in HORIZONS:
            X = base[F.FEATURES[hazard]].copy()
            X["horizon"] = h
            p = tr["model"].predict_proba(X)[:, 1] if tr["use_model"] else tr["baseline"].predict(X, h)
            factors = top_factors(explain(tr, X), X.drop(columns=["horizon"]))
            out.append(
                pd.DataFrame(
                    {
                        "segment_id": segs.id.to_numpy(),
                        "hazard_type": hazard,
                        "horizon_days": h,
                        "probability": np.round(p, 4),
                        "top_factors": factors,
                        "model_version": tr["version"],
                    }
                )
            )
        log(f"predicted {hazard}")
    preds = pd.concat(out, ignore_index=True)
    preds["risk_level"] = preds.probability.map(risk_level)
    return preds


def write(conn, preds: pd.DataFrame, trained: dict[str, dict]) -> None:
    now = datetime.now(UTC)
    cols = "segment_id, hazard_type, horizon_days, probability, risk_level, top_factors, model_version, generated_at"
    with conn.cursor() as cur:
        # Stage, then truncate and insert: truncate frees the old rows' space at once, which a delete
        # doesn't (500 MB cap), and the table is only locked for the final insert, not the upload.
        cur.execute("create temp table predictions_stage (like predictions) on commit drop")
        with cur.copy(f"copy predictions_stage ({cols}) from stdin") as cp:
            for r in preds.itertuples():
                cp.write_row(
                    (
                        r.segment_id,
                        r.hazard_type,
                        r.horizon_days,
                        float(r.probability),
                        r.risk_level,
                        json.dumps(r.top_factors),
                        r.model_version,
                        now,
                    )
                )
        cur.execute("truncate predictions")
        cur.execute(f"insert into predictions ({cols}) select {cols} from predictions_stage")
        for tr in trained.values():
            cur.execute("update model_versions set is_active = false where hazard_type = %s", (tr["hazard"],))
            cur.execute(
                """
                insert into model_versions (version, hazard_type, algorithm, trained_at, training_rows,
                                            synthetic_share, metrics, features, limitations, is_active)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                on conflict (version) do update set algorithm = excluded.algorithm, trained_at = excluded.trained_at,
                    training_rows = excluded.training_rows, synthetic_share = excluded.synthetic_share,
                    metrics = excluded.metrics, features = excluded.features, limitations = excluded.limitations,
                    is_active = true""",
                (
                    tr["version"],
                    tr["hazard"],
                    tr["algorithm"],
                    now,
                    tr["training_rows"],
                    tr["synthetic_share"],
                    json.dumps(tr["metrics"]),
                    tr["features"],
                    limitations(tr),
                ),
            )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("refresh materialized view segment_components")
    conn.commit()


def limitations(tr: dict) -> str:
    parts = []
    if tr["synthetic_share"] >= 0.5:
        parts.append(f"Trained on {tr['synthetic_share']:.0%} demo data; accuracy will change with real reports.")
    parts.append(
        "Trained on the Kinta and Kuala Lumpur pilots, then applied to every road; elsewhere it has "
        "little incident history and only recent weather."
    )
    if tr["hazard"] == "SINKHOLE":
        parts.append("Karst and ex-mining areas are approximate hand-drawn polygons, not JMG survey data.")
    if not tr["use_model"]:
        parts.append("The trained model did not beat this baseline on the held-out months, so the baseline is used.")
    return " ".join(parts)


def main() -> None:
    rng = np.random.default_rng(SEED)
    with connect() as conn:
        share = frame(
            conn,
            """
            select coalesce(avg(case when is_synthetic then 1.0 else 0.0 end), 1) as s from incidents
            where status not in ('REJECTED', 'DUPLICATE')""",
        ).s.iloc[0]
        segs = F.segments(conn, pilots_only=True)
        end = date.today() - timedelta(days=1)
        ctx = F.load(conn, segs, end - timedelta(days=HISTORY_DAYS - 1), end)
        log(f"{len(segs):,} pilot segments, {len(ctx.days)} days; synthetic share {float(share):.0%}")
        trained = {h: train_hazard(ctx, h, rng, float(share)) for h in F.HAZARDS}
        preds = predict_all(conn, trained)
        write(conn, preds, trained)
        log(f"wrote {len(preds):,} predictions; risk levels: {preds.risk_level.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
