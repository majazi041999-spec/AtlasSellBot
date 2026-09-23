"""Local revenue forecasts selected by causal, rolling-origin validation.

Revenue here moves on WEEKLY and MONTHLY rhythms, not daily ones. Measured on
the live data after launch: a single day swings ±46% around its level, a week
±21%, and a 30-day block barely moves. So the "weekly" model sets the level
from whole weeks — the median of the last four weekly means, with extreme days
capped first, so one bulk-reseller week cannot move it — after taking out the
Persian-calendar pay cycle, and then puts that cycle back onto each forecast
day. On the live data the last ten days of a Jalali month sold ~20% below the
month's average and mid-month ~20% above. Weekday shape only redistributes a
week: it can never move a 7-day total.

The default is a "blend" of that weekly model and the mean-orders × trimmed
basket model, which fail in different ways. The older daily-level models still
compete as challengers, but a challenger may overrule the default only on
enough independent evidence (see MIN_INDEPENDENT_WINDOWS). Selection uses only
outcomes available at the forecast origin, and accuracy evaluates that whole
selection process on later folds, not the winning model's fit score.

Measured on the live data (rolling origin, 40 folds, whole policy): 30-day
accuracy 82.2% -> 93.0%, 7-day 79.7% -> 85.3% (accuracy = 100 − WAPE). The
known cost, from tools/benchmark_forecast.py: the 30-day forecast does not chase
sustained trends or step changes (see docs/forecast-validation.md) — every
trend-following variant lost on this business's own history.
"""
from __future__ import annotations

import statistics as st
import math
from datetime import date, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Sequence

from core.jalali import gregorian_to_jalali

# Default lookback; shorter windows compete through historical validation.
WINDOW = 28
# Trim this share off EACH end of the basket distribution before averaging, so an
# unusual day's mix cannot set the price of every future day.
BASKET_TRIM = 0.2
# Below this much history there is nothing to model; say so instead of guessing.
MIN_HISTORY = 14
# Folds used to measure this model's own accuracy on the caller's real data.
ACCURACY_FOLDS = 40
# Whole weeks whose median sets the weekly model's level.
LEVEL_WEEKS = 4
# The Jalali pay cycle is learned from this much history and shrunk toward "no
# effect" by this many pseudo-days, so a thin month cannot invent a pattern.
MONTH_LOOKBACK = 90
MONTH_SHRINK = 15
# Nominal coverage of the "typical range" band.
BAND_COVERAGE = 0.8
# Before a level or a month factor is taken, any day above this multiple of the
# window's median day is capped to it. A reseller's bulk order is real money,
# but it is not the business's typical week — and under an absolute-error
# target the typical week is exactly what should be forecast. 0 disables.
WINSOR = 3.0


def _winsorize(values: Sequence[float]) -> List[float]:
    positive = [v for v in values if v > 0]
    if not positive or not WINSOR:
        return list(values)
    cap = st.median(positive) * WINSOR
    return [min(v, cap) for v in values]


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


