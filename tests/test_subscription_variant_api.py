"""Admin handler: authorization and targeting of a single transport switch."""
import asyncio,json,sys,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from web import app as web

class VariantApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthorized_request_cannot_toggle(self):
        with patch.object(web,'_auth',return_value=False),patch.object(web,'toggle_variant',AsyncMock()) as switch:
            response=await web.subscription_variant_toggle(object(),16,'plus')
            self.assertEqual(response.status_code,401);switch.assert_not_called()

    async def test_authorized_switch_uses_stored_server_and_inbound(self):
        with patch.object(web,'_auth',return_value=True),patch.object(web,'get_subscription_node_config',AsyncMock(return_value={'server_id':2,'inbound_id':3})),patch.object(web,'toggle_variant',AsyncMock(return_value=False)) as switch:
            response=await web.subscription_variant_toggle(object(),16,'plus-backup')
            self.assertEqual(response.status_code,200)
            self.assertFalse(json.loads(response.body)['is_active'])
            switch.assert_awaited_once_with('2:3','plus-backup')

    async def test_invalid_variant_returns_400(self):
        with patch.object(web,'_auth',return_value=True),patch.object(web,'get_subscription_node_config',AsyncMock(return_value={'server_id':4,'inbound_id':3})),patch.object(web,'toggle_variant',AsyncMock(side_effect=ValueError('protected'))):
            response=await web.subscription_variant_toggle(object(),17,'regular')
            self.assertEqual(response.status_code,400)

if __name__=='__main__':unittest.main()
