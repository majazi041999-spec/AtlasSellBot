import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.subscription_tuning import apply_ws_early_data, apply_ws_ech, apply_ws_backup, without_ws_early_data, apply_ws_tls_frontend
from core import multi_subscription as multi
from core.subscription_variants import describe_variants, variant_enabled, toggle_variant

UUID = '11111111-1111-4111-8111-111111111111'
WS = f'vless://{UUID}@edge.example:8443?type=ws&security=tls&sni=origin.example&host=origin.example&path=%2Fvpn%2F%3Ftoken%3Dabc&fp=chrome'
ECH = 'trws.anacotig.com+https://8.8.8.8/dns-query'

class TuningTests(unittest.TestCase):
    def test_tls_frontend_exports_public_endpoint_with_same_identity_and_path(self):
        raw=WS.replace('security=tls','security=none').replace(':8443',':16443')
        result=apply_ws_tls_frontend(raw,{'port':443,'server_name':'public.example'})
        before,after=urlsplit(raw),urlsplit(result)
        self.assertEqual(after.username,before.username)
        self.assertEqual(after.hostname,before.hostname)
        self.assertEqual(after.port,443)
        query=parse_qs(after.query)
        self.assertEqual(query['path'],parse_qs(before.query)['path'])
        self.assertEqual(query['security'],['tls'])
        self.assertEqual(query['sni'],['public.example'])
        self.assertEqual(query['host'],['public.example'])
        for bad in [{},{'port':True,'server_name':'public.example'},
                    {'port':443,'server_name':'bad\nhost'}, {'port':70000,'server_name':'public.example'}]:
            self.assertEqual(apply_ws_tls_frontend(raw,bad),'')
        self.assertEqual(apply_ws_tls_frontend(WS,{'port':443,'server_name':'public.example'}),'')
    def test_backup_rejects_unverified_hosts_resolvers_and_malformed_settings(self):
        for options in [None, [], {}, {'address':[]}, {'address':'unverified.example'},
                        {'address':'virgool.io','no_ed':'true'},
                        {'address':'virgool.io','ech':{}},
                        {'address':'virgool.io','ech':'blogfa.com+http://8.8.8.8/dns-query'},
                        {'address':'virgool.io','ech':'evil.example+https://8.8.8.8/dns-query'}]:
            self.assertEqual(apply_ws_backup(WS,options),WS)
        reality=WS.replace('type=ws','type=tcp').replace('security=tls','security=reality')
        self.assertEqual(apply_ws_backup(reality,{'address':'virgool.io'}),reality)
        self.assertEqual(apply_ws_backup(WS,{'address':'virgool.io'}),WS.replace('edge.example','virgool.io'))

    def test_no_ed_variant_preserves_authentication_and_other_path_parameters(self):
        original = apply_ws_ech(apply_ws_early_data(WS, 2560), ECH)
        updated = without_ws_early_data(original)
        before, after = urlsplit(original), urlsplit(updated)
        self.assertEqual(before.netloc, after.netloc)
        old, new = parse_qs(before.query), parse_qs(after.query)
        old.pop('path')
        path = urlsplit(new.pop('path')[0])
        self.assertEqual(old, new)
        self.assertEqual(path.path, '/vpn/')
        self.assertEqual(parse_qs(path.query), {'token': ['abc']})
        self.assertEqual(without_ws_early_data(updated), updated)
        self.assertEqual(without_ws_early_data(WS), WS)
        reality = original.replace('type=ws', 'type=tcp').replace('security=tls', 'security=reality')
        self.assertEqual(without_ws_early_data(reality), reality)

    def test_dedupe_keeps_distinct_transports_but_ignores_labels_and_query_order(self):
        original = apply_ws_early_data(WS, 2560)
        no_ed = without_ws_early_data(original)
        ech = apply_ws_ech(original, ECH)
        parts = urlsplit(original)
        reordered = parts._replace(query='&'.join(reversed(parts.query.split('&'))), fragment='OtherLabel').geturl()
        self.assertEqual(multi._dedupe_complete_links([original, no_ed, ech, reordered]), [original, no_ed, ech])

    def test_ech_round_trip_preserves_transport_and_authentication(self):
        tuned = apply_ws_ech(WS, ECH)
        before, after = urlsplit(WS), urlsplit(tuned)
        self.assertEqual(before.netloc, after.netloc)
        query = parse_qs(after.query)
        self.assertEqual(query.pop('ech'), [ECH])
        self.assertEqual(query, parse_qs(before.query))
        self.assertEqual(apply_ws_ech(tuned, ECH), tuned)

    def test_ech_invalid_resolvers_and_non_ws_are_unchanged(self):
        for value in [None, {}, True, '', ECH+'\n', 'trws.anacotig.com+http://8.8.8.8/dns-query',
                      'trws.anacotig.com+https://user:pass@8.8.8.8/dns-query']:
            self.assertEqual(apply_ws_ech(WS, value), WS)
        reality = WS.replace('type=ws', 'type=tcp').replace('security=tls', 'security=reality')
        self.assertEqual(apply_ws_ech(reality, ECH), reality)

    def test_preserves_identity_and_existing_path_parameters(self):
        tuned = apply_ws_early_data(WS, 2560)
        before, after = urlsplit(WS), urlsplit(tuned)
        self.assertEqual(before.netloc, after.netloc)
        old, new = parse_qs(before.query), parse_qs(after.query)
        for key in ['type', 'security', 'sni', 'host', 'fp']:
            self.assertEqual(old[key], new[key])
        path = urlsplit(new['path'][0])
        self.assertEqual(path.path, '/vpn/')
        self.assertEqual(parse_qs(path.query), {'token': ['abc'], 'ed': ['2560']})
        self.assertEqual(apply_ws_early_data(tuned, 2560), tuned)

    def test_invalid_settings_and_other_transports_stay_identical(self):
        for value in [None, 0, -1, 8193, 'invalid', {}, True]:
            self.assertEqual(apply_ws_early_data(WS, value), WS)
        tcp = WS.replace('type=ws', 'type=tcp').replace('security=tls', 'security=reality')
        self.assertEqual(apply_ws_early_data(tcp, 2560), tcp)

