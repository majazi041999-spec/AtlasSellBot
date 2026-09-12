"""Forecast data boundaries and historical revenue, isolated from live storage."""
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import database as db


class AnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='atlas-forecast-')
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(db, 'DB_PATH', str(Path(self.tmp.name) / 'test.db'))
        p.start(); self.addCleanup(p.stop)
        await db.init_db()

    async def test_historical_cost_and_real_empty_days(self):
        user = await db.get_or_create_user(12345, 'test', 'Test')
        pkg = await db.add_package('Test', 30, 7, 100000)
        oid = await db.create_order(user['id'], pkg)
        start = (date.today() - timedelta(days=3)).isoformat()
        await db.update_order(oid, status='approved', approved_at=start)
        await db.update_package(pkg, price=900000)
        rows = await db.get_revenue_timeseries(7)
        self.assertFalse(rows[0]['is_observed'])
        self.assertEqual(rows[-4]['revenue'], 100000)
        self.assertTrue(rows[-3]['is_observed'])
        self.assertEqual(rows[-3]['revenue'], 0)
        self.assertFalse(rows[-1]['is_complete'])
        await db.add_user_balance(user['id'], -85000, kind='purchase', note=f'order:{oid}')
        self.assertEqual((await db.get_revenue_timeseries(7))[-4]['revenue'], 85000)
        unknown = await db.create_order(user['id'], pkg)
        await db.update_order(unknown, status='approved', approved_at=start, price_snapshot=None)
        rows = await db.get_revenue_timeseries(7)
        self.assertEqual(rows[-4]['unknown_revenue_orders'], 1)
        self.assertEqual(rows[-4]['revenue'], 85000)

    async def test_pipeline_excludes_padding_and_today_and_blocks_unknown_prices(self):
        from web import app as webapp
        today = date.today()
        rows = [{'date': (today-timedelta(days=29-i)).isoformat(),
                 'revenue': 100000 if i<29 else 999999999,
                 'orders': 1, 'is_observed': i>=5, 'is_complete': i<29,
                 'unknown_revenue_orders': 0} for i in range(30)]
        patches = [patch.object(webapp, 'get_revenue_timeseries', AsyncMock(return_value=rows))]
        for name, value in [('get_new_users_timeseries', []), ('count_users', 0),
                            ('count_active_subscription_profiles', 0), ('count_expiring_profiles', 0),
                            ('get_revenue_mix', {})]:
            patches.append(patch.object(db, name, AsyncMock(return_value=value)))
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        result = await webapp._analytics_stats()
        fc = result['forecast']
        self.assertEqual(fc['history_days'], 24)
        self.assertEqual(fc['total'], 700000)
        self.assertEqual(fc['points'][0]['date'], (today+timedelta(days=1)).isoformat())
        self.assertEqual(result['revenue_series'][-1]['revenue'], 999999999)
        rows[5]['unknown_revenue_orders'] = 57
        result = await webapp._analytics_stats()
        self.assertTrue(result['forecast']['ok'])
        self.assertEqual(result['forecast']['history_days'], 23)
        self.assertEqual(result['forecast']['excluded_history_days'], 1)
        self.assertEqual(result['forecast']['unknown_revenue_orders'], 57)
        rows[-2]['unknown_revenue_orders'] = 1
        result = await webapp._analytics_stats()
        self.assertFalse(result['forecast']['ok'])
        self.assertIsNone(result['forecast']['total'])
        self.assertEqual(result['forecast']['points'], [])


if __name__ == '__main__':
    unittest.main()
