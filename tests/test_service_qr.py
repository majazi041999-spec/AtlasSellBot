"""Every subscription card must offer QR again after initial delivery."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.keyboards import subscription_detail_kb


class ServiceQRKeyboardTests(unittest.TestCase):
    def test_existing_subscription_has_repeatable_qr_action(self):
        kb = subscription_detail_kb(7, "https://example.test/sub/owned")
        actions = [button.callback_data for row in kb.inline_keyboard for button in row]
        self.assertIn("sub_qr:7", actions)


if __name__ == "__main__":
    unittest.main()
