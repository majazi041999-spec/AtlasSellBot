"""Publish the authorized native countdown once; save a private delivery receipt."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

import urllib.error
import urllib.request

ROOT = Path('/opt/AtlasSellBot')
STAGE = Path('/root/atlas-announcements')
CAMPAIGN = 'price-countdown-20261007'
DEADLINE = 1791361800  # 2026-10-07 12:00 Asia/Tehran
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from core.config import BOT_TOKEN


def main():
    STAGE.mkdir(mode=0o700, exist_ok=True)
    source = STAGE / (CAMPAIGN + '.html')
    receipt_path = STAGE / (CAMPAIGN + '.json')
    body = source.read_text(encoding='utf-8').strip()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}

    def save():
        tmp = receipt_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.chmod(0o600)
        tmp.replace(receipt_path)

    if receipt.get('source_sha256'):
        assert receipt['source_sha256'] == digest, 'Published content changed; edit separately'
    if receipt.get('message_id'):
        print(json.dumps({'already_published': True, 'url': receipt['url'],
                          'native_date_entity_verified': receipt.get('native_date_entity_verified', False)}))
        return
    assert not receipt.get('dispatch_started'), 'Unknown earlier send outcome: inspect channel before retrying'
    assert datetime.datetime.now(datetime.timezone.utc).timestamp() < DEADLINE, 'Deadline has passed'
    match = re.search(r'<tg-time unix="(\d+)" format="r">([^<]+)</tg-time>', body)
    assert match and int(match[1]) == DEADLINE, 'Incorrect native countdown'
    assert len(match[2].encode('utf-16-le')) // 2 <= 31, 'Countdown fallback is too long'
    with sqlite3.connect(ROOT / 'atlas.db') as db:
        row = db.execute("SELECT value FROM settings WHERE key='channel_username'").fetchone()
    assert row, 'Channel is not configured'
    channel = row[0].strip().lstrip('@')
    assert re.fullmatch(r'[A-Za-z0-9_]+', channel), 'Unexpected channel setting'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(method, payload):
        try:
            request = urllib.request.Request(
                'https://api.telegram.org/bot' + BOT_TOKEN + '/' + method,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
            )
            try:
                with opener.open(request, timeout=30) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as response:
                with response:
                    data = json.load(response)
        except Exception:
            raise RuntimeError('Telegram request failed; token and URL omitted') from None
        if not data.get('ok'):
            error = str(data.get('description', 'unknown Telegram error')).replace(BOT_TOKEN, '<redacted>')
            raise RuntimeError(method + ': ' + error)
        return data['result']

    me = api('getMe', {})
    chat = api('getChat', {'chat_id': '@' + channel})
    member = api('getChatMember', {'chat_id': chat['id'], 'user_id': me['id']})
    assert member['status'] == 'creator' or (
        member['status'] == 'administrator' and member.get('can_post_messages')
    ), 'Bot cannot publish in configured channel'
    username = me['username']
    assert re.fullmatch(r'[A-Za-z0-9_]+', username)
    markup = {'inline_keyboard': [[{'text': '🛒 خرید و تمدید با قیمت فعلی',
                                   'url': 'https://t.me/' + username}]]}
    receipt.update(source_sha256=digest, dispatch_started=True, deadline=DEADLINE,
                   channel_id=chat['id'])
    save()
    sent = api('sendMessage', {'chat_id': chat['id'], 'text': body, 'parse_mode': 'HTML',
                              'reply_markup': markup, 'link_preview_options': {'is_disabled': True}})
    receipt.update(message_id=sent['message_id'],
                   url='https://t.me/' + channel + '/' + str(sent['message_id']),
                   native_date_entity_verified=any(
                       e.get('type') == 'date_time' and e.get('unix_time') == DEADLINE
                       and e.get('date_time_format') == 'r' for e in sent.get('entities', [])
                   ))
    save()
    assert receipt['native_date_entity_verified'], 'Message sent, but native date entity was not returned'
    print(json.dumps({'url': receipt['url'], 'native_date_entity_verified': True,
                      'deadline_tehran': '2026-10-07 12:00', 'bot_button': username}))


if __name__ == '__main__':
    main()
