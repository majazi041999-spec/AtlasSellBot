"""Campaign edits use recorded message IDs and never resend announcements."""
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('broadcast_tool', ROOT/'tools/broadcast.py')
broadcast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broadcast)


class BroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_records_id_then_repeated_edit_does_not_resend(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = str(Path(folder)/'test.db')
            body_path = Path(folder)/'body.html'
            body_path.write_text('Original', encoding='utf-8')
            db = sqlite3.connect(db_path)
            db.execute('CREATE TABLE users(telegram_id INTEGER)')
            db.execute('INSERT INTO users VALUES(123)')
            db.commit()
            bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=456)),
                                  edit_message_text=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
            with patch.object(broadcast, 'DB', db_path), patch.object(broadcast, 'Bot', return_value=bot), \
                 patch.object(broadcast, 'DELAY', 0), patch.object(sys, 'argv', ['broadcast.py', 'campaign', '--html-file', str(body_path)]):
                await broadcast.main()
                self.assertEqual(db.execute('SELECT message_id FROM broadcast_messages').fetchone()[0], 456)
                body_path.write_text('Revised', encoding='utf-8')
                with patch.object(sys, 'argv', sys.argv+['--edit']):
                    await broadcast.main()
                    await broadcast.main()
                bot.send_message.assert_awaited_once()
                bot.edit_message_text.assert_awaited_once()
                self.assertEqual(bot.edit_message_text.await_args.kwargs['message_id'], 456)
                self.assertEqual(bot.edit_message_text.await_args.kwargs['text'], 'Revised')
            db.close()


if __name__ == '__main__':
    unittest.main()
