# Adaptive revenue forecast

The default model is `blend`: the mean of `weekly` and `mean28`.
- **`weekly`** takes the median of the last four weekly means (days above 3× the median day are capped first), deseasonalised by a Jalali month-third factor, then re-seasonalised per target day.
- **`mean28`** is mean orders/day × 20%-trimmed basket × weekday factors.

The two fail in different ways. `weekly` adapts within weeks and knows the pay cycle. `mean28` shrugs off big-ticket bulk orders and never collapses to zero on sparse or closed-weekday demand, which a median-count partner does.

Eight challengers (`weekly`, `weekly_raw`, `robust28`, `robust14`, `mean28`, `mean7`, `damped`, `seasonal`) compete per horizon, using only fully matured historical outcomes. To overrule the default, a challenger needs all of:
- at least 14 validation folds;
- 8% lower weighted sMAPE;
- wins on 55% of folds;
- validation spanning at least **3 non-overlapping horizon windows** (`MIN_INDEPENDENT_WINDOWS`).

In practice 7-day selection runs, and 30-day always keeps the default. The reported accuracy evaluates the entire selector at historical origins, not its tuning score.

The Jalali factors (days 1-10 / 11-20 / 21-end) are learned per call from the history handed in: a 90-day lookback, shrunk by 15 pseudo-days, averaging exactly 1.0. They are exactly neutral under 28 days of history.

## Inputs

Inputs exclude today's unfinished receipts and padding before the first approved sale. Genuine zero-sale days remain. Revenue uses historical snapshots or net purchase wallet debits rather than today's package price.

When historical amounts are missing, training uses only the contiguous complete suffix after the last unknown day. The excluded days and unknown order count are disclosed; fewer than 14 remaining days suppress forecasts. Never remove isolated days or substitute current package prices.

Charts retain today's receipts. Forecasts start tomorrow; validation uses the same one-day skip.

## Range and accuracy reporting

The range is symmetric split-conformal: ± the 80th percentile of past absolute scaled errors. Measured coverage uses only errors whose target windows had ended at each origin. The previous signed 10/90-quantile range inherited the post-launch over-forecast bias and covered 0% of later 30-day actuals.

`accuracy_pct` = 100 − WAPE is what the panel headlines. The panel warns when coverage rests on fewer than 8 folds. Overlapping folds are not independent; neither ranges nor improvements guarantee future outcomes.

## Live results (Sep 2026)

116 complete days, whole policy, 40 rolling folds, accuracy = 100 − WAPE:

| Horizon | Previous policy | Current | Last 15 folds | Range coverage (target 80%) |
|---|---:|---:|---:|---|
| 30 days | 82.2% | **93.0%** | 95.1% | 100% over only 2 folds — not yet meaningful |
| 7 days | 79.7% | **85.3%** | 87.1% | 80.0% over 25 folds |

About 85% is the 7-day ceiling with the signals available. Weekly revenue swings ±21%, and resellers (59% of revenue) buy in lumps. None of these explained next week's surprise: a 30-day sales echo, reseller top-ups (corr −0.30), or reseller wallet balances (corr −0.04). See PROJECT_MAP §11b.

## Reproduction and holdout results

Run `python tools/benchmark_forecast.py`. These are **synthetic**, 150-day series, 10 held-out seeds (100–109), 40 outer origins each, one-day skip. Lower sMAPE is better.
- **"Previous policy"** is the selector before Sep 2026: robust28 default, no independence rule.
- **"Fixed model"** is the original robust28 alone.

| Scenario | Days | Current sMAPE | Previous policy | Fixed model | Linear |
|---|---:|---:|---:|---:|---:|
| stable | 7 | 2.70 | 2.99 | 2.87 | 3.75 |
| stable | 30 | 1.91 | 2.58 | 2.69 | 4.28 |
| sparse | 7 | 75.16 | 80.95 | 178.00 | 84.02 |
| sparse | 30 | 45.91 | 52.46 | 200.00 | 91.50 |
| growth | 7 | 6.49 | 6.49 | 15.21 | 4.49 |
| growth | 30 | **26.98** | 11.39 | 27.68 | 7.61 |
| decline | 7 | 7.28 | 7.28 | 21.61 | 5.57 |
| decline | 30 | **30.69** | 12.10 | 30.18 | 8.87 |
| step | 7 | 4.84 | 4.17 | 3.58 | 48.55 |
| step | 30 | **76.35** | 59.58 | 65.80 | 128.36 |
| price | 7 | 3.88 | 3.98 | 3.68 | 5.89 |
| price | 30 | 31.13 | 29.96 | 30.76 | 24.67 |
| spikes | 7 | 33.11 | 31.41 | 27.47 | 44.61 |
| spikes | 30 | 20.21 | 20.10 | 32.48 | 42.79 |
| closed | 7 | 5.09 | 4.85 | 200.00 | 11.49 |
| closed | 30 | 6.42 | 4.07 | 200.00 | 21.27 |

**The deliberate trade-off (bold rows):** at 30 days the current policy never leaves the level-based default, so it does not chase sustained trends or step changes. The previous policy could switch to `damped` there, and wins those three cells.

That was measured, not assumed. On the live history, every variant that let 30-day selection switch, and a blend that included `damped`, fell to 81–84% accuracy. The one decline this business has had was a post-launch decay, not a trend, and switching on it failed in the following period.

If the business ever enters a sustained trend, the 30-day figure will lag, and the panel's daily re-measured accuracy will show it. Revisit then, with a fold-for-fold measurement on the live history.

A first version of the blend used the median-count `robust28` as its partner. It forecast 0 on closed weekdays and halved every total: `closed`/30 went 4 → 67, and `sparse`/30 went 52 → 84. `tests/test_forecast_calendar.py` §8 pins the fix.

Keep all eight scenarios when evaluating future changes. Do not tune against these seeds and continue calling them held out.

## Verification

- `python tests/test_forecast.py`
- `python tests/test_forecast_calendar.py`
- `python -m unittest discover -s tests -p test_forecast_adaptive.py`
- `python -m unittest discover -s tests -p test_analytics_forecast.py`
- `python tests/test_ai_analyst.py`
- `python tests/test_rep_accounting.py`
- `python tools/benchmark_forecast.py` (compare against the table above)
- `npm run build` in `web/admin`