@lru_cache(maxsize=8192)
def _month_third(d: date) -> int:
    """Which third of the Jalali month a day is in: 0 = days 1-10, 1 = 11-20,
    2 = 21 to the month's end."""
    return min(2, (gregorian_to_jalali(d.year, d.month, d.day)[2] - 1) // 10)


def _month_factors(revenue: Sequence[float], days: Sequence[date]) -> Dict[int, float]:
    """Multiplicative factor per third of the Jalali month, averaging 1.0.

    Learned only from the history handed in — callers pass a strictly past
    slice, which keeps every backtest fold causal — over the last
    MONTH_LOOKBACK days, and shrunk toward 1.0 by MONTH_SHRINK pseudo-days.
    With under four weeks of history there is no month to learn from, so every
    factor is exactly 1.0 rather than a guess.
    """
    rw, dw = _winsorize(revenue[-MONTH_LOOKBACK:]), list(days[-MONTH_LOOKBACK:])
    flat = {0: 1.0, 1: 1.0, 2: 1.0}
    if len(rw) < 28:
        return flat
    mu = st.mean(rw)
    if mu <= 0:
        return flat
    raw = {}
    for t in (0, 1, 2):
        xs = [v for v, d in zip(rw, dw) if _month_third(d) == t]
        ratio = st.mean(xs) / mu if xs else 1.0
        raw[t] = 1 + (ratio - 1) * len(xs) / (len(xs) + MONTH_SHRINK)
    m = st.mean(raw.values())
    return {t: v / m for t, v in raw.items()} if m > 0 else flat


def _weekly_level(revenue: Sequence[float], days: Sequence[date],
                  factors: Optional[Dict[int, float]] = None) -> Optional[float]:
    """Revenue per day: the median over the last LEVEL_WEEKS weekly means.

    Whole weeks, so every sample holds the same weekday mix; a median, so a
    single bulk-reseller week cannot set the level; and, when `factors` are
    given, deseasonalised first — otherwise a normal month-end dip inside the
    window drags the level down and the next forecast runs low.
    """
    k = min(LEVEL_WEEKS, len(revenue) // 7)
    if k < 1:
        return None
    rw, dw = _winsorize(revenue[-7 * k:]), list(days[-7 * k:])
    if factors:
        rw = [v / max(factors[_month_third(d)], .2) for v, d in zip(rw, dw)]
    return st.median([sum(rw[j * 7:(j + 1) * 7]) / 7 for j in range(k)])


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


MODELS = ("weekly", "weekly_raw", "blend", "robust28", "robust14", "mean28", "mean7", "damped", "seasonal")
# What selection falls back to, and what a challenger must clearly beat. The
# blend, not "weekly" alone: on the live data the two score the same, but on a
# series of rare, huge bulk orders the weekly level alone lost ~3 points to the
# count × basket model while the blend held level with it.
DEFAULT_MODEL = "blend"
MODEL_LABELS = {
    "weekly": "سطح هفتگی با چرخهٔ ماه شمسی",
    "weekly_raw": "سطح هفتگی خام با چرخهٔ ماه شمسی",
    "blend": "ترکیب سطح هفتگی و میانگین سفارش‌ها",
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
# A challenger may only overrule the default when its validation spans at least
# this many NON-overlapping horizon windows. Consecutive folds share most of
# their target days: 28 origins of a 7-day forecast cover ~4 independent weeks,
# but 28 origins of a 30-day forecast are barely two months — too little to tell
# skill from luck. Measured on the live data, letting 30-day selection switch on
# that evidence picked a worse model and cost ~12 points of accuracy.
MIN_INDEPENDENT_WINDOWS = 3


def _smape(actual: float, predicted: float) -> float:
    den = (abs(actual) + abs(predicted)) / 2
    return abs(actual - predicted) / den * 100 if den else 0.0


def _candidate(revenue, counts, days, horizon, model):
    if model == "robust28":
        return _project(revenue, counts, days, horizon)
    last = days[-1]
    if model == "blend":
        # Two models that fail differently: the weekly level adapts to a new
        # regime within weeks, the count × trimmed-basket model shrugs off bulk
        # orders. The partner uses MEAN orders/day, not the median: on sparse
        # demand or a business closed some weekdays the median count is 0, and a
        # blend with a zero forecast halves every total (benchmark "closed",
        # 30 days: sMAPE 4 → 67 with the median partner, 6 with the mean).
        a = _candidate(revenue, counts, days, horizon, "weekly")
        b = _candidate(revenue, counts, days, horizon, "mean28")
        return [(x + y) / 2 for x, y in zip(a, b)]
    if model in ("weekly", "weekly_raw"):
        mf = _month_factors(revenue, days)
        level = _weekly_level(revenue, days, mf if model == "weekly" else None)
        if level is None:
            return _project(revenue, counts, days, horizon)
        # Mean-1 weekday factors: any 7 consecutive days sum to exactly 7, so the
        # shape moves money between days without changing a week's total.
        wf = _weekday_factors(counts[-WINDOW:], days[-WINDOW:])
        targets = [last + timedelta(days=k) for k in range(1, horizon + 1)]
        return [max(0.0, level * mf[_month_third(d)] * wf[d.weekday()]) for d in targets]
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
            return DEFAULT_MODEL, {"folds": len(origins), "reason": "insufficient_validation"}
        independent = (len(origins) - 1 + self.horizon) // self.horizon
        if independent < MIN_INDEPENDENT_WINDOWS:
            return DEFAULT_MODEL, {"folds": len(origins), "independent_windows": independent,
                                   "reason": "insufficient_independent_validation"}
        losses = {m: [] for m in MODELS}
        for t in origins:
            actual = sum(self.revenue[t + self.skip:t + self.span])
            for model in MODELS:
                losses[model].append(_smape(actual, sum(self.predict(t, model))))
        weights = [.97 ** (len(origins) - 1 - i) for i in range(len(origins))]
        scores = {m: sum(e * w for e, w in zip(errors, weights)) / sum(weights) for m, errors in losses.items()}
        best = min(MODELS, key=scores.get)
        wins = sum(a < b for a, b in zip(losses[best], losses[DEFAULT_MODEL])) / len(origins)
        if scores[best] >= scores[DEFAULT_MODEL] * (1 - MIN_GAIN) or wins < .55:
            best = DEFAULT_MODEL
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
        # Symmetric band from the BAND_COVERAGE quantile of past ABSOLUTE scaled
        # errors (split-conformal). The previous asymmetric 10/90 quantiles of
        # signed errors inherited whatever bias the older folds had: after the
        # launch spike every old fold over-forecast, so the band sat entirely
        # above the later actuals and its measured coverage was 0%.
        scale = max(total, st.mean(revenue[-WINDOW:]) * horizon, 1)
        half = _quantile(sorted(abs(r["error"]) for r in rows), BAND_COVERAGE)
        band = {"low": max(0, round(total - half * scale)), "high": round(total + half * scale),
                "target_coverage": round(BAND_COVERAGE * 100)}
        covered = tested = 0
        for row in rows:
            # Coverage is itself measured causally: each fold is judged against a
            # band built only from folds whose targets had ended before it.
            past = sorted(abs(r["error"]) for r in rows if r["cut"] + evaluation.span <= row["cut"])
            if len(past) < 8:
                continue
            tested += 1
            covered += abs(row["actual"] - row["predicted"]) <= _quantile(past, BAND_COVERAGE) * row["scale"]
        band.update(observed_coverage=round(100 * covered / tested, 1) if tested else None, coverage_folds=tested)
        absolute = [abs(r["actual"] - r["predicted"]) for r in rows]
        actual_sum = sum(r["actual"] for r in rows)
        wape = round(sum(absolute) / actual_sum * 100, 1) if actual_sum else None
        accuracy = {"smape": round(st.mean(_smape(r["actual"], r["predicted"]) for r in rows), 1),
                    "mae": round(st.mean(absolute)), "folds": len(rows),
                    "wape": wape,
                    # What an owner means by "accuracy": the share of the money
                    # forecast correctly, i.e. 100 − WAPE, on unseen later folds.
                    "accuracy_pct": round(max(0.0, 100 - wape), 1) if wape is not None else None,
                    "bias_pct": round(sum(r["predicted"] - r["actual"] for r in rows) / actual_sum * 100, 1) if actual_sum else None}
    window = 14 if model == "robust14" else 7 if model == "mean7" else WINDOW
    cw, rw = counts[-window:], revenue[-window:]
    mf = _month_factors(revenue, days)
    level = _weekly_level(revenue, days, mf)
    return {"ok": True, "history_days": n, "horizon": horizon,
            "points": [{"date": (last + timedelta(days=k + skip_days + 1)).isoformat(), "revenue": v} for k, v in enumerate(rounded)],
            "total": total, "band": band, "accuracy": accuracy,
            "method": model, "method_label": MODEL_LABELS[model], "selection": selection,
            "versus_baseline": _comparison(rows, "baseline", horizon),
            "versus_linear": _comparison(rows, "linear", horizon),
            "trained_through": last.isoformat(), "skip_days": skip_days,
            "drivers": {"orders_per_day": round(st.median(cw) if model.startswith("robust") else st.mean(cw), 2),
                        "avg_basket": round(_trimmed_basket(rw, cw)), "window_days": min(window, n),
                        "weekday_factors": {str(i): round(v, 2) for i, v in _weekday_factors(counts[-28:], days[-28:]).items()},
                        # Jalali pay cycle: days 1-10 / 11-20 / 21-end of the month.
                        "month_factors": {"early": round(mf[0], 2), "mid": round(mf[1], 2), "late": round(mf[2], 2)},
                        "daily_level": round(level) if level is not None else None},
            "backtest": [{"origin": days[r["cut"] - 1].isoformat(), "actual": round(r["actual"]),
                          "predicted": round(r["predicted"]), "method": r["model"]} for r in rows]}


def compare_to_line(revenue: Sequence[float], counts: Sequence[float], days: Sequence[date],
                    horizon: int = 7, *, skip_days: int = 0) -> Optional[Dict]:
    """Compatibility entry point; production callers can reuse forecast's comparison."""
    return forecast(revenue, counts, days, horizon, skip_days=skip_days).get("versus_linear")
