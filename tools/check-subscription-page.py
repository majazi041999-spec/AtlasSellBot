"""Optional Playwright smoke test with synthetic subscription data only.

Run: python tools/check-subscription-page.py --screenshots <directory>
Requires Playwright and its Chromium browser; not a production dependency.
"""
import argparse
import base64
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from web.subscription_page import render_page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    labels = ['🇺🇸 USA New', '🇩🇪 Germany WS 🛡️', '🇳🇱 Netherland WS 🛡️ | Plus', '🇹🇷 Turkey WS 🛡️ | Backup 1']
    from urllib.parse import quote
    links = [f'vless://11111111-1111-4111-8111-111111111111@edge.example:443?type=ws&security=tls&host=origin.example&path=%2F%3Fed%3D2560&ech=trws.anacotig.com%2Bhttps%3A%2F%2F8.8.8.8%2Fdns-query#{quote(label)}' for label in labels]
    fixture = render_page(dict(is_active=1, name='اشتراک شخصی'),
                          (base64.b64encode('\n'.join(links).encode()).decode(), dict(download=9*1024**3, total=50*1024**3, expire=int(time.time()+13*86400))),
                          'https://sub.example/sub/demo', 'Atlas Account', '')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (320, 390, 940, 1280):
            for os in ('android', 'ios') if width == 390 else ('android',):
                context = browser.new_context(viewport={'width':width, 'height':900}, user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' if os == 'ios' else 'Mozilla/5.0 (Linux; Android 15)')
                context.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedText=text}}});")
                page = context.new_page()
                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                requests = []; page.on('request', lambda request: requests.append(request.url))
                page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=fixture))
                page.goto('http://localhost/sub/demo')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}'
                assert [node.get_attribute('data-link') for node in page.locator('button[data-link]').all()] == links
                assert page.locator('.app-link:visible').count() == 3
                assert page.locator('#tab-'+os).get_attribute('aria-selected') == 'true'
                for node, link in zip(page.locator('button[data-link]').all(), links):
                    node.click(); page.wait_for_function('window.copiedText !== undefined')
                    assert page.evaluate('window.copiedText') == link
                page.locator('#copy-sub').click()
                assert page.evaluate('window.copiedText') == 'https://sub.example/sub/demo?config=1'
                for app in page.locator('.app-link').all():
                    href = app.get_attribute('href')
                    if href.startswith(('v2box:', 'v2rayng:')):
                        assert parse_qs(urlsplit(href).query)['url'] == ['https://sub.example/sub/demo?config=1']
                assert requests == ['http://localhost/sub/demo'], 'Unexpected external asset request'
                assert not errors, errors
                if args.screenshots:
                    args.screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(args.screenshots / f'page-{width}-{os}.png'), full_page=True)
                # Clipboard rejection must never display false success.
                page.evaluate("navigator.clipboard.writeText=async()=>{throw Error('denied')}; document.execCommand=()=>false;")
                page.locator('#toast').evaluate('(el)=>el.hidden=true')
                page.locator('button[data-link]').first.click()
                assert page.locator('#manual-copy').is_visible()
                assert page.locator('#manual-copy textarea').input_value() == links[0]
                assert page.locator('#toast').is_hidden()
                assert page.locator('#manual-copy textarea').evaluate('(el)=>document.activeElement===el')
                page.locator('#manual-copy button').click()
                # Legacy browsers' successful execCommand remains supported.
                page.evaluate("document.execCommand=()=>true")
                page.locator('button[data-link]').last.click()
                assert page.locator('#toast').is_visible()
                assert not errors, errors
                context.close()
                print(f'PASS {width}px {os}: exact copy, platform tabs, import URLs, clipboard fallbacks, no overflow or external requests')
        browser.close()


if __name__ == '__main__':
    main()
