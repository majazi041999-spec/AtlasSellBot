"""A browser view of the *published* subscription, never the raw node cache."""
import base64
import html
import hashlib
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from string import Template
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

_ASSETS = Path(__file__).with_name('subscription_assets')
_PAGE = Template((_ASSETS / 'page.html').read_text(encoding='utf-8'))
_CSS = (_ASSETS / 'page.css').read_text(encoding='utf-8')
_JS = (_ASSETS / 'page.js').read_text(encoding='utf-8')
DEFAULT_LOGO_URL = '/subscription-assets/atlas-logo.webp?v=' + hashlib.sha256((_ASSETS / 'atlas-logo.webp').read_bytes()).hexdigest()[:12]


def telegram_contacts(bot: str, channel: str, tutorial: str, support: str) -> list[dict]:
    """Accept public Telegram usernames, never arbitrary URLs from settings."""
    contacts = []
    for label, username in [('ربات و تمدید', bot), ('کانال اطلاع‌رسانی', channel), ('آموزش اتصال', tutorial), ('پشتیبانی', support)]:
        username = str(username or '').strip().lstrip('@')
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', username):
            contacts.append(dict(label=label, username=username, href='https://t.me/' + username))
    return contacts


def published_nodes(body: str) -> list[tuple[str, str]]:
    """Preserve published URI bytes/order; omit only our synthetic status entries."""
    nodes = []
    for link in base64.b64decode(body).decode('utf-8').splitlines():
        parts = urlsplit(link)
        if parts.scheme == 'vless' and parts.hostname == '127.0.0.1' and parts.port == 1:
            continue
        label = unquote(parts.fragment)
        if parts.scheme == 'vmess' and not label:
            try:
                payload = link.split('://', 1)[1]
                label = json.loads(base64.b64decode(payload + '=' * (-len(payload) % 4))).get('ps', '')
            except (ValueError, TypeError):
                pass
        nodes.append((str(label or f'سرور {len(nodes) + 1}'), link))
    return nodes


def config_url(url: str) -> str:
    """Force machine content even when an app fetches using a browser User-Agent."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ('html', 'config')]
    return urlunsplit(parts._replace(query=urlencode(query + [('config', '1')]), fragment=''))


def import_apps(url: str, name: str) -> list[dict]:
    # Sources/encoding contracts: docs/subscription-browser-page.md.
    encoded, title = quote(url, safe=''), quote(name, safe='')
    return [
        dict(name='V2Box', platforms='android ios', letter='V', color='blue', href=f'v2box://install-sub?url={encoded}&name={title}'),
        dict(name='Happ', platforms='android ios', letter='H', color='green', href=f'happ://add/{url}'),
        dict(name='v2rayNG', platforms='android', letter='NG', color='orange', href=f'v2rayng://install-config?url={encoded}#{title}'),
        dict(name='Streisand', platforms='ios', letter='S', color='purple', href=f'streisand://import/{encoded}'),
    ]


def _bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if amount < 1024 or unit == 'TB':
            return f'{amount:.2f} {unit}'
        amount /= 1024


def render_page(profile: dict, rendered: tuple | None, sub_url: str, brand: str, logo: str, contacts: list[dict] | None = None) -> str:
    body, info = rendered or ('', {})
    used = int(info.get('download', profile.get('used_bytes') or 0)) + int(info.get('upload', 0))
    total = int(info.get('total', float(profile.get('traffic_gb') or 0) * 1024**3))
    expire = int(info.get('expire', int(profile.get('expire_timestamp') or 0) // 1000))
    now = time.time()
    inactive = not int(profile.get('is_active') or 0)
    expired = expire > 0 and expire <= now
    depleted = total > 0 and used >= total
    unavailable = inactive or expired or depleted
    nodes = [] if unavailable else published_nodes(body)
    status = 'غیرفعال' if inactive else 'زمان سرویس تمام شده' if expired else 'حجم سرویس تمام شده' if depleted else 'اشتراک فعال'
    days = 'نامحدود' if expire <= 0 else 'به پایان رسیده' if expired else 'کمتر از یک روز' if expire - now < 86400 else f'{math.ceil((expire - now) / 86400)} روز'
    safe = lambda value: html.escape(str(value), quote=True)
    machine_url = config_url(sub_url)
    app_rows = ''.join(
        f'<a class="app-link" data-platforms="{app["platforms"]}" href="{safe(app["href"])}" aria-label="افزودن اشتراک به {safe(app["name"])}">'
        f'<span class="app-icon {app["color"]}" aria-hidden="true">{app["letter"]}</span>'
        f'<span><b dir="ltr">{app["name"]}</b><small>افزودن اشتراک</small></span><span class="open-arrow" aria-hidden="true">↗</span></a>'
        for app in import_apps(machine_url, str(profile.get('name') or brand))
    ) if not unavailable else '<p class="muted">برای افزودن سرورها، ابتدا سرویس را از ربات تمدید کنید.</p>'
    node_rows = ''.join(
        f'<div class="node"><span class="node-number" aria-hidden="true">{i:02d}</span>'
        f'<span class="node-name"><b dir="auto">{safe(label)}</b><small>کپی و افزودن دستی</small></span>'
        f'<button class="copy-btn secondary" type="button" data-link="{safe(link)}">کپی لینک</button></div>'
        for i, (label, link) in enumerate(nodes, 1)
    ) or '<p class="empty">در حال حاضر سروری برای نمایش موجود نیست. وضعیت سرویس را از ربات بررسی کنید.</p>'
    logo_html = f'<img src="{safe(logo)}" alt="" referrerpolicy="no-referrer">' if logo else '<span aria-hidden="true">◈</span>'
    contact_rows = ''.join(
        f'<a href="{safe(contact["href"])}" target="_blank" rel="noopener noreferrer">'
        f'<span>{safe(contact["label"])}</span><b dir="ltr">@{safe(contact["username"])}</b><i aria-hidden="true">↗</i></a>'
        for contact in contacts or []
    )
    return _PAGE.substitute(
        css=_CSS, js=_JS, brand=safe(brand), service_name=safe(profile.get('name') or 'اشتراک شما'),
        logo=logo_html, status=safe(status), status_class='ended' if unavailable else 'active',
        banner='<div class="banner">سرویس شما غیرفعال یا تمام شده است. برای ادامه، از داخل ربات تمدید کنید.</div>' if unavailable else '',
        used=safe(_bytes(used)), total=safe(_bytes(total) if total > 0 else 'نامحدود'),
        remaining=safe(_bytes(max(0, total - used)) if total > 0 else 'نامحدود'), days=safe(days),
        date=safe(datetime.fromtimestamp(expire).strftime('%Y-%m-%d') if expire > 0 else 'نامحدود'),
        pct=min(100, max(0, round(used * 100 / total))) if total > 0 else 0,
        node_count=len(nodes), sub_url=safe(machine_url), apps=app_rows, nodes=node_rows,
        contacts=f'<nav class="contact-links" aria-label="ارتباط در تلگرام">{contact_rows}</nav>' if contact_rows else '',
    )
