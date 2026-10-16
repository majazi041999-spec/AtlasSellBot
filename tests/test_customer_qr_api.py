"""Exercise authenticated customer QR endpoints without a real DB or Telegram."""
import base64
import importlib
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from PIL import Image
web = importlib.import_module("web.app")
bot_user = importlib.import_module("bot.handlers.user")


class CustomerQrTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="https://test")
        self.user = {"id": 7}
        self.profile = {"id": 9, "user_id": 7, "token": "current", "name": "Owned"}
        self.settings = {"miniapp_enabled": "1", "channel_username": "Atlas_Account"}
        async def setting(key, default=""):
            return self.settings.get(key, default)
        self.patches = [patch.object(web, "get_setting", side_effect=setting),
                        patch.object(web, "_miniapp_user", AsyncMock(side_effect=lambda request: self.user)),
                        patch.object(web, "get_subscription_profile", AsyncMock(side_effect=lambda pid: self.profile)),
                        patch.object(web, "subscription_url", AsyncMock(side_effect=lambda token: "https://example.test/sub/" + token))]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.client.aclose()

    async def test_repeated_requests_use_current_link_and_are_not_cached(self):
        for token in ["current", "rotated"]:
            self.profile["token"] = token
            response = await self.client.post("/app/api/services/qr", json={"profile_id": 9})
            self.assertEqual(200, response.status_code)
            self.assertIn("no-store", response.headers["cache-control"])
            data = response.json()
            self.assertEqual("https://example.test/sub/" + token, data["sub_url"])
            image = Image.open(BytesIO(base64.b64decode(data["image"].split(",", 1)[1])))
            self.assertEqual("PNG", image.format)

    async def test_ownership_auth_block_and_malformed_input_are_checked(self):
        self.profile["user_id"] = 8
        self.assertEqual(404, (await self.client.post("/app/api/services/qr", json={"profile_id": 9})).status_code)
        self.user = None
        self.assertEqual(401, (await self.client.post("/app/api/services/qr", json={"profile_id": 9})).status_code)
        self.user = {"id": 7, "is_blocked": 1}
        self.assertEqual(403, (await self.client.post("/app/api/services/qr", json={"profile_id": 9})).status_code)
        self.user = {"id": 7}
        self.assertEqual(400, (await self.client.post("/app/api/services/qr", json={"profile_id": "bad"})).status_code)

    async def test_bot_uses_ownership_guard_before_sending_any_qr(self):
        cb = SimpleNamespace(data="sub_qr:9", from_user=SimpleNamespace(id=70, username="u", full_name="U"),
                             answer=AsyncMock(), message=SimpleNamespace(answer_photo=AsyncMock(), answer=AsyncMock()))
        with patch.object(bot_user, "_ensure_channel_membership", AsyncMock(return_value=True)), \
             patch.object(bot_user, "get_or_create_user", AsyncMock(return_value={"id": 7})), \
             patch.object(bot_user, "get_subscription_profile", AsyncMock(return_value={"id": 9, "user_id": 8})), \
             patch.object(bot_user, "subscription_url", AsyncMock()) as url:
            await bot_user.sub_qr(cb)
        cb.message.answer_photo.assert_not_awaited()
        url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
