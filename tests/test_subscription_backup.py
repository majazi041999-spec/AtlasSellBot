"""A recovery URL must stay independent when importing from its browser page."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import multi_subscription as multi
from web import app as web
from bot.keyboards import subscription_detail_kb


class BackupTests(unittest.IsolatedAsyncioTestCase):
    async def test_backup_keeps_same_token_and_does_not_change_primary(self):
        async def setting(key, default=''):
            return {'public_base_url': 'https://primary.example',
                    'subscription_backup_base_url': 'https://backup.example:8444'}.get(key, default)
        with patch.object(multi, 'get_setting', setting):
            self.assertEqual(await multi.subscription_url('test'), 'https://primary.example/sub/test')
            self.assertEqual(await multi.subscription_backup_url('test'), 'https://backup.example:8444/sub/test')
        for invalid in ('http://backup.example', 'https://user:pass@backup.example',
                        'https://backup.example?token=test', 'https://backup.example/sub/other'):
            with patch.object(multi, 'get_setting', AsyncMock(return_value=invalid)):
                self.assertEqual(await multi.subscription_backup_url('test'), '')

    async def test_backup_browser_imports_backup_instead_of_unreachable_primary(self):
        profile = dict(id=1, is_active=1, traffic_gb=1)
        with patch.object(web, '_get_sub_profile_by_token', AsyncMock(return_value=profile)), \
             patch.object(web, 'subscription_url', AsyncMock(return_value='https://primary.example/sub/test')), \
             patch.object(web, 'subscription_backup_url', AsyncMock(return_value='https://backup.example:8444/sub/test')), \
             patch.object(web, '_render_sub_status_html', AsyncMock(return_value='page')) as render:
            for forwarded, expected in [('backup.example:8444', 'https://backup.example:8444/sub/test'),
                                        ('evil.example', 'https://primary.example/sub/test')]:
                request = Request({'type': 'http', 'scheme': 'https', 'method': 'GET',
                                   'path': '/sub/test', 'query_string': b'html=1',
                                   'headers': [(b'host', b'primary.example'),
                                               (b'x-forwarded-host', forwarded.encode())]})
                await web.public_subscription('test', request)
                self.assertEqual(render.await_args.kwargs['page_url'], expected)

    def test_service_card_offers_copyable_backup(self):
        backup = 'https://backup.example:8444/sub/test'
        kb = subscription_detail_kb(1, 'https://primary.example/sub/test', backup_url=backup)
        copies = [b.copy_text.text for row in kb.inline_keyboard for b in row if b.copy_text]
        self.assertIn(backup, copies)


if __name__ == '__main__':
    unittest.main()
