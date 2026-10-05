"""Send four copyable premium messages only to the owner, once per receipt."""
import asyncio, hashlib, html, json, os
from pathlib import Path
import re, sqlite3, sys
ROOT=Path('/opt/AtlasSellBot');STAGE=Path('/root/atlas-announcements')
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from core.config import ADMIN_IDS,BOT_TOKEN

async def main():
    texts=json.loads((STAGE/'android-video-captions-20261005.json').read_text(encoding='utf-8'))
    assert len(texts)==4 and all(len(text)<4096 for text in texts)
    path=STAGE/'android-video-captions-20261005-receipt.json'
    receipt=json.loads(path.read_text()) if path.exists() else {'messages':{}}
    db=sqlite3.connect(ROOT/'atlas.db')
    row=db.execute("select value from settings where key='owner_admin_id'").fetchone();db.close()
    owner=int((row[0] if row else '0') or 0)
    if not owner:
        assert len(ADMIN_IDS)==1,'Owner is ambiguous'
        owner=ADMIN_IDS[0]
    bot=Bot(BOT_TOKEN)
    try:
        ids=list(dict.fromkeys(re.findall(r'emoji-id="(\d+)"',''.join(texts))))
        stickers=await bot.get_custom_emoji_stickers(custom_emoji_ids=ids)
        alts={s.custom_emoji_id:s.emoji for s in stickers if s.emoji}
        assert all(eid in alts for eid in ids)
        for index,original in enumerate(texts):
            digest=hashlib.sha256(original.encode()).hexdigest()
            if str(index) in receipt['messages']:
                assert receipt['messages'][str(index)]['sha256']==digest,'Previously sent caption changed'
                continue
            text=re.sub(r'<tg-emoji emoji-id="(\d+)">.*?</tg-emoji>',lambda m:f'<tg-emoji emoji-id="{m[1]}">{html.escape(alts[m[1]])}</tg-emoji>',original)
            sent=await bot.send_message(owner,text,parse_mode='HTML',link_preview_options=LinkPreviewOptions(is_disabled=True))
            count=sum(e.type=='custom_emoji' for e in sent.entities or [])
            receipt['messages'][str(index)]={'message_id':sent.message_id,'custom_emojis':count,'sha256':digest}
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(receipt,indent=2));tmp.chmod(0o600);tmp.replace(path)
            assert count==len(re.findall(r'<tg-emoji',text)),'Premium emoji entity missing'
    finally:
        await bot.session.close()
    print(json.dumps({'owner_only':True,'messages':len(receipt['messages']),'premium_verified':all(v['custom_emojis']>0 for v in receipt['messages'].values()),'broadcast':False}))

asyncio.run(main())
