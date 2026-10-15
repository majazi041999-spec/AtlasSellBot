"""Relay users are distinct from shared-ingress variants and missing samples."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import autonode, database, subscription_variants
from core.node_online import dashboard_nodes, relay_observers, sample_routes

CONFIGS = [dict(id=24, server_id=1, inbound_id=3, label='Turkey WS', is_active=1)]
OPTIONS = {'subscription_ws_relays': {'1:3': dict(address='nitro.example.com', port=2053,
    server_name='tls.example.com', path='/ws/', label='Turkey Nitro', source_ips=['127.0.0.2'])}}


class RouteCountTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_account_dual_connections_and_old_ips(self):
        observers = relay_observers(CONFIGS, OPTIONS, 1)
        sample = sample_routes(['a_n24', 'b_n24', 'c_n24', 'd_n24', 'a_n24'], {
            'a_n24': {'127.0.0.2': 999},
            'b_n24': {'203.0.113.1': 998},
            'c_n24': {'127.0.0.2': 998, '203.0.113.2': 998},
            'd_n24': {'127.0.0.2': 800},
        }, observers, 1000)
        self.assertEqual(sample['24'], dict(label='Turkey Nitro', relay=2, other=2, unknown=1, overlap=1))
        row = dashboard_nodes({'24': 4}, CONFIGS, 1, OPTIONS, sample)[0]
        self.assertEqual(row['online'], 4)
        self.assertIsNone(row['routes'][0]['online'])
        self.assertEqual(row['routes'][0]['observed'], 2)
        self.assertEqual(row['unattributed'], 1)
        self.assertEqual(row['overlap'], 1)

    def test_unknown_api_is_not_zero_but_empty_server_is(self):
        observers = relay_observers(CONFIGS, OPTIONS, 1)
        sample = sample_routes(['a_n24'], None, observers, 1000)
        row = dashboard_nodes({'24': 1}, CONFIGS, 1, OPTIONS, sample)[0]
        self.assertIsNone(row['routes'][0]['online'])
        zero = dashboard_nodes({}, CONFIGS, 1, OPTIONS)[0]
        self.assertEqual(zero['online'], 0)
        self.assertEqual([r['online'] for r in zero['routes']], [0, 0])
        self.assertIsNone(dashboard_nodes(None, CONFIGS, 1, OPTIONS))

    def test_same_sample_metadata_cannot_pollute_parent_counts(self):
        server = {'online_nodes': json.dumps({'24': 2, '_routes': {'24': {'relay': 1}}})}
        self.assertEqual(autonode._fresh_online_nodes(server, 2), {'24': 2})
        self.assertEqual(autonode._fresh_online_routes(server, 2), {'24': {'relay': 1}})
        self.assertIsNone(autonode._fresh_online_routes(server, None))

    async def test_poll_saves_route_and_total_in_one_sample_without_identities(self):
        cli = AsyncMock()
        cli.get_onlines_checked.return_value = (['a_n24', 'a_n24'], True)
        cli.get_client_ips_bulk.return_value = {'a_n24': {'127.0.0.2': 1000}}
        server = dict(id=1, url='test', username='test', password='test')
        with patch.object(database, 'get_subscription_node_configs', AsyncMock(return_value=CONFIGS)), \
             patch.object(subscription_variants, 'load_variant_options', AsyncMock(return_value=OPTIONS)), \
             patch.object(autonode, '_setting_int', AsyncMock(return_value=1)), \
             patch.object(autonode, 'XUIClient', return_value=cli), \
             patch.object(autonode.time, 'time', return_value=1000), \
             patch.object(autonode, 'set_server_online_stats', AsyncMock()) as save:
            self.assertEqual(await autonode.refresh_server_online_counts([server]), {1: 1})
        sample = save.await_args.args[3]
        self.assertEqual(sample['24'], 1)
        self.assertEqual(sample['_routes']['24']['relay'], 1)
        self.assertNotIn('a_n24', json.dumps(sample))
        self.assertNotIn('127.0.0.2', json.dumps(sample))


if __name__ == '__main__':
    unittest.main()
