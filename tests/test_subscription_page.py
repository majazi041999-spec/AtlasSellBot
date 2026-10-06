"""Browser copies must match the subscription clients receive, including variants."""
import base64
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, unquote, urlsplit
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web import app as web
from web.subscription_page import config_url, import_apps, published_nodes, render_page, telegram_contacts
from core import database as db, multi_subscription as multi

class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button' and attrs.get('data-link'):
            self.links.append(attrs['data-link'])

class SubscriptionPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = patch.object(web, 'get_setting', AsyncMock(return_value=''))
        settings.start()
        self.addCleanup(settings.stop)

    async def test_browser_copies_canonical_variants_instead_of_cached_raw_nodes(self):
        profile = dict(id=1, is_active=1, traffic_gb=1, used_bytes=0, expire_timestamp=0)
        raw = 'vless://test@old.example:443?type=ws&security=tls#Old'
        actual = 'vless://test@edge.example:443?type=ws&security=tls&ech=example%2Bhttps%3A%2F%2F8.8.8.8%2Fdns-query&path=%2F%3Fed%3D2560#New%20Plus'
        rendered = (base64.b64encode(actual.encode()).decode(), dict(upload=0, download=0, total=1024**3, expire=0))
        with patch.object(web, '_resolve_sub_brand', AsyncMock(return_value=('Test', False))), patch.object(web, '_resolve_sub_logo', AsyncMock(return_value='')), patch.object(web, 'subscription_url', AsyncMock(return_value='https://sub.example/sub/test')), patch.object(web, '_get_sub_nodes', AsyncMock(return_value=[dict(is_active=1, link=raw, node_label='Old')])), patch.object(web, 'render_subscription', AsyncMock(return_value=rendered)):
            html = await web._render_sub_status_html('test', profile)
        page = PageLinks(); page.feed(html)
        self.assertEqual(page.links, [actual])

    async def test_page_follows_real_database_server_switch_and_variant_settings(self):
        import aiosqlite
        link = 'vless://11111111-1111-4111-8111-111111111111@old.example:8443?type=ws&security=tls&sni=origin.example&host=origin.example&path=%2Fvpn&fp=chrome'
        profile = dict(id=1, is_active=1, traffic_gb=1, used_bytes=0, expire_timestamp=0)
        async def setting(key, default=''):
            settings = {'sub_info_sync_on_render': '0', 'subscription_ws_hide_regular': '{"2:3":true}',
                        'subscription_ws_ech': json.dumps({'2:3': {'primary': 'trws.anacotig.com+https://8.8.8.8/dns-query'}})}
            return settings.get(key, default)
        with tempfile.TemporaryDirectory() as directory, patch.object(db, 'DB_PATH', str(Path(directory) / 'test.db')):
            async with aiosqlite.connect(db.DB_PATH) as connection:
                await connection.executescript(db.SCHEMA)
                await db._ensure_columns(connection)
                await connection.execute("INSERT INTO servers(id,name,url,username,password,sub_path,is_active) VALUES(2,'NL','http://unused','u','p','',1)")
                await connection.execute("INSERT INTO subscription_node_configs(id,server_id,inbound_id,label,connect_host) VALUES(16,2,3,'Netherlands','edge.example')")
                await connection.execute("INSERT INTO subscription_nodes(profile_id,server_id,inbound_id,uuid,email,link,config_id) VALUES(1,2,3,'test','qa_n16',?,16)", (link,))
                await connection.commit()
            with patch.object(multi, 'get_subscription_profile_by_token', AsyncMock(return_value=profile)), patch.object(multi, 'get_setting', setting), patch.object(multi, '_subscription_info_links', AsyncMock(return_value=[multi._fake_info_link('Usage')])), patch.object(web, '_get_sub_profile_by_token', AsyncMock(return_value=profile)), patch.object(web, '_resolve_sub_brand', AsyncMock(return_value=('Test', False))), patch.object(web, '_resolve_sub_logo', AsyncMock(return_value='')), patch.object(web, 'subscription_url', AsyncMock(return_value='https://sub.example/sub/test')):
                async def snapshot():
                    response = await web.public_subscription('test', Request({'type':'http','method':'GET','path':'/sub/test','query_string':b'','headers':[(b'user-agent', b'Mozilla/5.0'), (b'accept', b'text/html')]}))
                    page = PageLinks(); page.feed(response.body.decode())
                    canonical = await multi.render_subscription('test')
                    self.assertEqual(page.links, [link for _, link in published_nodes(canonical[0])])
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    return page.links
                before = await snapshot()
                self.assertEqual(len(before), 1)
                self.assertEqual(urlsplit(before[0]).hostname, 'edge.example')
                self.assertIn('ech', parse_qs(urlsplit(before[0]).query))
                await db.update_server(2, is_active=0)
                self.assertEqual(await snapshot(), [])
                with patch.object(multi, 'schedule_server_activation'):
                    await db.update_server(2, is_active=1)
                self.assertEqual(await snapshot(), before)

    async def test_browser_awaits_publication_once_without_background_race(self):
        profile = dict(id=1, is_active=1, traffic_gb=1, used_bytes=0, expire_timestamp=0)
        with patch.object(web, '_get_sub_profile_by_token', AsyncMock(return_value=profile)), patch.object(web, '_resolve_sub_brand', AsyncMock(return_value=('Test', False))), patch.object(web, '_resolve_sub_logo', AsyncMock(return_value='')), patch.object(web, 'subscription_url', AsyncMock(return_value='https://sub.example/sub/test')), patch.object(web, 'render_subscription', AsyncMock(return_value=('', dict(download=0, upload=0, total=1024**3, expire=1791361800)))) as render:
            response = await web.public_subscription('test', Request({'type':'http','method':'GET','path':'/sub/test','query_string':b'html=1','headers':[]}))
            render.assert_awaited_once_with('test')
            self.assertIn('2026-10-07', response.body.decode())
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')

    def test_expired_subscription_never_exposes_cached_working_links(self):
        link = 'vless://test@example.com:443?type=ws#Old'
        rendered = (base64.b64encode(link.encode()).decode(), dict(download=100, total=100, expire=0))
        page = PageLinks(); page.feed(render_page(dict(is_active=1), rendered, 'https://sub.example/sub/test', 'Test', ''))
        self.assertEqual(page.links, [])

    def test_scheme_encoding_and_machine_format_preserve_url(self):
        url = config_url('https://sub.example/sub/test?html=1&source=a%26b&config=0')
        self.assertEqual(parse_qs(urlsplit(url).query), {'source':['a&b'], 'config':['1']})
        apps = {app['name']:app['href'] for app in import_apps(url, 'Name & فارسی')}
        for name in ('V2Box', 'v2rayNG'):
            self.assertEqual(parse_qs(urlsplit(apps[name]).query)['url'], [url])
        self.assertEqual(unquote(apps['Streisand'].removeprefix('streisand://import/')), url)
        self.assertEqual(apps['Happ'].removeprefix('happ://add/'), url)

    def test_synthetic_status_nodes_hidden_and_untrusted_labels_escaped(self):
        label = '<script>alert(1)</script>'
        link = 'vless://test@example.com:443?type=ws#' + label
        rendered = (base64.b64encode((multi._fake_info_link('Usage') + '\n' + link).encode()).decode(), dict(download=0, total=0, expire=0))
        html = render_page(dict(is_active=1, name=label), rendered, 'https://sub.example/sub/test', label, '')
        page = PageLinks(); page.feed(html)
        self.assertEqual(page.links, [link])
        self.assertNotIn(label, html)
        self.assertIn('&lt;script&gt;', html)

    async def test_representative_page_does_not_leak_platform_contacts(self):
        profile = dict(id=1, is_active=1)
        with patch.object(web, '_resolve_sub_brand', AsyncMock(return_value=('Representative Brand', True))), patch.object(web, '_resolve_sub_logo', AsyncMock(return_value='')), patch.object(web, 'get_setting', AsyncMock()) as settings, patch.object(web, 'subscription_url', AsyncMock(return_value='https://sub.example/sub/test')), patch.object(web, 'render_subscription', AsyncMock(return_value=('', dict(download=0, total=0, expire=0)))):
            html = await web._render_sub_status_html('test', profile)
        self.assertIn('Representative Brand', html)
        self.assertNotIn('t.me/', html)
        self.assertNotIn('atlas-logo.webp', html)
        settings.assert_not_awaited()

    def test_contact_settings_cannot_inject_arbitrary_links(self):
        contacts = telegram_contacts('@atlas_account_bot', 'atlas_account', 'atlastutorial', 'javascript:alert(1)')
        self.assertEqual(len(contacts), 3)
        self.assertEqual(contacts[0]['href'], 'https://t.me/atlas_account_bot')

if __name__ == '__main__':
    unittest.main()