class RenderTuningTests(unittest.IsolatedAsyncioTestCase):
    async def test_frontend_render_preserves_protected_nodes_and_omits_pending_resets(self):
        raw=WS.replace('security=tls','security=none').replace(':8443',':16443')
        germany=WS+'#Germany%20WS'
        frontend=json.dumps({'port':443,'server_name':'public.example'})
        nodes=[dict(id=1,server_id=2,inbound_id=6,is_active=1,link=raw,node_label='Instagram Test',
                    tls_frontend=frontend,connect_host='public.example'),
               dict(id=2,server_id=4,inbound_id=3,is_active=1,link=germany,node_label='Germany WS',
                    tls_frontend=frontend)]
        profile=dict(id=1,is_active=1,traffic_gb=30,used_bytes=0,expire_timestamp=0,name='QA')
        async def setting(key,default=''):
            return '0' if key=='sub_info_sync_on_render' else default
        with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), \
             patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), \
             patch.object(multi,'get_setting',setting), \
             patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])):
            rendered=await multi.render_subscription('test-token')
            links=base64.b64decode(rendered[0]).decode().splitlines()
            self.assertEqual(len(links),2)
            trial=urlsplit(links[0]);self.assertEqual((trial.hostname,trial.port),('public.example',443))
            self.assertEqual(parse_qs(trial.query)['security'],['tls'])
            self.assertEqual(links[1],germany)
            nodes[0]['renewal_reset_pending']=1
            hidden=await multi.render_subscription('test-token')
            self.assertEqual(base64.b64decode(hidden[0]).decode().splitlines(),[germany])
            nodes[0]['renewal_reset_pending']=0;nodes[0]['tls_frontend']='bad json'
            invalid=await multi.render_subscription('test-token')
            self.assertEqual(base64.b64decode(invalid[0]).decode().splitlines(),[germany])

    async def test_hide_regular_keeps_working_sibling_variants_and_protected_nodes(self):
        nl = apply_ws_early_data(WS, 2560) + '#Netherlands%20WS'
        usa = f'vless://{UUID}@usa.example:2083?type=tcp&security=reality&sni=example.com#USA%20New'
        germany = WS.replace('edge.example','de.example')+'#Germany%20WS'
        nodes=[dict(id=i,server_id=s,inbound_id=b,is_active=1,link=l,node_label=label)
               for i,s,b,l,label in [(1,2,3,nl,'Netherlands WS'),(2,6,2,usa,'USA New'),(3,4,3,germany,'Germany WS')]]
        counts=[]
        async def render(hidden,disabled=None):
            async def setting(key,default=''):
                options={'subscription_ws_hide_regular':hidden,
                         'subscription_ws_disabled_variants':disabled or {},
                         'subscription_ws_fallbacks':{'2:3':'edge-b.example'},
                         'subscription_ws_ech':{'2:3':{'primary':ECH,'backup':ECH}},
                         'subscription_ws_no_ed':{'2:3':True},
                         'subscription_ws_backups':{'2:3':[{'address':'virgool.io','ech':ECH}]}}
                if key in options:return json.dumps(options[key])
                if key=='sub_info_sync_on_render':return '0'
                return default
            async def info(profile,used,total,count):counts.append(count);return []
            profile=dict(id=1,is_active=1,traffic_gb=0,used_bytes=0,expire_timestamp=0,name='QA')
            with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), \
                 patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), \
                 patch.object(multi,'get_setting',setting), \
                 patch.object(multi,'_subscription_info_links',info):
                result=await multi.render_subscription('test-token')
                return base64.b64decode(result[0]).decode().splitlines()
        original=await render({})
        hidden=await render({'2:3':True,'4:3':True,'6:2':True})
        self.assertEqual(hidden,[l for l in original if l != nl])
        self.assertIn(usa,hidden);self.assertIn(germany,hidden)
        self.assertEqual(counts,[9,8])
        self.assertEqual(await render({'2:3':'true'}),original)
        masked=await render({}, {'2:3':['plus-backup','mobin','backup-0']})
        # Keep the Mobin backup independently when just its primary is hidden.
        expected=[l for l in original if not ('Plus%20Backup' in urlsplit(l).fragment or urlsplit(l).fragment.endswith('%7C%20Mobin%20WS') or 'Backup%201' in urlsplit(l).fragment)]
        self.assertEqual(masked,expected)
        nodes[0]['link']=nl.replace('type=ws','type=tcp').replace('security=tls','security=reality')
        non_ws=await render({})
        self.assertEqual(await render({'2:3':True}),non_ws)

    async def test_variant_panel_toggle_changes_only_selected_published_sibling(self):
        from core import subscription_variants as variants
        settings={'subscription_ws_ech':json.dumps({'2:3':{'primary':ECH,'backup':ECH}}),
                  'subscription_ws_fallbacks':json.dumps({'2:3':'edge-b.example'}),
                  'subscription_ws_hide_regular':json.dumps({'2:3':True})}
        async def get(key,default=''):return settings.get(key,default)
        async def set_(key,value):settings[key]=value
        with patch.object(variants,'get_setting',get),patch.object(variants,'set_setting',set_):
            self.assertFalse(await toggle_variant('2:3','plus-backup'))
            options=await variants.load_variant_options()
            rows={r['id']:r for r in describe_variants(options,'2:3','edge.example')}
            self.assertFalse(rows['plus-backup']['is_active'])
            self.assertTrue(rows['plus']['is_active']);self.assertFalse(rows['regular']['is_active'])
            self.assertTrue(await toggle_variant('2:3','plus-backup'))
            self.assertTrue(await toggle_variant('2:3','regular'))
            with self.assertRaises(ValueError):await toggle_variant('4:3','regular')
            with self.assertRaises(ValueError):await toggle_variant('2:3','not-a-variant')

    async def test_external_backups_are_additive_and_exclude_protected_targets(self):
        nl = apply_ws_early_data(WS, 2560) + '#Netherlands%20WS'
        usa = f'vless://{UUID}@usa.example:2083?type=tcp&security=reality&sni=example.com#USA%20New'
        germany = WS.replace('edge.example','de.example')+'#Germany%20WS'
        nodes=[dict(id=i,server_id=s,inbound_id=b,is_active=1,link=l,node_label=label)
               for i,s,b,l,label in [(1,2,3,nl,'Netherlands WS'),(2,6,2,usa,'USA New'),(3,4,3,germany,'Germany WS')]]
        options={'address':'virgool.io','ech':'www.tgju.org+https://8.8.4.4/dns-query','no_ed':True}
        async def render(backups):
            async def setting(key,default=''):
                if key=='subscription_ws_backups':return json.dumps(backups)
                if key=='sub_info_sync_on_render':return '0'
                return default
            profile=dict(id=1,is_active=1,traffic_gb=0,used_bytes=0,expire_timestamp=0,name='QA')
            with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), \
                 patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), \
                 patch.object(multi,'get_setting',setting), \
                 patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])):
                result=await multi.render_subscription('test-token')
                return base64.b64decode(result[0]).decode().splitlines()
        original=await render({})
        updated=await render({'2:3':[options],'4:3':[options],'6:2':[options]})
        self.assertEqual(updated[:len(original)],original)
        self.assertEqual(len(updated),len(original)+1)
        extra=urlsplit(updated[-1]);query=parse_qs(extra.query)
        self.assertEqual(extra.hostname,'virgool.io')
        self.assertEqual(extra.username,UUID)
        self.assertEqual(query['ech'],[options['ech']])
        self.assertEqual(query['sni'],['origin.example'])
        path=urlsplit(query['path'][0])
        self.assertEqual(parse_qs(path.query),{'token':['abc']})
        self.assertNotIn('ECH',extra.fragment)

    async def test_renderer_tunes_opted_target_and_preserves_protected_links(self):
        tuned = WS + '#Netherlands%20WS'
        usa = f'vless://{UUID}@usa.example:2083?type=tcp&security=reality&sni=example.com#USA%20New'
        germany = WS.replace('edge.example', 'de.example') + '#Germany%20WS'
        nodes = [dict(id=1,server_id=2,inbound_id=3,is_active=1,link=tuned,node_label='Netherlands WS'),
                 dict(id=2,server_id=6,inbound_id=2,is_active=1,link=usa,node_label='USA New'),
                 dict(id=3,server_id=4,inbound_id=3,is_active=1,link=germany,node_label='Germany WS'),
                 # Renewal can enable a client; its disabled config must still stay hidden.
                 dict(id=4,server_id=6,inbound_id=3,is_active=1,node_config_active=0,link=WS+'#Disabled',node_label='Disabled')]
        async def setting(key, default=''):
            if key == 'subscription_ws_early_data': return json.dumps({'2:3':2560})
            if key == 'subscription_ws_fallbacks': return json.dumps({'2:3':'edge-b.example'})
            if key == 'sub_info_sync_on_render': return '0'
            return default
        profile = dict(id=1,is_active=1,traffic_gb=0,used_bytes=0,expire_timestamp=0,name='QA')
        with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), \
             patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), \
             patch.object(multi,'get_setting',setting), \
             patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])):
            rendered = await multi.render_subscription('test-token')
        links = base64.b64decode(rendered[0]).decode().splitlines()
        self.assertIn(usa, links)
        self.assertIn(germany, links)
        self.assertEqual(len(links), 4)
        self.assertEqual(urlsplit(links[1]).hostname, 'edge-b.example')
        self.assertEqual(parse_qs(urlsplit(parse_qs(urlsplit(links[0]).query)['path'][0]).query)['ed'], ['2560'])

    async def test_ech_variants_coexist_with_unchanged_originals_and_protected_nodes(self):
        nl = WS + '#Netherlands%20WS'
        usa = f'vless://{UUID}@usa.example:2083?type=tcp&security=reality&sni=example.com#USA%20New'
        germany = WS.replace('edge.example', 'de.example') + '#Germany%20WS'
        nodes = [dict(id=i, server_id=s, inbound_id=b, is_active=1, link=l, node_label=label)
                 for i,s,b,l,label in [(1,2,3,nl,'Netherlands WS'),(2,6,2,usa,'USA New'),(3,4,3,germany,'Germany WS')]]
        async def render(ech, no_ed=False):
            async def setting(key, default=''):
                if key == 'subscription_ws_early_data': return json.dumps({'2:3':2560})
                if key == 'subscription_ws_no_ed': return json.dumps({'2:3':no_ed})
                if key == 'subscription_ws_fallbacks': return json.dumps({'2:3':'edge-b.example'})
                if key == 'subscription_ws_ech': return json.dumps(ech)
                if key == 'sub_info_sync_on_render': return '0'
                return default
            profile = dict(id=1,is_active=1,traffic_gb=0,used_bytes=0,expire_timestamp=0,name='QA')
            with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)), \
                 patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), \
                 patch.object(multi,'get_setting',setting), \
                 patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])):
                result = await multi.render_subscription('test-token')
                return base64.b64decode(result[0]).decode().splitlines()
        original = await render({})
        updated = await render({'2:3':{'primary':ECH,'backup':ECH.replace('8.8.8.8','8.8.4.4')}})
        self.assertEqual([l for l in updated if 'ech=' not in l], original)
        self.assertEqual(len(updated), len(original)+2)
        self.assertEqual(sum(l == usa or l == germany for l in updated), 2)
        self.assertEqual([urlsplit(l).hostname for l in updated if 'ech=' in l], ['edge.example','edge-b.example'])
        for link in updated:
            self.assertNotIn('ECH', urlsplit(link).fragment)
            self.assertNotIn('Irancell', urlsplit(link).fragment)
        self.assertTrue(all('Plus' in urlsplit(l).fragment for l in updated if 'ech=' in l))
        self.assertEqual(updated, multi._dedupe_complete_links(updated + updated))
        added = await render({'2:3':{'primary':ECH,'backup':ECH.replace('8.8.8.8','8.8.4.4')}}, True)
        self.assertEqual([l for l in added if 'Mobin' not in urlsplit(l).fragment], updated)
        variants = [l for l in added if 'Mobin' in urlsplit(l).fragment]
        self.assertEqual(len(variants), 2)
        self.assertEqual([urlsplit(l).hostname for l in variants], ['edge.example', 'edge-b.example'])
        for link in variants:
            self.assertNotIn('ed', parse_qs(urlsplit(parse_qs(urlsplit(link).query)['path'][0]).query))
            self.assertEqual(urlsplit(link).username, UUID)
            self.assertEqual(parse_qs(urlsplit(link).query)['sni'], ['origin.example'])
        self.assertEqual(await render({}, 'true'), original)

if __name__ == '__main__': unittest.main()
