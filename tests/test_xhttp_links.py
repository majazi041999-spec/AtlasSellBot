import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.xui_api import XUIClient
from core import multi_subscription as multi

class XhttpLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_remains_usable_without_panel_link_endpoint(self):
        cli = XUIClient('https://origin.example:8020', 'qa', 'qa')
        cli._req = AsyncMock(return_value=None)
        cli.get_inbound = AsyncMock(return_value={
            'protocol':'vless', 'port':2053,
            'settings':json.dumps({'clients':[{'id':'11111111-1111-4111-8111-111111111111','email':'qa'}]}),
            'streamSettings':json.dumps({'network':'xhttp','security':'tls','tlsSettings':{'serverName':'cdn.example','alpn':['h2']},'xhttpSettings':{'host':'cdn.example','path':'/assets/test/','mode':'stream-one','extra':{'xmux':{'maxConcurrency':8}}}}),
        })
        try:
            link = await cli.get_client_link(3, 'qa')
            values = parse_qs(urlsplit(link).query)
            self.assertEqual(values.get('path'), ['/assets/test/'])
            self.assertEqual(values.get('mode'), ['stream-one'])
            self.assertEqual(values.get('host'), ['cdn.example'])
            self.assertEqual(json.loads(values['extra'][0]), {'xmux':{'maxConcurrency':8}})
            self.assertEqual(values.get('sni'), ['cdn.example'])
            self.assertEqual(values.get('alpn'), ['h2'])
        finally:
            await cli.close()

    async def test_disabling_entry_hides_relay_but_preserves_usa_control(self):
        uuid = '11111111-1111-4111-8111-111111111111'
        control = f'vless://{uuid}@usa.example:2083?type=tcp&security=reality&sni=example.com#USA%20New'
        relay = f'vless://{uuid}@entry.example:2053?type=xhttp&security=tls&sni=origin.example&path=%2Ftest%2F&mode=stream-one#USA%20Plus'
        nodes = [dict(id=i,server_id=6,inbound_id=b,is_active=1,link=l,node_label=label)
                 for i,b,l,label in [(1,2,control,'USA New'),(2,3,relay,'USA Plus')]]
        profile = dict(id=1,is_active=1,traffic_gb=0,used_bytes=0,expire_timestamp=0,name='QA')
        async def setting(key,default=''):
            if key == 'subscription_node_dependencies': return '{"6:3":[4],"6:2":[4]}'
            if key == 'sub_info_sync_on_render': return '0'
            return default
        with patch.object(multi,'get_setting',setting), patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])), patch.object(multi,'get_server',AsyncMock(return_value={'is_active':0})) as server:
            off = await multi.render_subscription('test')
            self.assertEqual(base64.b64decode(off[0]).decode().splitlines(), [control])
            server.return_value = {'is_active':1}
            on = await multi.render_subscription('test')
            self.assertEqual(base64.b64decode(on[0]).decode().splitlines(), [control,relay])
            server.return_value = None
            missing = await multi.render_subscription('test')
            self.assertEqual(base64.b64decode(missing[0]).decode().splitlines(), [control])

if __name__ == '__main__': unittest.main()
