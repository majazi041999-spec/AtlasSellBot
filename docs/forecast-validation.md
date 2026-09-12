# Adaptive revenue forecast

The fixed 28-day count × trimmed basket forecast remains the fallback. Six candidates cover stable demand, recent levels, sparse demand, damped count trends and weekly revenue recurrence. Each horizon selects independently using only fully matured historical outcomes. A challenger needs at least 14 validation folds, 8% lower weighted sMAPE and wins on 55% of folds. The reported accuracy evaluates the entire selector at historical origins, not its tuning score.

Inputs exclude today's unfinished receipts and padding before the first approved sale. Genuine zero-sale days remain. Revenue uses historical snapshots or net purchase wallet debits rather than today's package price. Missing historical amounts suppress forecasts. Charts retain today's receipts. Forecasts start tomorrow; validation uses the same one-day skip.

The empirical range uses historical signed errors. Measured coverage uses only errors whose target windows had ended at each origin. Overlapping folds are not independent; neither ranges nor improvements guarantee future outcomes. With fewer than 14 complete days, no production forecast is displayed.

## Reproduction and holdout results

Run `python tools/benchmark_forecast.py`. These are **synthetic**, 150-day series, 10 held-out seeds (100–109), 40 outer origins each, one-day skip. Seeds 0–4 were exploratory. Candidate settings were frozen before the held-out run. Lower sMAPE is better; reductions are against the previous fixed model, not the linear comparator. No live database was available in this workspace.

| Scenario | Days | Adaptive sMAPE | Previous sMAPE | Linear sMAPE | Error reduction vs previous |
|---|---:|---:|---:|---:|---:|
| stable | 7 | 2.99 | 2.87 | 3.75 | -4.1% |
| stable | 30 | 2.58 | 2.69 | 4.28 | 4.1% |
| sparse | 7 | 80.95 | 178.00 | 84.02 | 54.5% |
| sparse | 30 | 52.46 | 200.00 | 91.50 | 73.8% |
| growth | 7 | 6.49 | 15.21 | 4.49 | 57.3% |
| growth | 30 | 11.39 | 27.68 | 7.61 | 58.8% |
| decline | 7 | 7.28 | 21.61 | 5.57 | 66.3% |
| decline | 30 | 12.10 | 30.18 | 8.87 | 59.9% |
| step | 7 | 4.17 | 3.58 | 48.55 | -16.8% |
| step | 30 | 59.58 | 65.80 | 128.36 | 9.5% |
| price | 7 | 3.98 | 3.68 | 5.89 | -8.1% |
| price | 30 | 29.96 | 30.76 | 24.67 | 2.6% |
| spikes | 7 | 31.41 | 27.47 | 44.61 | -14.3% |
| spikes | 30 | 20.10 | 32.48 | 42.79 | 38.1% |
| closed | 7 | 4.85 | 200.00 | 11.49 | 97.6% |
| closed | 30 | 4.07 | 200.00 | 21.27 | 98.0% |

The requested halving of error occurs in sparse demand, growth, decline and regularly closed weekdays in this suite. It does not occur universally: stable/step/price/spike seven-day cases regress. Straight-line extrapolation also beats this bounded policy on smooth synthetic trends. Retain these cases when evaluating future changes; do not tune against these seeds and continue calling them held out. The panel reports the owner's actual rolling errors and negative as well as positive comparisons.

## Verification

- `python tests/test_forecast.py`
- `python -m unittest discover -s tests -p test_forecast_adaptive.py`
- `python -m unittest discover -s tests -p test_analytics_forecast.py`
- `python tests/test_ai_analyst.py`
- `python tests/test_rep_accounting.py`
- `npm run build` in `web/admin`
- Edge browser smoke with mocked analytics: both horizons, positive/negative comparisons, historical table, missing-price suppression and responsive forecast cards.
