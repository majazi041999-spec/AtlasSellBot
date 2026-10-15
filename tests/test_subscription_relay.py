"""Relay routes share entitlement; they must never resurrect disabled accounts."""
import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import multi_subscription as multi, subscription_variants as variants
from core.subscription_tuning import apply_ws_relay

UUID = '11111111-1111-4111-8111-111111111111'
LINK = f'vless://{UUID}@edge.example:2096?encryption=none&type=ws&security=tls&sni=origin.example&host=origin.example&path=%2Fvpn%2F%3Fed%3D2560&ech=old&alpn=h2'
RELAY = dict(address='entry.example', port=2053, server_name='turkey.example', path='/relay/test/')


class RelayTests(unittest.TestCase):
    def test_relay_retains_identity_and_encryption_but_uses_its_verified_route(self):
        result = urlsplit(apply_ws_relay(LINK, RELAY))
        self.assertEqual((result.username, result.hostname, result.port), (UUID, 'entry.example', 2053))
        q = parse_qs(result.query)
        self.assertEqual(q['security'], ['tls'])
        self.assertEqual(q['encryption'], ['none'])
        self.assertEqual(q['sni'], ['turkey.example'])
        self.assertEqual(q['host'], ['turkey.example'])
        self.assertEqual(q['path'], ['/relay/test/'])
        self.assertEqual(q['alpn'], ['http/1.1'])
        self.assertNotIn('ech', q)
        self.assertNotIn('ed', q)
        self.assertNotIn('allowInsecure', q)

    def test_invalid_or_incompatible_routes_are_not_published(self):
        for bad in [None, {}, dict(RELAY, port=True), dict(RELAY, port=65536),
                    dict(RELAY, address='bad\nhost'),
                    dict(RELAY, server_name=''), dict(RELAY, path='/test/?ed=2560')]:
            self.assertEqual(apply_ws_relay(LINK, bad), '')
        self.assertEqual(apply_ws_relay(LINK.replace('security=tls', 'security=none'), RELAY), '')
        self.assertEqual(apply_ws_relay(LINK.replace('type=ws', 'type=tcp'), RELAY), '')


class RelayRenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_hide_and_expire_share_parent_entitlement_without_new_clients(self):
        profile = dict(id=1, is_active=1, traffic_gb=1, used_bytes=12345, expire_timestamp=0, name='QA')
        nodes = [dict(id=1, server_id=1, inbound_id=3, is_active=1, link=LINK, node_label='Turkey'),
                 dict(id=2, server_id=4, inbound_id=3, is_active=1, link=LINK.replace('edge.example', 'germany.example'), node_label='Germany WS'),
                 dict(id=3, server_id=6, inbound_id=2, is_active=1, link=LINK.replace('edge.example', 'usa.example'), node_label='USA New')]
        settings = {'subscription_ws_relays': json.dumps({'1:3': RELAY, '4:3': RELAY, '6:2': RELAY})}
        async def get(key, default=''):
            if key == 'sub_info_sync_on_render': return '0'
            return settings.get(key, default)
        async def render():
            result = await multi.render_subscription('test-token')
            return base64.b64decode(result[0]).decode().splitlines(), result[1]
        with patch.object(multi, 'get_subscription_profile_by_token', AsyncMock(return_value=profile)), \
             patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=nodes)), \
             patch.object(multi, 'get_setting', get), \
             patch.object(multi, '_subscription_info_links', AsyncMock(return_value=[])), \
             patch.object(multi, '_subscription_expired_notice_links', AsyncMock(return_value=[])):
            published, info = await render()
            self.assertEqual(len(published), 4)
            self.assertEqual(urlsplit(published[-1]).username, UUID)
            self.assertEqual(info['download'], 12345)
            self.assertEqual(info['total'], 1024 ** 3)
            protected = published[1:3]
            for flag in ('server_active', 'node_config_active', 'is_active'):
                nodes[0][flag] = 0
                hidden, _ = await render()
                self.assertEqual(hidden, protected)
                nodes[0][flag] = 1
            nodes[0]['renewal_reset_pending'] = 1
            self.assertEqual((await render())[0], protected)
            nodes[0]['renewal_reset_pending'] = 0
            settings['subscription_ws_disabled_variants'] = json.dumps({'1:3': ['relay']})
            self.assertEqual((await render())[0], published[:3])
            profile['is_active'] = 0
            self.assertIsNone(await multi.render_subscription('test-token'))

    async def test_panel_switch_hides_only_relay(self):
        settings = {'subscription_ws_relays': json.dumps({'1:3': RELAY})}
        async def get(key, default=''): return settings.get(key, default)
        async def set_(key, value): settings[key] = value
        with patch.object(variants, 'get_setting', get), patch.object(variants, 'set_setting', set_):
            options = await variants.load_variant_options()
            rows = variants.describe_variants(options, '1:3')
            self.assertEqual([r['id'] for r in rows], ['regular', 'relay'])
            self.assertFalse(await variants.toggle_variant('1:3', 'relay'))
            options = await variants.load_variant_options()
            self.assertTrue(variants.variant_enabled(options, '1:3', 'regular'))
            self.assertFalse(variants.variant_enabled(options, '1:3', 'relay'))
            self.assertTrue(await variants.toggle_variant('1:3', 'relay'))


if __name__ == '__main__':
    unittest.main()
