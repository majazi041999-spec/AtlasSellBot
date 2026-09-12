"""Launch-fragment transport never bypasses server signature or expiry checks."""
import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import miniapp


class AuthTests(unittest.TestCase):
    def test_signed_launch_transport_and_expiry(self):
        token = '123456789:test-only-bot-token-not-a-real-secret'
        now = 1800000000
        def signed(auth_date):
            fields = {'auth_date': str(auth_date), 'user': json.dumps({'id': 123, 'first_name': 'A+B'})}
            key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
            message = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
            fields['hash'] = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
            return urlencode(fields)
        with patch.object(miniapp, 'BOT_TOKEN', token), patch.object(miniapp.time, 'time', return_value=now):
            self.assertTrue(miniapp.check_init_data(signed(now))['ok'])
            self.assertEqual(miniapp.check_init_data(signed(now).replace('123', '124'))['reason'], 'bad_hash')
            self.assertEqual(miniapp.check_init_data(signed(now-miniapp.MAX_INIT_DATA_AGE-1))['reason'], 'expired')
            self.assertEqual(miniapp.check_init_data('')['reason'], 'no_data')


if __name__ == '__main__':
    unittest.main()
