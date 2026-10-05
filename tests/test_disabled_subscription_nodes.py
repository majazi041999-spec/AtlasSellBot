"""A renewed subscription must not reactivate an admin-disabled node."""
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import multi_subscription as multi
from core import database

LINK = 'vless://11111111-1111-4111-8111-111111111111@edge.example:443?type=ws&security=tls&sni=origin.example&host=origin.example&path=%2Fvpn'


class DisabledNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_entitlement_changes_leave_disabled_nodes_off(self):
        for operation in ('enable', 'renew', 'edit', 'reset_time'):
            with self.subTest(operation=operation), ExitStack() as stack:
                profile = dict(id=1, email='sub_test', traffic_gb=30, expire_timestamp=0)
                common = dict(server_url='test', srv_user='', srv_pass='', server_active=1,
                              inbound_id=3, uuid='test', remote_disabled_at=123)
                nodes = [dict(common, id=1, email='sub_test_n17', node_config_active=1),
                         dict(common, id=2, email='sub_test_n9', node_config_active=0)]
                cli = MagicMock(update_client=AsyncMock(return_value=True),
                                reset_client_traffic=AsyncMock(return_value=True),
                                close=AsyncMock())
                stack.enter_context(patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=nodes)))
                stack.enter_context(patch.object(multi, 'get_subscription_profile', AsyncMock(return_value=profile)))
                stack.enter_context(patch.object(database, 'get_subscription_profile', AsyncMock(return_value=profile)))
                stack.enter_context(patch.object(multi, 'XUIClient', return_value=cli))
                stack.enter_context(patch.object(multi, '_remote_identity_and_link', AsyncMock(return_value=(3, 'test', LINK))))
                save = stack.enter_context(patch.object(multi, 'update_subscription_node', AsyncMock()))
                stack.enter_context(patch.object(multi, 'update_subscription_profile', AsyncMock()))
                if operation == 'enable':
                    await multi.set_nodes_enabled(1, True)
                elif operation == 'renew':
                    result = await multi.renew_subscription_profile(profile, 30, 7)
                    self.assertTrue(result['ok'])
                elif operation == 'edit':
                    result = await multi.edit_subscription_profile(profile, 'sub_test', 30, 0, True)
                    self.assertTrue(result['ok'])
                else:
                    result = await multi.reset_subscription_time(1)
                    self.assertTrue(result['ok'])
                enabled_emails = [call.args[2] for call in cli.update_client.await_args_list if call.args[5]]
                self.assertEqual(enabled_emails, ['sub_test_n17'] * (2 if operation == 'reset_time' else 1))
                self.assertFalse(any(call.args[0] == 2 and call.kwargs.get('is_active') == 1
                                     for call in save.await_args_list))

    async def test_failed_remote_removal_keeps_a_retryable_row(self):
        node = dict(id=2, server_url='test', srv_user='', srv_pass='', inbound_id=4,
                    uuid='test', email='sub_test_n9')
        cli = MagicMock(delete_client=AsyncMock(return_value=False), close=AsyncMock())
        with patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=[node])), \
             patch.object(multi, 'XUIClient', return_value=cli), \
             patch.object(multi, 'delete_subscription_node', AsyncMock()) as delete, \
             patch.object(multi, 'update_subscription_node', AsyncMock()) as save:
            result = await multi._remove_node_config_from_profile({'id': 1}, 9)
            delete.assert_not_awaited()
            self.assertEqual(result['failed'], 1)
            save.assert_awaited_once_with(2, is_active=0, remote_disabled_at=0)

    async def test_enable_retries_disabling_an_unconfirmed_disabled_node(self):
        node = dict(id=2, server_url='test', srv_user='', srv_pass='', inbound_id=4,
                    uuid='test', email='sub_test_n9', node_config_active=0,
                    is_active=1, remote_disabled_at=0)
        cli = MagicMock(update_client=AsyncMock(return_value=True), close=AsyncMock())
        with patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=[node])), \
             patch.object(database, 'get_subscription_profile', AsyncMock(return_value={'traffic_gb':30})), \
             patch.object(multi, 'XUIClient', return_value=cli), \
             patch.object(multi, 'update_subscription_node', AsyncMock()) as save:
            await multi.set_nodes_enabled(1, True)
            self.assertFalse(cli.update_client.await_args.args[5])
            self.assertEqual(save.await_args.kwargs['is_active'], 0)
            self.assertGreater(save.await_args.kwargs['remote_disabled_at'], 0)

    async def test_successful_remote_removal_deletes_only_the_target(self):
        common = dict(server_url='test', srv_user='', srv_pass='', inbound_id=4, uuid='test')
        nodes = [dict(common, id=2, email='sub_test_n9'), dict(common, id=1, email='sub_test_n17')]
        cli = MagicMock(delete_client=AsyncMock(return_value=True), close=AsyncMock())
        with patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=nodes)), \
             patch.object(multi, 'XUIClient', return_value=cli), \
             patch.object(multi, 'delete_subscription_node', AsyncMock()) as delete, \
             patch.object(multi, 'update_subscription_node', AsyncMock()):
            result = await multi._remove_node_config_from_profile({'id':1}, 9)
            delete.assert_awaited_once_with(2)
            self.assertEqual(result, {'removed':1, 'targets':1, 'failed':0})

    async def test_link_rotation_does_not_recreate_disabled_nodes(self):
        profile = dict(id=1, user_id=1, is_active=1, traffic_gb=30, expire_timestamp=123)
        common = dict(server_id=2, server_url='test', srv_user='', srv_pass='', inbound_id=4,
                      uuid='test', server_active=1)
        nodes = [dict(common, id=1, email='sub_test_n17', node_config_active=1, config_id=17),
                 dict(common, id=2, email='sub_test_n9', node_config_active=0, config_id=9)]
        cli = MagicMock(add_client=AsyncMock(return_value=True), update_client=AsyncMock(return_value=True),
                        delete_client=AsyncMock(return_value=True), close=AsyncMock())
        with patch.object(multi, 'get_subscription_profile', AsyncMock(return_value=profile)), \
             patch.object(multi, 'subscription_url', AsyncMock(return_value='https://sub.example/sub/test')), \
             patch.object(multi, 'get_subscription_nodes', AsyncMock(return_value=nodes)), \
             patch.object(multi, 'XUIClient', return_value=cli), \
             patch.object(multi, '_remote_identity_and_link', AsyncMock(return_value=(4, 'test', LINK))), \
             patch.object(multi, 'update_subscription_node', AsyncMock()), \
             patch.object(multi, 'update_subscription_profile', AsyncMock()):
            result = await multi.rotate_subscription_link(1)
            self.assertEqual(result['rotated'], 1)
            self.assertEqual(cli.add_client.await_count, 1)
            self.assertTrue(cli.add_client.await_args.args[2].endswith('_n17'))


if __name__ == '__main__':
    unittest.main()
