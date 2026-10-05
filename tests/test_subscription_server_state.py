"""Server switch regression: cached links, offline usage and stale order targets."""
import asyncio,base64,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import database as db, multi_subscription as multi
from test_subscription_tuning import WS

class ServerStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_activation_restores_only_enabled_configs_on_that_server(self):
        profile=dict(id=1,token='test',is_active=1)
        configs=[dict(id=17,server_id=4),dict(id=13,server_id=6)]
        with patch.object(multi,'get_subscription_node_configs',AsyncMock(return_value=configs)),patch.object(multi,'get_active_subscription_profiles',AsyncMock(return_value=[profile])),patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)),patch.object(multi,'get_server',AsyncMock(return_value={'is_active':1})),patch.object(multi,'ensure_subscription_profile_nodes',AsyncMock()) as ensure:
            multi.schedule_server_activation(4)
            await multi._server_activation_tasks[4]
            ensure.assert_awaited_once_with(profile,force_refresh=True,only_config_ids={17},restore_limits=True)
            self.assertNotIn(4,multi._server_activation_tasks)

    async def test_order_provisions_healthy_targets_concurrently(self):
        nodes=[dict(id=i,server_id=i,server_active=1,inbound_id=3,server_url='http://unused',srv_user='u',srv_pass='p') for i in (1,2)]
        active=0;peak=0
        async def add(*args,**kwargs):
            nonlocal active,peak
            active+=1;peak=max(peak,active);await asyncio.sleep(.02);active-=1;return True
        client=MagicMock(side_effect=lambda *a,**k:AsyncMock(add_client=AsyncMock(side_effect=add)))
        with patch.object(multi,'get_available_subscription_node_configs',AsyncMock(return_value=nodes)),patch.object(multi,'expand_node_configs',AsyncMock(return_value=nodes)),patch.object(multi,'get_server',AsyncMock(return_value={'is_active':1})),patch.object(multi,'subscription_url',AsyncMock(return_value='https://sub.example/sub/test')),patch.object(multi,'get_setting',AsyncMock(return_value='1')),patch.object(multi,'create_subscription_profile',AsyncMock(return_value=1)),patch.object(multi,'delete_subscription_profile',AsyncMock()),patch.object(multi,'add_subscription_node',AsyncMock()) as store,patch.object(multi,'_remote_identity_and_link',AsyncMock(return_value=(3,'test',WS))),patch.object(multi,'XUIClient',client):
            result=await multi.create_profile_for_order({'id':1,'telegram_id':1},{'id':1},1,1)
            self.assertTrue(result['ok'],result.get('error'))
            self.assertEqual(result['nodes'],2);self.assertEqual(store.await_count,2);self.assertEqual(peak,2)

    async def test_cached_nodes_follow_physical_server_switch(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(db,'DB_PATH',str(Path(directory)/'test.db')):
            import aiosqlite
            async with aiosqlite.connect(db.DB_PATH) as connection:
                await connection.executescript(db.SCHEMA)
                await db._ensure_columns(connection)
                await connection.execute("INSERT INTO servers(id,name,url,username,password,sub_path,is_active) VALUES(4,'DE','http://unused','u','p','',1)")
                await connection.execute("INSERT INTO subscription_node_configs(id,server_id,inbound_id,label) VALUES(17,4,3,'Germany WS')")
                await connection.execute("INSERT INTO subscription_nodes(profile_id,server_id,inbound_id,uuid,email,link,config_id) VALUES(1,4,3,'test','qa_n17',?,17)",(WS+'#Germany%20WS',))
                await connection.commit()
            profile=dict(id=1,is_active=1,traffic_gb=1,used_bytes=0,expire_timestamp=0)
            async def setting(key,default=''):return '0' if key=='sub_info_sync_on_render' else default
            with patch.object(multi,'get_subscription_profile_by_token',AsyncMock(return_value=profile)),patch.object(multi,'get_setting',setting),patch.object(multi,'_subscription_info_links',AsyncMock(return_value=[])):
                before=await multi.render_subscription('test')
                await db.update_server(4,is_active=0)
                after=await multi.render_subscription('test')
                self.assertEqual(base64.b64decode(after[0]),b'')
                # A retained client returns immediately on activation, unchanged.
                with patch.object(multi,'schedule_server_activation'):
                    await db.update_server(4,is_active=1)
                restored=await multi.render_subscription('test')
                self.assertEqual(before,restored)

    async def test_offline_usage_uses_banked_counters_without_panel_call(self):
        profile=dict(id=1,is_active=1,traffic_gb=10,used_bytes=140,expire_timestamp=0)
        node=dict(id=1,server_id=4,server_active=0,last_used_bytes=100,carried_bytes=40,server_url='http://unused',srv_user='u',srv_pass='p',email='qa')
        client=MagicMock(return_value=AsyncMock())
        with patch.object(multi,'repair_subscription_profile_expiry',AsyncMock(return_value=profile)),patch.object(multi,'get_subscription_nodes',AsyncMock(return_value=[node])),patch.object(multi,'update_subscription_profile',AsyncMock()) as update,patch.object(multi,'XUIClient',client):
            result=await multi.sync_profile_usage(profile)
            self.assertEqual(result['used'],140)
            client.assert_not_called()
            self.assertEqual(update.await_args.kwargs['used_bytes'],140)

    async def test_stale_order_target_is_checked_before_any_panel_call(self):
        node=dict(id=17,server_id=4,server_active=1,inbound_id=3)
        with patch.object(multi,'get_available_subscription_node_configs',AsyncMock(return_value=[node])),patch.object(multi,'expand_node_configs',AsyncMock(return_value=[node])),patch.object(multi,'get_server',AsyncMock(return_value={'id':4,'is_active':0}),create=True),patch.object(multi,'subscription_url',AsyncMock(return_value='https://sub.example/sub/test')),patch.object(multi,'get_setting',AsyncMock(return_value='1')),patch.object(multi,'create_subscription_profile',AsyncMock(return_value=1)),patch.object(multi,'delete_subscription_profile',AsyncMock()),patch.object(multi,'XUIClient') as client:
            result=await multi.create_profile_for_order({'id':1,'telegram_id':1},{'id':1},1,1)
            self.assertFalse(result['ok'])
            client.assert_not_called()

if __name__=='__main__':unittest.main()
