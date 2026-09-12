"""Local revenue forecasts selected by causal, rolling-origin validation.

The fixed 28-day count × basket model remains the fallback. Challengers may
adapt to recent levels, sparse demand, weekly recurrence or bounded count trend.
Selection uses only outcomes available at the forecast origin. Accuracy evaluates
that whole selection process on later folds, not the winning model's fit score.
"""
from __future__ import annotations

import statistics as st
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

# Default lookback; shorter windows compete through historical validation.
WINDOW = 28
# Trim this share off EACH end of the basket distribution before averaging, so an
# unusual day's mix cannot set the price of every future day.
BASKET_TRIM = 0.2
# Below this much history there is nothing to model; say so instead of guessing.
MIN_HISTORY = 14
# Folds used to measure this model's own accuracy on the caller's real data.
ACCURACY_FOLDS = 40


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def _weekday_factors(counts: Sequence[float], days: Sequence[date],
                     min_obs: int = 2) -> Dict[int, float]:
    """Multiplicative day-of-week factors, normalised to average 1.0.

    Built from medians of each weekday's ratio to the overall level, so one
    exceptional Saturday does not become "Saturdays are huge". A weekday with
    too few observations gets 1.0 rather than a number invented from one day.
    """
    positive = [c for c in counts if c > 0]
    base = st.median(positive) if positive else 1.0
    if base <= 0:
        return {i: 1.0 for i in range(7)}
    buckets: Dict[int, List[float]] = {i: [] for i in range(7)}
    for c, d in zip(counts, days):
        buckets[d.weekday()].append(c / base)
    observed = {i: st.median(v) for i, v in buckets.items()
                if len(v) >= min_obs and st.median(v) > 0}
    if not observed:
        return {i: 1.0 for i in range(7)}
    # Normalise across the weekdays we actually measured, so the factors only
    # RESHAPE the week and never move its overall level. Weekdays with too few
    # observations are then set to exactly 1.0 — normalising them alongside the
    # rest would have turned "we don't know" into a real adjustment.
    mean_f = sum(observed.values()) / len(observed)
    if mean_f <= 0:
        return {i: 1.0 for i in range(7)}
    return {i: (observed[i] / mean_f if i in observed else 1.0) for i in range(7)}


def _trimmed_basket(revenue: Sequence[float], counts: Sequence[float]) -> float:
    """Average money per order, with the extremes trimmed off both ends."""
    baskets = [r / c for r, c in zip(revenue, counts) if c > 0]
    if not baskets:
        return 0.0
    s = sorted(baskets)
    cut = int(len(s) * BASKET_TRIM)
    core = s[cut: len(s) - cut] or s
    return sum(core) / len(core)


def _project(revenue: Sequence[float], counts: Sequence[float],
             days: Sequence[date], horizon: int) -> List[float]:
    """Previous fixed model, retained as the fallback and comparison baseline."""
    rw = list(revenue[-WINDOW:]) or list(revenue)
    cw = list(counts[-WINDOW:]) or list(counts)
    dw = list(days[-len(cw):])
    if not cw:
        return [0.0] * horizon

    basket = _trimmed_basket(rw, cw)
    level = st.median(cw)
    factors = _weekday_factors(cw, dw)
    last = days[-1]
    return [max(0.0, level * factors[(last + timedelta(days=k)).weekday()] * basket)
            for k in range(1, horizon + 1)]


MODELS = ("robust28", "robust14", "mean28", "mean7", "damped", "seasonal")
MODEL_LABELS = {
    "robust28": "سطح پایدار سفارش‌ها",
    "robust14": "سطح اخیر سفارش‌ها",
    "mean28": "میانگین سفارش‌ها با روزهای بدون فروش",
    "mean7": "میانگین هفتهٔ اخیر",
    "damped": "روند محدودشدهٔ سفارش‌ها",
    "seasonal": "الگوی تکرار هفتگی درآمد",
}
SELECTION_FOLDS = 28
MIN_SELECTION_FOLDS = 14
MIN_GAIN = 0.08


def _smape(actual: float, predicted: float) -> float:
    den = (abs(actual) + abs(predicted)) / 2
    return abs(actual - predicted) / den * 100 if den else 0.0


