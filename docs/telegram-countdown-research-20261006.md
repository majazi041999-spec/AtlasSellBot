# Telegram countdown feasibility — 2026-10-06

Target: 2026-10-07 12:00 Asia/Tehran = 08:30 UTC; Unix timestamp `1791361800` (calculated from the explicit +03:30 offset).

## Native relative countdown: supported

Telegram introduced date formatting on March 1, 2026, including dynamic bot time variables and recipient-local date/time. [Official announcement](https://telegram.org/blog/member-tags-disable-sharing-and-more#time-and-date-formatting)

Bot API `MessageEntity` supports `date_time`, `unix_time`, and `date_time_format`. HTML with `parse_mode=HTML` accepts:

```html
افزایش قیمت: ۷ اکتبر، ساعت ۱۲:۰۰ به وقت تهران
زمان باقی‌مانده: <tg-time unix="1791361800" format="r">تا ۷ اکتبر ساعت ۱۲:۰۰ تهران</tg-time>
```

`r` means relative time; `T` means an absolute clock time including seconds, not a remaining HH:MM:SS timer. [Bot API formatting](https://core.telegram.org/bots/api#date-time-entity-formatting), [HTML syntax](https://core.telegram.org/bots/api#html-style)

The client specification explicitly requires realtime updates while the message is visible. Relative display rounds down to a single unit: 1h 1m 10s becomes “in 1 hour”; 1m 10s becomes “in 1 minute”; 10s becomes “in 10 seconds.” After the deadline it changes to elapsed-time wording. This supports an automatically updating native relative countdown in message text, including channel posts, but does not specify a custom multi-unit timer widget. [Date entities](https://core.telegram.org/api/entities#date-entities)

Recommendation: use native relative formatting plus a fixed, explicit Tehran deadline. Preserve useful fallback text and visually check target client versions before publishing; actual client compatibility was not tested. An end-of-campaign message/edit and the price change itself require independent scheduling/application logic (implementation inference).

## Alternatives

For custom remaining-time text inside the post, `editMessageText` can edit the bot’s message. Flood control exposes `retry_after`. A cautious minute-level edit scheduler is an engineering choice, not a documented safe edit rate. [Editing](https://core.telegram.org/bots/api#editmessagetext), [ResponseParameters](https://core.telegram.org/bots/api#responseparameters)

The FAQ documents **sending** limits: avoid >1 message/second in one chat; groups ≤20 messages/minute; bulk broadcasts about 30/second without paid broadcasts. It does not document an edit-specific quota there; do not claim these numbers guarantee per-second edits. [Official Bot FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)

For a bespoke HH:MM:SS display, a web/Mini App timer can run after opening a link. Direct links launch Mini Apps from any chat and support `startapp`, including channel context. They open a separate app surface rather than replacing the inline post rendering. [Mini App direct links](https://core.telegram.org/bots/webapps#direct-link-mini-apps)

Use a normal URL button linking to `https://t.me/botusername/appname?startapp=countdown`; the `web_app` button field is available only in private user–bot chats. [InlineKeyboardButton](https://core.telegram.org/bots/api#inlinekeyboardbutton)

No Telegram requests, credentials, posting, or remote mutations were used during this research.

## Authorized implementation after research

The owner selected the native relative display. A short follow-up to the owner's
existing price announcement was published in the configured main channel:
[channel post](https://t.me/atlas_account/268). The Bot API returned a `date_time`
entity with `unix_time=1791361800` and `date_time_format=r`, verifying that the
countdown was stored as a native entity, not ordinary static text. A URL button
opens the sales bot for purchases and renewals. Rendering on specific customer
client versions was not visually inspected.

Source and the guarded one-time publisher are in
`tools/announcements/price-countdown-20261007.html` and
`tools/announcements/publish-price-countdown-20261007.py`. Private receipts stay
under `/root/atlas-announcements` on the bot host. No recurring edit worker or
restart is required. Publishing the countdown does not change plan prices.
