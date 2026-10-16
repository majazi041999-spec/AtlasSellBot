"""Saved campaign media must reach delivery, including automated followups."""
import base64
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from core import campaigns
from core.campaign_media import campaign_photo_bytes, send_campaign_message


def photo_uri():
    out = BytesIO()
    Image.new("RGB", (100, 100), "blue").save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


class CampaignMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_emoji_caption_is_split_without_losing_photo(self):
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        await send_campaign_message(bot, 70, "🎁" * 600, campaign_photo_bytes(photo_uri()))
        bot.send_photo.assert_awaited_once()
        self.assertNotIn("caption", bot.send_photo.await_args.kwargs)
        bot.send_message.assert_awaited_once()

    async def test_bad_saved_photo_never_silently_degrades_to_text(self):
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        with self.assertRaises(ValueError), patch.object(campaigns, "get_setting", AsyncMock(return_value="Atlas")):
            await campaigns.run_custom_campaign(bot, {"slug": "bad", "message": "hello", "photo": "data:image/png;base64,not-an-image"})
        bot.send_message.assert_not_awaited()

    async def test_unsuccessful_automatic_delivery_is_not_marked_sent(self):
        async def setting(key, default=""):
            return {"campaign_winback_code": "WELCOME"}.get(key, default)
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock(side_effect=RuntimeError("temporary")))
        mark, event = AsyncMock(), AsyncMock()
        with patch.object(campaigns, "get_setting", side_effect=setting), \
             patch.object(campaigns, "get_lapsed_users_for_winback", AsyncMock(return_value=[{"id": 7, "telegram_id": 70}])), \
             patch.object(campaigns, "mark_winback_sent", mark), patch.object(campaigns, "log_campaign_event", event):
            self.assertEqual(0, (await campaigns.run_winback(bot))["sent"])
        mark.assert_not_awaited()
        event.assert_not_awaited()

    async def test_referral_preview_tracks_changed_rewards(self):
        from core import rewards
        tiers = [{"referrals_needed": 1, "reward_kind": "wallet", "reward_amount": 30000}]
        async def setting(key, default=""):
            return {"referral_enabled": "1", "ui.brand_name": "Atlas"}.get(key, default)
        with patch.object(campaigns, "get_setting", side_effect=setting), \
             patch.object(rewards, "referral_per_referral_amount", AsyncMock(return_value=15000)), \
             patch.object(rewards, "referral_per_referral_gb", AsyncMock(return_value=0)), \
             patch.object(campaigns, "get_referral_tiers", AsyncMock(side_effect=lambda **kw: tiers)):
            first = await campaigns.campaign_preview({"message": "{referral_rewards}"})
            self.assertIn("15,000", first)
            self.assertIn("30,000", first)
            tiers[0]["reward_amount"] = 45000
            second = await campaigns.campaign_preview({"message": "{referral_rewards}"})
            self.assertIn("45,000", second)
            self.assertNotIn("30,000", second)

    async def test_automated_winback_delivers_configured_photo(self):
        settings = {"campaign_winback_enabled": "1", "campaign_winback_code": "WELCOME",
                    "campaign_winback_photo": photo_uri()}
        async def setting(key, default=""):
            return settings.get(key, default)
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        with patch.object(campaigns, "get_setting", side_effect=setting), \
             patch.object(campaigns, "get_lapsed_users_for_winback", AsyncMock(return_value=[{"id": 7, "telegram_id": 70}])), \
             patch.object(campaigns, "mark_winback_sent", AsyncMock()), \
             patch.object(campaigns, "log_campaign_event", AsyncMock()), \
             patch.object(campaigns.asyncio, "sleep", AsyncMock()):
            self.assertEqual(1, (await campaigns.run_winback(bot))["sent"])
        bot.send_photo.assert_awaited_once()
        bot.send_message.assert_not_awaited()

    async def test_uploaded_photo_is_used_by_custom_sender(self):
        bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        with patch.object(campaigns, "get_setting", AsyncMock(return_value="Atlas")), \
             patch.object(campaigns, "get_segment_users", AsyncMock(return_value=[{"id": 7, "telegram_id": 70}])), \
             patch.object(campaigns, "user_has_campaign_event", AsyncMock(return_value=False)), \
             patch.object(campaigns, "log_campaign_event", AsyncMock()), \
             patch.object(campaigns, "mark_custom_campaign_sent", AsyncMock()), \
             patch.object(campaigns.asyncio, "sleep", AsyncMock()):
            self.assertEqual(1, (await campaigns.run_custom_campaign(bot, {
                "slug": "photo-test", "message": "Hello {name}", "photo": photo_uri()
            }))["sent"])
        bot.send_photo.assert_awaited_once()
        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