def _candidate(revenue, counts, days, horizon, model):
    if model == "robust28":
        return _project(revenue, counts, days, horizon)
    last = days[-1]
    if model == "seasonal":
        recent = list(zip(days[-28:], revenue[-28:]))
        fallback = st.mean(revenue[-28:])
        return [st.median([v for d, v in recent if d.weekday() == (last + timedelta(days=k)).weekday()])
                if any(d.weekday() == (last + timedelta(days=k)).weekday() for d, _ in recent)
                else fallback for k in range(1, horizon + 1)]
    window = {"robust14": 14, "mean28": 28, "mean7": 7, "damped": 28}[model]
    cw, rw, dw = counts[-window:], revenue[-window:], days[-window:]
    basket = _trimmed_basket(rw, cw)
    factors = _weekday_factors(counts[-28:], days[-28:])
    level = st.median(cw) if model == "robust14" else st.mean(cw)
    slope = 0.0
    if model == "damped" and len(cw) >= 14:
        adjusted = [c / max(factors[d.weekday()], .1) for c, d in zip(cw, dw)]
        early, recent = st.median(adjusted[:7]), st.median(adjusted[-7:])
        slope = (recent - early) / (len(cw) - 7)
        # Cap daily slope and damp extrapolation; one launch spike cannot imply
        # unlimited growth (or a negative number of orders).
        slope = max(-recent * .1, min(recent * .1, slope))
        level = max(0.0, recent + slope * 3)
    return [max(0.0, level + slope * sum(.9 ** j for j in range(1, k + 1))) *
            factors[(last + timedelta(days=k)).weekday()] * basket
            for k in range(1, horizon + 1)]


def _line(revenue, horizon):
    vals = list(revenue[-30:])
    n = len(vals)
    if n < 2:
        return [max(0.0, vals[0] if vals else 0.0)] * horizon
    mx, my = (n - 1) / 2, st.mean(vals)
    slope = sum((i - mx) * (v - my) for i, v in enumerate(vals)) / sum((i - mx) ** 2 for i in range(n))
    return [max(0.0, .6 * (my + slope * (n - 1 + k - mx)) + .4 * st.mean(vals[-7:]))
            for k in range(1, horizon + 1)]


