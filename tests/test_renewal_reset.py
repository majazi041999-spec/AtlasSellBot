"""Renewal replaces the old entitlement, regardless of remaining time/traffic."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import multi_subscription as multi, renewal

NOW = 1800000000
DAY = 86400000

class RenewalTests(unittest.IsolatedAsyncioTestCase):
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
        with patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=nodes)), patch.object(multi,'XUIClient',return_value=cli), patch.object(multi,'_remote_identity_and_link',AsyncMock(return_value=(1,'test',''))), patch.object(multi,'update_subscription_node',AsyncMock()), patch.object(multi,'update_subscription_profile',AsyncMock()) as save:
            result=await multi.renew_subscription_profile({'id':1},30,7)
            self.assertFalse(result['ok'])
            self.assertIn('traffic_reset_failed',result['error'])
            save.assert_not_awaited()

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
