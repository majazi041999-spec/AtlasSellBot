"""Renewal replaces the old entitlement, regardless of remaining time/traffic."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import ExitStack
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import multi_subscription as multi, renewal, database

NOW = 1800000000
DAY = 86400000

class RenewalTests(unittest.IsolatedAsyncioTestCase):
    async def test_reactivation_resets_deferred_counter_before_publishing(self):
        link='vless://11111111-1111-4111-8111-111111111111@edge.example:443?type=ws&security=tls&sni=origin.example&host=origin.example&path=%2Fvpn'
        for reset_ok in (True,False):
            with self.subTest(reset_ok=reset_ok), ExitStack() as stack:
                profile=dict(id=1,email='qa',is_active=1,traffic_gb=30,used_bytes=0,
                             expire_timestamp=NOW*1000+7*DAY)
                node=dict(id=2,email='qa_n9',server_id=2,inbound_id=3,config_id=9,
                          server_url='test',srv_user='',srv_pass='',uuid='test',link=link,
                          server_active=1,node_config_active=1,is_active=0,
                          renewal_reset_pending=1,last_used_bytes=0,carried_bytes=0)
                config=dict(node,id=9)
                cli=MagicMock(update_client=AsyncMock(return_value=True),
                              get_client_link=AsyncMock(return_value=link),
                              reset_client_traffic=AsyncMock(return_value=reset_ok),close=AsyncMock())
                async def save_node(node_id,**kw):
                    self.assertEqual(node_id,2)
                    if kw.get('is_active')==1:
                        cli.reset_client_traffic.assert_awaited_once_with(3,'qa_n9')
                        self.assertEqual(node['renewal_reset_pending'],0)
                    node.update(kw)
                stack.enter_context(patch.object(database,'get_cut_profile_ids',AsyncMock(return_value=set())))
                for name,value in [('get_subscription_nodes',AsyncMock(return_value=[node])),
                                   ('get_subscription_node_configs',AsyncMock(return_value=[config])),
                                   ('get_server',AsyncMock(return_value={'is_active':1})),
                                   ('XUIClient',MagicMock(return_value=cli)),
                                   ('_remote_identity_and_link',AsyncMock(return_value=(3,'test',link))),
                                   ('update_subscription_node',AsyncMock(side_effect=save_node))]:
                    stack.enter_context(patch.object(multi,name,value))
                stack.enter_context(patch.object(multi.time,'time',return_value=NOW))
                result=await multi.ensure_subscription_profile_nodes(profile,force_refresh=True,
                                                                     only_config_ids={9},restore_limits=True)
                self.assertEqual(result['failed'],0 if reset_ok else 1)
                self.assertEqual(node['is_active'],int(reset_ok))
                self.assertEqual(node['renewal_reset_pending'],int(not reset_ok))
                if not reset_ok:
                    self.assertFalse(cli.update_client.await_args.args[-1])

    async def test_renewal_then_usage_sync_excludes_previous_disabled_node_usage(self):
        for disabled_by in ('server_active', 'node_config_active'):
            with self.subTest(disabled_by=disabled_by):
                profile = dict(id=1, is_active=1, traffic_gb=100, used_bytes=25*1024**3,
                               expire_timestamp=NOW*1000+DAY)
                common = dict(server_url='test', srv_user='', srv_pass='', inbound_id=1,
                              uuid='test', server_active=1, node_config_active=1)
                nodes = [dict(common, id=1, email='active', last_used_bytes=7*1024**3),
                         dict(common, id=2, email='off', last_used_bytes=12*1024**3,
                              carried_bytes=6*1024**3, is_active=0)]
                nodes[1][disabled_by] = 0
                async def save_node(node_id, **kw):
                    next(n for n in nodes if n['id']==node_id).update(kw)
                async def save_profile(profile_id, **kw):
                    self.assertEqual(profile_id,1)
                    profile.update(kw)
                cli=MagicMock(update_client=AsyncMock(return_value=True),
                              reset_client_traffic=AsyncMock(return_value=True),
                              get_client_traffic=AsyncMock(return_value={'up':100,'down':200}),
                              close=AsyncMock())
                with patch.object(multi,'get_subscription_nodes',AsyncMock(side_effect=lambda _:nodes)), \
                     patch.object(multi,'XUIClient',return_value=cli), \
                     patch.object(multi,'_remote_identity_and_link',AsyncMock(return_value=(1,'test',''))), \
                     patch.object(multi,'update_subscription_node',side_effect=save_node), \
                     patch.object(multi,'update_subscription_profile',side_effect=save_profile), \
                     patch.object(multi,'repair_subscription_profile_expiry',AsyncMock(side_effect=lambda p:p)), \
                     patch.object(multi.time,'time',return_value=NOW):
                    self.assertTrue((await multi.renew_subscription_profile(profile,30,7))['ok'])
                    synced=await multi.sync_profile_usage(profile)
                self.assertEqual(synced['used'],300)
                self.assertEqual(nodes[1]['is_active'],0)
                cli.update_client.assert_awaited_once()
                cli.reset_client_traffic.assert_awaited_once()

    async def test_subscription_replaces_every_previous_plan(self):
        for old_gb, used, expiry, unstarted in [(100, 20, NOW*1000+10*DAY, False), (0, 20, 0, False), (100, 0, 0, True), (100,100,NOW*1000-DAY,False)]:
            for gb, days in [(30,7),(0,0)]:
                with self.subTest(old_gb=old_gb, unstarted=unstarted, gb=gb, days=days):
                    profile = dict(id=1,traffic_gb=old_gb,used_bytes=used*1024**3,expire_timestamp=expiry,starts_on_first_use=int(unstarted),first_use_at=0 if unstarted else (NOW-86400)*1000)
                    cli=MagicMock()
                    cli.update_client=AsyncMock(return_value=True)
                    cli.reset_client_traffic=AsyncMock(return_value=True)
                    cli.close=AsyncMock()
                    node=dict(id=1,server_url='test',srv_user='',srv_pass='',inbound_id=1,uuid='test',email='test')
                    with patch.object(multi,'get_subscription_profile',AsyncMock(return_value=profile)), patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=[node])), patch.object(multi,'XUIClient',return_value=cli), patch.object(multi,'_remote_identity_and_link',AsyncMock(return_value=(1,'test',''))), patch.object(multi,'update_subscription_node',AsyncMock()), patch.object(multi,'update_subscription_profile',AsyncMock()) as save, patch.object(multi.time,'time',return_value=NOW):
                        result=await multi.renew_subscription_profile(profile,gb,days)
                        self.assertTrue(result['ok'])
                        self.assertEqual(save.call_args.kwargs['traffic_gb'],gb)
                        self.assertEqual(save.call_args.kwargs['expire_timestamp'], NOW*1000+days*DAY if days else 0)
                        self.assertEqual(save.call_args.kwargs['duration_days'],days)
                        self.assertEqual(save.call_args.kwargs['used_bytes'],0)
                        cli.update_client.assert_awaited_with(1,'test','test',gb,NOW*1000+days*DAY if days else 0,True)

    async def test_partial_panel_reset_is_not_reported_as_success(self):
        cli=MagicMock()
        cli.update_client=AsyncMock(return_value=True)
        cli.reset_client_traffic=AsyncMock(side_effect=[True,False])
        cli.close=AsyncMock()
        nodes=[dict(id=i,server_url='test',srv_user='',srv_pass='',inbound_id=i,uuid='test',email='test') for i in [1,2]]
        nodes.append(dict(id=3,server_active=0,last_used_bytes=1234,carried_bytes=45))
        with patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), patch.object(multi,'XUIClient',return_value=cli), patch.object(multi,'_remote_identity_and_link',AsyncMock(return_value=(1,'test',''))), patch.object(multi,'update_subscription_node',AsyncMock()) as save_node, patch.object(multi,'update_subscription_profile',AsyncMock()) as save:
            result=await multi.renew_subscription_profile({'id':1},30,7)
            self.assertFalse(result['ok'])
            self.assertIn('traffic_reset_failed',result['error'])
            save.assert_not_awaited()
            self.assertNotIn(3,[call.args[0] for call in save_node.await_args_list])

    async def test_legacy_restarts_expiry_from_now(self):
        server=dict(id=1,url='test',username='',password='')
        cli=MagicMock()
        cli.find_client=AsyncMock(return_value={'client':{'id':'test','email':'test','expiryTime':NOW*1000+20*DAY},'inbound_id':1})
        cli.get_client_traffic=AsyncMock(return_value={'expiryTime':NOW*1000+30*DAY})
        for name in ['update_client','reset_client_traffic']:
            setattr(cli,name,AsyncMock(return_value=True))
        for name in ['get_client_link','get_subscription_link','close']:
            setattr(cli,name,AsyncMock(return_value=''))
        with patch.object(renewal,'get_server',AsyncMock(return_value=server)), patch.object(renewal,'get_servers',AsyncMock(return_value=[])), patch.object(renewal,'XUIClient',return_value=cli), patch.object(renewal,'update_config',AsyncMock()) as save, patch.object(renewal,'clear_config_alerts',AsyncMock()), patch.object(renewal.time,'time',return_value=NOW):
            result=await renewal.find_and_renew_config(dict(id=1,server_id=1,email='test',uuid='test',expire_timestamp=NOW*1000+10*DAY),30,7)
            self.assertTrue(result['ok'])
            self.assertEqual(save.call_args.kwargs['expire_timestamp'],NOW*1000+7*DAY)

if __name__ == '__main__':
    unittest.main()
