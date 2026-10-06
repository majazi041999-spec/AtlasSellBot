# Subscription browser page

The HTML `/sub/{token}` page previously copied raw `subscription_nodes.link`
values. App responses went through `render_subscription`, applying connect-host
overrides, WS tuning, published variants, deduplication, relay dependencies and
server/node enable switches. The two paths therefore disagreed. A production
canary reproduced 7 browser entries versus 11 published server entries.

The browser now awaits that same fast publication function exactly once and
copies its final URIs byte for byte. Only synthetic status entries at
`vless://…@127.0.0.1:1` are omitted from the browser's server list. Expired,
disabled and depleted profiles expose no server-copy buttons. Usage and expiry
come from the publication response, including first-use expiry activation.
Existing representative branding rules remain in `web/app.py`.

The self-contained RTL page includes platform selection, app import links,
subscription copying, individual server copying and update guidance. It makes
no external requests for scripts, fonts or app icons. Logos retain existing
branding; a no-referrer policy prevents leaking the subscription URL through
external logo requests. The response remains `no-store`, and a browser history
cache restore reloads the page. Clipboard success is shown only after a
successful Clipboard API call or successful `execCommand('copy')`; failures
offer selected text for manual copying.

## App import contracts

Every imported/copied subscription URL includes `config=1`, ensuring apps get
the machine format even if they send browser-like request headers. The website
does not install or connect the VPN; the app handles the import/confirmation.
Depending on app/version, users must update the subscription after adding it.

| App | Platforms | Scheme |
| --- | --- | --- |
| V2Box | Android, iOS | `v2box://install-sub?url=<encoded URL>&name=<encoded title>` |
| Happ | Android, iOS | `happ://add/<raw URL>` |
| v2rayNG | Android | `v2rayng://install-config?url=<encoded URL>#<encoded title>` |
| Streisand | iOS | `streisand://import/<encoded URL>` |

The scheme/encoding contracts match the [3x-ui subscription page model](https://github.com/MHSanaei/3x-ui/blob/main/frontend/src/pages/sub/subPageModel.ts).
The v2rayNG handler was also checked against its [official source](https://github.com/2dust/v2rayNG/blob/master/V2rayNG/app/src/main/java/com/v2ray/ang/ui/UrlSchemeActivity.kt).
These links preserve the original subscription token; no redirect service or
third party receives it. Browser testing verifies the constructed URLs and
platform selection, not native application import on a physical iPhone.

## Verification

`python -m unittest discover -s tests -p test_subscription_page.py` checks the
original copy mismatch, real SQLite server deactivation/reactivation, address
override plus published variants, expiry/quota, status-entry exclusion,
escaping, single publication call and app URL encoding.

`python tools/check-subscription-page.py --screenshots <directory>` optionally
uses Playwright Chromium to verify 320/390/940/1280px layouts, Android/iOS tabs,
exact clipboard content and both failed and successful clipboard fallbacks.
All fixtures are synthetic. Playwright is not a production dependency.

## Atlas branding and contacts

The owner's supplied logo is served as a 25 KB WebP asset, with a content version
in its URL and a long cache lifetime. The source artwork is preserved visually;
it was only resized/compressed for website delivery. A configured `ui.logo_data`
still takes precedence. Representatives with no logo retain a neutral symbol.

Owner pages show Telegram contacts from `subscription_page.bot_username`,
`channel_username`, `subscription_page.tutorial_username` and `support_username`.
Only public Telegram usernames are accepted. Platform contacts are omitted
entirely from representative pages. Telegram links open with `noopener
noreferrer`, so they do not disclose the private subscription URL.
