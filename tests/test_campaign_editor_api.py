"""The admin editor preserves saved images and previews only authenticated media."""
import base64
import importlib
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from PIL import Image
web = importlib.import_module("web.app")


class CampaignEditorApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="https://test")
        self.url = "/" + web.S + "/api/campaigns/custom"
        image = BytesIO()
        Image.new("RGB", (100, 100), "blue").save(image, "PNG")
        self.photo = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_text_only_edit_preserves_image_but_explicit_removal_clears_it(self):
        saved = AsyncMock(return_value=1)
        with patch.object(web, "_api_guard", return_value=True), \
             patch.object(web, "get_custom_campaign", AsyncMock(return_value={"photo": self.photo})), \
             patch.object(web, "save_custom_campaign", saved):
            for body, expected in [({"id": 1, "title": "Edited"}, self.photo),
                                   ({"id": 1, "title": "Edited", "photo": ""}, "")]:
                response = await self.client.post(self.url, json=body)
                self.assertEqual(200, response.status_code)
                self.assertEqual(expected, saved.await_args.args[0]["photo"])

    async def test_bad_image_is_rejected_before_save(self):
        saved = AsyncMock()
        with patch.object(web, "_api_guard", return_value=True), patch.object(web, "save_custom_campaign", saved):
            response = await self.client.post(self.url, json={"title": "Campaign", "photo": "data:image/png;base64,bm90IGFuIGltYWdl"})
        self.assertEqual(400, response.status_code)
        saved.assert_not_awaited()

    async def test_persisted_media_preview_is_private_and_requires_admin(self):
        with patch.object(web, "get_custom_campaign", AsyncMock(return_value={"photo": self.photo})), \
             patch.object(web, "_api_guard", return_value=False):
            self.assertEqual(401, (await self.client.get(self.url + "/1/photo")).status_code)
        with patch.object(web, "get_custom_campaign", AsyncMock(return_value={"photo": self.photo})), \
             patch.object(web, "_api_guard", return_value=True):
            response = await self.client.get(self.url + "/1/photo")
        self.assertEqual("image/jpeg", response.headers["content-type"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual("JPEG", Image.open(BytesIO(response.content)).format)


if __name__ == "__main__":
    unittest.main()
