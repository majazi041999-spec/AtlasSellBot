"""Send the authorized subscription guide once, with verified premium emojis."""
import asyncio
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path('/opt/AtlasSellBot')
STAGE = Path('/root/atlas-announcements')
CAMPAIGN = 'atlas-sub-refresh-guide-20261005'
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from bot.keyboards import _inline_button
from aiogram.types import InlineKeyboardMarkup
from core.config import ADMIN_IDS, BOT_TOKEN


async def main():
    source = STAGE / 'sub-refresh-guide-20261005.html'
    receipt_path = STAGE / (CAMPAIGN + '.json')
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}

    def save():
        temp = receipt_path.with_suffix('.tmp')
        temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        temp.chmod(0o600)
        temp.replace(receipt_path)

    body = source.read_text(encoding='utf-8').strip()
    assert len(body) < 4096
    digest = hashlib.sha256(body.encode()).hexdigest()
    if receipt.get('sha256'):
        assert receipt['sha256'] == digest, 'Campaign content changed; inspect before resending'
    db = sqlite3.connect(ROOT / 'atlas.db', timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS broadcast_log (campaign TEXT NOT NULL, telegram_id INTEGER NOT NULL, status TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(campaign,telegram_id))')
    db.commit()
    row = db.execute("select value from settings where key='owner_admin_id'").fetchone()
    owner = int((row[0] if row else '0') or 0)
    if not owner:
        assert len(ADMIN_IDS) == 1, 'Owner is ambiguous'
        owner = ADMIN_IDS[0]
    if not receipt.get('emoji_verified'):
        assert not db.execute('select 1 from broadcast_log where campaign=? and telegram_id=?', (CAMPAIGN, owner)).fetchone(), 'Inspect existing owner delivery before retry'
        bot = Bot(BOT_TOKEN)
        try:
            ids = list(dict.fromkeys(re.findall(r'emoji-id="(\d+)"', body)))
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=ids)
            alts = {s.custom_emoji_id: s.emoji for s in stickers if s.emoji}
            assert all(eid in alts for eid in ids)
            body = re.sub(r'<tg-emoji emoji-id="(\d+)">.*?</tg-emoji>', lambda m: f'<tg-emoji emoji-id="{m[1]}">{html.escape(alts[m[1]])}</tg-emoji>', body)
            source.write_text(body + '\n', encoding='utf-8')
            markup = InlineKeyboardMarkup(inline_keyboard=[[_inline_button('📱 سرویس‌های من / دریافت لینک ساب', callback_data='home:status', style='success')]])
            sent = await bot.send_message(owner, body, parse_mode='HTML', reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=True))
            count = sum(e.type == 'custom_emoji' for e in sent.entities or [])
            assert count == 4, 'Premium emoji verification failed; broadcast was not started'
            with db:
                db.execute('insert into broadcast_log values(?,?,?,?)', (CAMPAIGN, owner, 'sent', int(time.time())))
            receipt.update(emoji_verified=True, custom_emoji_count=count, owner_message_id=sent.message_id, sha256=hashlib.sha256(body.encode()).hexdigest())
            save()
        finally:
            await bot.session.close()
    if not receipt.get('broadcast_started'):
        command = ['systemd-run', '--unit=atlas-sub-refresh-guide-20261005', '--property=WorkingDirectory=' + str(ROOT), str(ROOT / '.venv/bin/python'), str(ROOT / 'tools/broadcast.py'), CAMPAIGN, '--html-file', str(source), '--button', '📱 سرویس‌های من / دریافت لینک ساب|home:status|success']
        run = subprocess.run(command, capture_output=True, text=True)
        assert run.returncode == 0, 'Broadcast dispatch failed; receipts retained'
        receipt['broadcast_started'] = True
        save()
    db.close()
    print(json.dumps({'campaign': CAMPAIGN, 'premium_emojis': receipt['custom_emoji_count'], 'broadcast_started': receipt['broadcast_started']}))


asyncio.run(main())
