"""Send the authorized recommendation once, using verified premium emojis."""
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
CAMPAIGN = 'atlas-server-status-20261006'
BUTTONS = ['📊 وضعیت سرورها|home:load|primary',
           '🔄 سرویس‌های من / لینک ساب|home:status|success']
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards import _button
from bot.rich_message import premiumize
from core.config import ADMIN_IDS, BOT_TOKEN


async def main():
    source = STAGE / 'server-status-20261006.html'
    delivery = STAGE / 'server-status-20261006-premium.html'
    receipt_path = STAGE / (CAMPAIGN + '.json')
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if receipt.get('source_sha256'):
        assert receipt['source_sha256'] == digest, 'Campaign content changed'

    def save():
        temp = receipt_path.with_suffix('.tmp')
        temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        temp.chmod(0o600)
        temp.replace(receipt_path)

    db = sqlite3.connect(ROOT / 'atlas.db', timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS broadcast_log (campaign TEXT NOT NULL, telegram_id INTEGER NOT NULL, status TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(campaign,telegram_id))')
    db.commit()
    public = db.execute("SELECT value FROM settings WHERE key='server_load_public'").fetchone()
    assert public and public[0] == '1', 'Customer status screen is disabled'
    row = db.execute("SELECT value FROM settings WHERE key='owner_admin_id'").fetchone()
    owner = int((row[0] if row else '0') or 0)
    if not owner:
        assert len(ADMIN_IDS) == 1, 'Owner is ambiguous'
        owner = ADMIN_IDS[0]
    if not receipt.get('owner_message_id'):
        body = premiumize(source.read_text(encoding='utf-8').strip())
        assert len(body) < 4096
        bot = Bot(BOT_TOKEN)
        try:
            ids = list(dict.fromkeys(re.findall(r'emoji-id="(\d+)"', body)))
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=ids)
            alts = {s.custom_emoji_id:s.emoji for s in stickers if s.emoji}
            assert all(eid in alts for eid in ids)
            body = re.sub(r'<tg-emoji emoji-id="(\d+)">.*?</tg-emoji>', lambda m:f'<tg-emoji emoji-id="{m[1]}">{html.escape(alts[m[1]])}</tg-emoji>', body)
            delivery.write_text(body+'\n', encoding='utf-8')
            keyboard = InlineKeyboardBuilder()
            for spec in BUTTONS:
                label, data, style = spec.split('|')
                _button(keyboard, text=label, callback_data=data, style=style)
            keyboard.adjust(1)
            sent = await bot.send_message(owner, body, parse_mode='HTML', reply_markup=keyboard.as_markup(), link_preview_options=LinkPreviewOptions(is_disabled=True))
            count = sum(e.type == 'custom_emoji' for e in sent.entities or [])
            with db:
                db.execute('INSERT OR REPLACE INTO broadcast_log VALUES(?,?,?,?)', (CAMPAIGN, owner, 'sent', int(time.time())))
            receipt.update(source_sha256=digest, owner_message_id=sent.message_id,
                           custom_emoji_count=count, expected_emoji_count=body.count('<tg-emoji'),
                           button_icons_verified=all(b.icon_custom_emoji_id for r in sent.reply_markup.inline_keyboard for b in r))
            save()
        finally:
            await bot.session.close()
    assert receipt['custom_emoji_count'] == receipt['expected_emoji_count'] == 6, 'Premium emoji delivery verification failed'
    assert receipt['button_icons_verified'], 'Premium button icons missing'
    if not receipt.get('broadcast_started'):
        command = ['systemd-run', '--unit='+CAMPAIGN, '--property=WorkingDirectory='+str(ROOT), str(ROOT/'.venv/bin/python'), str(ROOT/'tools/broadcast.py'), CAMPAIGN, '--html-file', str(delivery)]
        for spec in BUTTONS:
            command.extend(['--button', spec])
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, 'Broadcast dispatch failed; receipts retained'
        receipt['broadcast_started'] = True
        save()
    db.close()
    print(json.dumps({'campaign':CAMPAIGN, 'custom_emojis':receipt['custom_emoji_count'],
                      'premium_button_icons':receipt['button_icons_verified'],
                      'broadcast_started':receipt['broadcast_started']}))


asyncio.run(main())