class _Evaluation:
    """Per-request cache. Every lookup is keyed by a strictly historical cut."""
    def __init__(self, revenue, counts, days, horizon, skip_days=0):
        self.revenue, self.counts, self.days = revenue, counts, days
        self.horizon, self.skip = horizon, skip_days
        self.span = horizon + skip_days
        self.cache = {}

    def predict(self, cut, model):
        key = (cut, model)
        if key not in self.cache:
            raw = (_line(self.revenue[:cut], self.span) if model == "linear" else
                   _candidate(self.revenue[:cut], self.counts[:cut], self.days[:cut], self.span, model))
            self.cache[key] = raw[self.skip:]
        return self.cache[key]

    def select(self, cut):
        # A fold may influence selection only once ALL its target days ended.
        last = cut - self.span
        origins = list(range(max(MIN_HISTORY, last - SELECTION_FOLDS + 1), last + 1))
        if len(origins) < MIN_SELECTION_FOLDS:
            return "robust28", {"folds": len(origins), "reason": "insufficient_validation"}
        losses = {m: [] for m in MODELS}
        for t in origins:
            actual = sum(self.revenue[t + self.skip:t + self.span])
            for model in MODELS:
                losses[model].append(_smape(actual, sum(self.predict(t, model))))
        weights = [.97 ** (len(origins) - 1 - i) for i in range(len(origins))]
        scores = {m: sum(e * w for e, w in zip(errors, weights)) / sum(weights) for m, errors in losses.items()}
        best = min(MODELS, key=scores.get)
        wins = sum(a < b for a, b in zip(losses[best], losses["robust28"])) / len(origins)
        if scores[best] >= scores["robust28"] * (1 - MIN_GAIN) or wins < .55:
            best = "robust28"
        return best, {"folds": len(origins), "reason": "historical_validation",
                      "scores": {m: round(v, 2) for m, v in scores.items()}}

    def records(self):
        n = len(self.revenue)
        first = max(MIN_HISTORY + WINDOW // 2, n - ACCURACY_FOLDS - self.span + 1)
        rows = []
        for cut in range(first, n - self.span + 1):
            model, _ = self.select(cut)
            actual = sum(self.revenue[cut + self.skip:cut + self.span])
            predicted = sum(self.predict(cut, model))
            scale = max(predicted, st.mean(self.revenue[max(0, cut - WINDOW):cut]) * self.horizon, 1)
            rows.append({"cut": cut, "actual": actual, "predicted": predicted,
                         "baseline": sum(self.predict(cut, "robust28")),
                         "linear": sum(self.predict(cut, "linear")),
                         "scale": scale, "error": (actual - predicted) / scale, "model": model})
        return rows


def _validate(revenue, counts, days, horizon, skip_days):
    if type(horizon) is not int or not 1 <= horizon <= 90:
        raise ValueError("horizon must be an integer between 1 and 90")
    if type(skip_days) is not int or not 0 <= skip_days <= 7:
        raise ValueError("skip_days must be an integer between 0 and 7")
    if not (len(revenue) == len(counts) == len(days)):
        raise ValueError("revenue, counts and dates must have equal lengths")
    if any(not math.isfinite(v) or v < 0 for v in revenue + counts):
        raise ValueError("observations must be finite and non-negative")
    if any(type(d) is not date for d in days):
        raise ValueError("dates must be calendar dates")
    if any(b - a != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise ValueError("dates must be sorted, unique and consecutive; fill genuine empty days with zeros")


def _comparison(rows, key, horizon):
    if len(rows) < 8:
        return None
    mine = st.mean(_smape(r["actual"], r["predicted"]) for r in rows)
    other = st.mean(_smape(r["actual"], r[key]) for r in rows)
    return {"this_model_smape": round(mine, 1), f"{key}_smape": round(other, 1),
            "error_reduction_pct": round((other - mine) / other * 100, 1) if other else 0,
            "folds": len(rows), "horizon": horizon}


def forecast(revenue: Sequence[float], counts: Sequence[float],
             days: Sequence[date], horizon: int = 7, *, skip_days: int = 0) -> Dict:
    """Forecast complete future days. The caller must exclude unfinished input days.

    skip_days=1 omits today when the last complete observation is yesterday.
    Validation uses the same lead time. All-zero forecasts are included in the
    error metric; no accuracy is inferred from the tuning score.
    """
    revenue, counts, days = list(map(float, revenue)), list(map(float, counts)), list(days)
    _validate(revenue, counts, days, horizon, skip_days)
    n = len(revenue)
    last = days[-1] if days else date.today() - timedelta(days=skip_days)
    if n < MIN_HISTORY:
        flat = st.mean(revenue) if revenue else 0.0
        points = [{"date": (last + timedelta(days=k + skip_days)).isoformat(), "revenue": int(round(flat))}
                  for k in range(1, horizon + 1)]
        return {"ok": False, "reason": "not_enough_history", "history_days": n, "needed_days": MIN_HISTORY,
                "horizon": horizon, "points": points, "total": sum(p["revenue"] for p in points),
                "band": None, "accuracy": None, "method": "mean of observed complete days"}
    evaluation = _Evaluation(revenue, counts, days, horizon, skip_days)
    model, selection = evaluation.select(n)
    raw = evaluation.predict(n, model)
    rounded = [int(round(v)) for v in raw]
    total = sum(rounded)
    rows = evaluation.records()
    band = accuracy = None
    if len(rows) >= 8:
        errors = sorted(r["error"] for r in rows)
        scale = max(total, st.mean(revenue[-WINDOW:]) * horizon, 1)
        low, high = _quantile(errors, .1), _quantile(errors, .9)
        # Include the point estimate for readability; do not promise nominal coverage.
        band = {"low": max(0, min(total, round(total + low * scale))),
                "high": max(total, round(total + high * scale)), "target_coverage": 80}
        covered = tested = 0
        for row in rows:
            past = sorted(r["error"] for r in rows if r["cut"] + evaluation.span <= row["cut"])
            if len(past) < 8:
                continue
            lo = max(0, min(row["predicted"], row["predicted"] + _quantile(past, .1) * row["scale"]))
            hi = max(row["predicted"], row["predicted"] + _quantile(past, .9) * row["scale"])
            tested += 1; covered += lo <= row["actual"] <= hi
        band.update(observed_coverage=round(100 * covered / tested, 1) if tested else None, coverage_folds=tested)
        absolute = [abs(r["actual"] - r["predicted"]) for r in rows]
        actual_sum = sum(r["actual"] for r in rows)
        accuracy = {"smape": round(st.mean(_smape(r["actual"], r["predicted"]) for r in rows), 1),
                    "mae": round(st.mean(absolute)), "folds": len(rows),
                    "wape": round(sum(absolute) / actual_sum * 100, 1) if actual_sum else None,
                    "bias_pct": round(sum(r["predicted"] - r["actual"] for r in rows) / actual_sum * 100, 1) if actual_sum else None}
    window = 14 if model == "robust14" else 7 if model == "mean7" else WINDOW
    cw, rw = counts[-window:], revenue[-window:]
    return {"ok": True, "history_days": n, "horizon": horizon,
            "points": [{"date": (last + timedelta(days=k + skip_days + 1)).isoformat(), "revenue": v} for k, v in enumerate(rounded)],
            "total": total, "band": band, "accuracy": accuracy,
            "method": model, "method_label": MODEL_LABELS[model], "selection": selection,
            "versus_baseline": _comparison(rows, "baseline", horizon),
            "versus_linear": _comparison(rows, "linear", horizon),
            "trained_through": last.isoformat(), "skip_days": skip_days,
            "drivers": {"orders_per_day": round(st.median(cw) if model.startswith("robust") else st.mean(cw), 2),
                        "avg_basket": round(_trimmed_basket(rw, cw)), "window_days": min(window, n),
                        "weekday_factors": {str(i): round(v, 2) for i, v in _weekday_factors(counts[-28:], days[-28:]).items()}},
            "backtest": [{"origin": days[r["cut"] - 1].isoformat(), "actual": round(r["actual"]),
                          "predicted": round(r["predicted"]), "method": r["model"]} for r in rows]}


def compare_to_line(revenue: Sequence[float], counts: Sequence[float], days: Sequence[date],
                    horizon: int = 7, *, skip_days: int = 0) -> Optional[Dict]:
    """Compatibility entry point; production callers can reuse forecast's comparison."""
    return forecast(revenue, counts, days, horizon, skip_days=skip_days).get("versus_linear")
