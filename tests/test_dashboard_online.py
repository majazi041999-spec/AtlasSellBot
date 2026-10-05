"""Dashboard keeps observed connections visible with their real node status."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import autonode, database
from web import app as web


class DashboardOnlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_reconciliation_does_not_change_node_state(self):
        with patch.object(web, '_auth', return_value=True), \
             patch.object(web, 'get_subscription_node_config', AsyncMock(return_value={'is_active':1})), \
             patch.object(web, '_read_job_log', return_value={'running':True}), \
             patch.object(web, 'update_subscription_node_config', AsyncMock()) as update:
            response = await web.subscription_node_toggle(object(), 9)
            self.assertEqual(response.status_code, 409)
            update.assert_not_awaited()

    async def test_rejected_job_start_restores_previous_state(self):
        with patch.object(web, '_auth', return_value=True), \
             patch.object(web, 'get_subscription_node_config', AsyncMock(return_value={'is_active':1})), \
             patch.object(web, '_read_job_log', return_value={'running':False}), \
             patch.object(web, '_start_nodeops', return_value=False), \
             patch.object(web, 'update_subscription_node_config', AsyncMock()) as update:
            response = await web.subscription_node_toggle(object(), 9)
            self.assertEqual(response.status_code, 409)
            self.assertEqual([c.kwargs['is_active'] for c in update.await_args_list], [0, 1])

    async def test_disabled_observed_clients_are_labelled_and_unknown_is_not_zero(self):
        servers = [dict(id=2, name='NL', is_active=1, online=3, checked_at=123,
                        online_nodes={'9':2, '16':1}),
                   dict(id=4, name='DE', is_active=1, online=None, checked_at=100,
                        online_nodes=None, stale=True)]
        configs = [dict(id=9, label='Ultra', is_active=0), dict(id=16, label='WS', is_active=1)]
        with patch.object(web, '_api_guard', return_value=True), \
             patch.object(web, 'get_stats', AsyncMock(return_value={})), \
             patch.object(web, 'get_pending_orders', AsyncMock(return_value=[])), \
             patch.object(database, 'build_daily_report', AsyncMock(return_value={})), \
             patch.object(autonode, 'server_load_snapshot', AsyncMock(return_value=servers)), \
             patch.object(web, 'get_subscription_node_configs', AsyncMock(return_value=configs)):
            online = json.loads((await web.api_dashboard(object())).body)['online']
        self.assertEqual(online['total'], 3)
        self.assertEqual(online['servers_known'], 1)
        self.assertEqual(online['servers_total'], 2)
        nl, de = online['servers']
        self.assertEqual(nl['checked_at'], 123)
        self.assertEqual(nl['nodes'][0], dict(id=9, label='Ultra', online=2, is_active=False))
        self.assertIsNone(de['online'])
        self.assertIsNone(de['nodes'])


if __name__ == '__main__':
    unittest.main()
