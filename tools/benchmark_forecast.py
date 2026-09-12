"""Deterministic synthetic holdout; never a claim about live accuracy."""
import random
import statistics as st
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.forecast import _Evaluation, _smape


def series(kind, seed):
    rnd = random.Random(seed)
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(150)]
    counts, revenue = [], []
    for i, day in enumerate(days):
        level = {"stable": 10, "sparse": 1, "growth": 2+i*.15,
                 "decline": max(1, 30-i*.15), "step": 25 if i<85 else 5,
                 "price": 10, "spikes": 10, "closed": 10 if day.weekday()<3 else 0}[kind]
        c = max(0, round(level*rnd.uniform(.85, 1.15)))
        if kind == "sparse":
            c = rnd.randint(1, 3) if rnd.random()<.22 else 0
        if kind == "spikes" and rnd.random()<.05:
            c *= 8
        counts.append(c)
        revenue.append(c*100000*(2 if kind=="price" and i>=85 else 1))
    return revenue, counts, days


def main():
    print("| Scenario | Days | Adaptive sMAPE | Previous sMAPE | Linear sMAPE | Error reduction vs previous |")
    print("|---|---:|---:|---:|---:|---:|")
    for kind in ("stable", "sparse", "growth", "decline", "step", "price", "spikes", "closed"):
        for horizon in (7, 30):
            scores = {key: [] for key in ("predicted", "baseline", "linear")}
            for seed in range(100, 110):
                rows = _Evaluation(*series(kind, seed), horizon, skip_days=1).records()
                for key in scores:
                    scores[key].extend(_smape(r["actual"], r[key]) for r in rows)
            new, old, line = (st.mean(scores[k]) for k in scores)
            print(f"| {kind} | {horizon} | {new:.2f} | {old:.2f} | {line:.2f} | {(old-new)/old*100 if old else 0:.1f}% |")


if __name__ == "__main__":
    main()
