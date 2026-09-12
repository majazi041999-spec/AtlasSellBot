"""Causality, sparse demand and input integrity of adaptive forecasts."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.forecast import forecast, _Evaluation, _smape


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.days = [date(2026, 1, 1) + timedelta(days=i) for i in range(150)]
        self.counts = [2 + i * .15 for i in range(150)]
        self.revenue = [c * 100000 for c in self.counts]

    def test_future_cannot_change_selection_or_prediction(self):
        original = _Evaluation(self.revenue, self.counts, self.days, 7, 1)
        changed = _Evaluation(self.revenue[:100] + [1e12] * 50,
                              self.counts[:100] + [1e6] * 50, self.days, 7, 1)
        self.assertEqual(original.select(100), changed.select(100))
        model, _ = original.select(100)
        self.assertEqual(original.predict(100, model), changed.predict(100, model))

    def test_accuracy_evaluates_entire_policy(self):
        result = forecast(self.revenue, self.counts, self.days, 7, skip_days=1)
        rows = _Evaluation(self.revenue, self.counts, self.days, 7, 1).records()
        expected = round(sum(_smape(r['actual'], r['predicted']) for r in rows) / len(rows), 1)
        self.assertEqual(result['accuracy']['smape'], expected)
        self.assertEqual(result['accuracy']['folds'], len(rows))
        self.assertEqual(result['points'][0]['date'], (self.days[-1] + timedelta(days=2)).isoformat())
        self.assertEqual(result['total'], sum(p['revenue'] for p in result['points']))
        self.assertLessEqual(result['band']['low'], result['total'])
        self.assertGreaterEqual(result['band']['high'], result['total'])

    def test_zero_forecasts_remain_in_validation(self):
        counts = [1 if i % 7 == 0 else 0 for i in range(150)]
        revenue = [c * 100 for c in counts]
        rows = _Evaluation(revenue, counts, self.days, 7).records()
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(r['baseline'] == 0 and r['actual'] > 0 for r in rows))
        result = forecast(revenue, counts, self.days)
        self.assertGreater(result['total'], 0)
        self.assertGreater(result['versus_baseline']['error_reduction_pct'], 50)

    def test_invalid_inputs_and_short_history(self):
        for values in ([float('nan')], [-1], [float('inf')]):
            with self.assertRaises(ValueError):
                forecast(values, [1], self.days[:1])
        with self.assertRaises(ValueError):
            forecast([1, 2], [1, 1], [self.days[0], self.days[2]])
        with self.assertRaises(ValueError):
            forecast([], [], [], True)
        short = forecast([1.5], [1], self.days[:1])
        self.assertFalse(short['ok'])
        self.assertIsNone(short['accuracy'])
        self.assertEqual(short['total'], sum(p['revenue'] for p in short['points']))


if __name__ == '__main__':
    unittest.main()
