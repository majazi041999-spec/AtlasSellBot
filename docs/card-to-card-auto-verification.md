# Automatic verification of card-to-card payments

Research note, 2026-09-23. Question: how can AtlasSellBot confirm that a customer's card-to-card (کارت به کارت) transfer really reached the owner's card, without an admin reading every receipt?

**Reading conventions**
- Every factual claim carries a source key such as `[aosp-nls]`. Keys resolve in §11, which gives each source's owner, the date printed on it, and PRIMARY or SECONDARY. All sources were accessed on 2026-09-23.
- **Inference** marks my own reasoning. Nothing marked that way is a sourced fact.
- **SECONDARY** marks a non-primary source, used only because the primary was unreachable or does not publish the fact.
- Iranian rules change often, so every regulatory figure carries its date.
- Code references point at this repository as it stands today.

---

## TL;DR

**Recommendation.**

1. **Build one bank-agnostic pipeline.**
   - *Payment intents* carry an amount that is allocated to one open order, not drawn at random.
   - *Payment events* come from any signal source.
   - A *matcher* pairs events with intents.
   - A *callback-independent approval service* does the approving.
   - An append-only audit log records every decision.
2. **First signal source: a dedicated Android phone.** It reads the owner's own bank notifications through `NotificationListenerService` and posts signed events to the Netherlands server.
   - The notifications can be bank-app push, or the bank's official bot in the Bale (بله) or iGap messenger.
   - It needs no company registration, no PSP contract and no bank credentials on the server.
   - It is the only candidate that proves the money arrived, works with a server outside Iran, and does not require describing the business to a PSP or fintech.
3. **Run it in shadow mode first.** The matcher proposes a match and an admin still clicks.
   - Then auto-approve only unique, exact-amount matches, behind per-order and per-day caps and a device-health gate.
   - Switch that on only after about 300 shadow matches with zero wrong pairings (§5.8).
4. **Fix the amount allocator before anything else.** Today every order draws one of 99 random offsets. Because unpaid orders stay open for at least 48 hours, identical amounts are routine at realistic volumes (§5.1).
5. **Keep receipt OCR and SMS in supporting roles.**
   - Receipt OCR stays a supporting signal only, because receipts are trivially forged and reused (§3.5).
   - Bank SMS can corroborate an event, but its absence proves nothing (§3.8).
6. **Not viable.**
   - **Open-banking and PSP deposit-ID products.** They onboard only legal entities, and their terms name VPN / filter-breaker sales as prohibited. Getting access would require misrepresenting the business (§3.2–3.3).
   - **Internet-bank scraping.** It needs the owner's credentials and OTPs on a server, two bank hosts did not even resolve from outside Iran in our test, and it carries ToS and lockout risk (§3.6).
   - **USDT as a replacement rail in 2026.** Nobitex has TRC20 suspended. Its 2 USDT minimum withdrawal is larger than a retail order. The large Iranian exchanges are OFAC-designated, and Tether's terms list Iran as a prohibited jurisdiction (§3.7).

**What automation does not fix.** The larger exposure is not the automation. It is commercial volume arriving on a personal card.
- The bot already sends about 190 deposits a month to one card.
- The Tax Administration's published trigger for treating personal accounts as commercial is at least 100 deposits and at least 35M toman in a month. It was announced in 2022, and whether it still holds in 1405 is unverified.
- Business accounts must be declared under the Terminals law (§4.3).
- Every PSP route excludes VPN sales (§4.5).

Automation neither creates nor removes that exposure, but faster throughput makes the account busier. The owner should decide the account question (§9) before scaling.

---

## 1. Current flow, and what it means for automation

### 1.1 How a card payment moves today

| Step | Where in code | Behaviour |
|---|---|---|
| Price the order | `_finalize_buy_payment` → `_jitter_price` (`bot/handlers/user.py`); the mini-app has its own copy, `_miniapp_jitter` (`web/app.py`) | `net = base + randint(1, max_off//10)*10`, with `max_off = random_price_max` (default 990). That gives 99 possible offsets (10 … 990 toman), drawn independently, with no memory of other open orders. |
| Store the order | `create_order(..., custom_price=net_price, base_price=clean_price)` (`core/database.py`) | The jittered card amount is persisted on the order. Wallet payment charges the clean `base_price`. |
| Renewals | `bot/handlers/user.py` around l.1451 and the mini-app renew in `web/app.py` around l.4340 → `create_custom_order` | Jittered the same way. |
| Wholesale (rep) bulk orders | `wholesale_naming_start` → `create_custom_order(price=final_price)` | **Not jittered.** |
| Wallet top-up (bot) | `wallet_topup_amount` jitters the typed amount but keeps it only in FSM state. `create_topup_request` writes the row when the photo arrives. | No record of the quoted amount exists until a receipt is uploaded. |
| Wallet top-up (mini-app) | `/app/api/wallet/topup` quotes a jittered amount and stores nothing. `/app/api/receipt` (`kind=topup`) takes `amount` from the **client's form**. | The credited amount is whatever the client submits. |
| Payment screen | `_payment_text` | Shows the card, "pay exactly this amount", "write nothing in the description field", and «⏰ مهلت پرداخت: ۳۰ دقیقه» (30-minute deadline). |
| Deadline enforcement | none | Orders stay `pending_payment` indefinitely. `run_cart_recovery` (`core/campaigns.py`) re-sends the card details at 30 min and 6 h for carts up to 48 h old (`cart_recovery_delay1_min`, `cart_recovery_delay2_hours`, `cart_recovery_max_age_hours`). **An amount therefore stays payable for at least 48 h, not 30 min.** |
| Receipt | `prompt_receipt` → `pending_receipt`; `receive_receipt` → `receipt_submitted`; broadcast to every admin with `order_review_kb`; each copy recorded in `review_messages` | The status set also includes `pending_receipt`, which the brief omits. |
| Approve (bot) | `approve_order_start` → `_do_approve(cb, oid, sid)` → `_do_approve_impl` (`bot/handlers/admin.py`) | Uses `cb.answer`, `cb.message.answer/edit_caption` and `cb.bot` throughout. |
| Approve (web panel) | `order_approve_web` → `_fulfill_order(oid)` (`web/app.py`) | Already callback-independent (it builds its own `Bot(token=BOT_TOKEN)`), but it **re-implements** `_do_approve_impl`. The copies have drifted: only the bot copy sends the thank-you and referral-invite messages. |
| Pay from wallet | `pay_with_wallet` → `_do_approve(cb, …)` with the **customer's** callback | Admin-facing replies such as «✅ … سابسکریپشن ساخته و برای کاربر ارسال شد.» land in the customer's chat. This is read from the code, not observed. |
| Top-up approve | `topup_approve` (bot); `api_topup_approve` and `topup_approve_web` (web) | See §1.2. |
| Resellers | manual wallet credits after transfers made outside the bot | `PROJECT_MAP.md` §11b records about 4.2B toman of `manual` credits to reseller accounts, against 123M toman of real top-ups. It flags that some of this may be gift or test balance. |

### 1.2 Concurrency facts that matter once a second approver (the machine) exists

- **Safe today.**
  - `claim_order_for_approval` is a single conditional `UPDATE`. It also re-claims a `processing` order after 15 minutes.
  - `reject_order_if_reviewable` and `claim_order_for_wallet_payment` are also conditional `UPDATE`s.
- **Top-up approval is check-then-act in all three places.** Each reads `status == 'pending'`, credits the wallet, and only then writes `approved`. An admin click and an automatic approval arriving together can both pass the check and **credit twice**.
- **`order_reject_web` writes `status='rejected'` unconditionally.** It does not use `reject_order_if_reviewable`, so it can flip an order that has already been auto-approved and delivered.
- **Three paths write status unconditionally:** `prompt_receipt`, the mini-app `/app/api/receipt` (`kind=order`) and `cancel_order`. An old button can push an `approved` order back to `pending_receipt` or `receipt_submitted`, or a paid one to `cancelled`.
- **Clocks.** `created_at` uses SQLite `datetime('now','localtime')`, which is the VPS's zone (Netherlands). Bank notifications carry Iran time, which is UTC+03:30 with no DST since March 2023 `[tz-iran]` `[majlis-dst]`. The matcher must work in UTC.

**Consequences for the design.**

1. Top-up amounts must be persisted when they are quoted, and credited from the *observed* bank amount, never from a client-supplied field.
2. The status machine needs guarded transitions before any automatic actor is added.
3. There must be exactly one approval implementation, which the bot handler, the web panel, the wallet path and the matcher all call (§6.2).

---

## 2. Signal sources compared

| Signal source | What it proves | Reliability / latency | Onboarding | Cost | Reachable from the NL server? | Legal / ToS risk | Effort | Verdict |
|---|---|---|---|---|---|---|---|---|
| **A. Owner's bank notifications (app push, or the bank's Bale/iGap bot) captured on a dedicated Android phone** | Money arrived in the owner's account: amount, time, sometimes balance or payer | Good if the phone is kept healthy. Bale bank messages are stored and delivered after an outage `[bale-bmi-bot]`. Latency: bank says "real-time" `[bmi-landing]`; unmeasured | None beyond the owner's own bank app | One Android phone + SIM | **Yes.** The phone pushes out to the server. It fails while Iran's international link is cut `[cf-2026]` | No bank term against it found. No credentials leave the phone | Medium | **Recommended primary** |
| B. Open-banking statement API (Finnotech) | Bank statement lines | High (bank data). Freshness not documented | Legal entities only `[finnotech-faq]`; account activated per client `[finnotech-statement]` | Enterprise pricing, not public `[finnotech-pricing]` | Not documented | Terms prohibit "VPN and means of bypassing filtering" `[finnotech-policy]` | Medium | **Not viable** without misrepresentation |
| C. PSP deposit ID / identified deposits (Jibit PIP, Vandar cash-in code, Zibal corporate banking) | Deposit to the provider's or business's account, tied to an ID or payer | High. Callbacks or webhooks `[jibit-pip-api]` `[vandar-cashin]` | Business banking; Zibal: legal entities only `[zibal-ebank]` | e.g. Jibit 5,000 rial per ID + 2,500 rial per 1M toman + VAT `[jibit-pid]` | Not documented | VPN named as prohibited by Vandar `[vandar-terms]` and Finnotech; Jibit and Zibal ban any illegal use `[jibit-rules]` `[zibal-terms]` | Medium | **Not viable** without misrepresentation |
| D. Bank SMS | Same as A, when it arrives | Owner reports late or missing SMS and varying senders. Melli stopped SMS under 30,000 toman in 2022 `[bmi-landing]` | None | Per-SMS fees (§3.8) | Via the same phone | Low | Low (same phone) | Corroboration only |
| E. Receipt OCR | That an image *claims* a transfer | Cannot prove a transfer: receipt generators are common `[fata-mizan]` | None | CPU | Yes | Low | Medium | Supporting signal only |
| F. Internet or mobile bank scraping | Statement lines | Brittle: one-minute OTPs for transfers `[cbi-otp]`; login OTP, captcha and session expiry vary by bank (Inference) | Owner's credentials on a server | Low | Two internet-bank hosts did not resolve from outside Iran (observed) | Credential sharing; captcha circumvention; lockout | High | **Not viable** |
| G. Crypto (USDT) with on-chain check | Transfer to our address, final after about 1 min `[tron-consensus]` | High on-chain, but see Verdict | Customers need an exchange account with KYC | Fees of 0.7 USDT on a 2 USDT minimum `[nobitex-options]` | Yes (TronGrid) | Iran is a Tether "Prohibited Jurisdiction" `[tether-legal]`; OFAC designated Nobitex, Wallex, Bitpin, Ramzinex `[ofac-sb0519]` | Medium | Not a practical replacement |
| H. «کیف پول ایران» (Iran Wallet), launched by Shaparak | Wallet-to-wallet transfer by phone number | New (Aug 2026). Results reported by SMS from the single sender `IRANWALLET` `[shaparak-iranwallet]` | Every customer must register | n/a | Via the phone (SMS) | Terms not researched | n/a | Watch; not evaluated |

---

## 3. Options in detail

### 3.1 Bank notifications on a dedicated Android phone (recommended)

**How it works.** A phone that stays in Iran runs the owner's bank app, or the bank's official messenger bot, and receives the owner's deposit alerts. A small forwarder app registers a `NotificationListenerService`, reads each alert, and POSTs a signed event to the bot's server (§6.4–6.5).

**Android platform evidence.** developer.android.com returned HTTP 403 to both fetch routes used for this research, so these points come from the AOSP source and Google Help.
- **What the service is.** A `NotificationListenerService` "receives calls from the system when new notifications are posted or removed". It must be declared with `BIND_NOTIFICATION_LISTENER_SERVICE`, and access is granted by the user in settings `[aosp-nls]`.
- **Useful callbacks.** `onNotificationPosted` delivers each new notification. `onListenerConnected` fires on every (re)bind, and from then on `getActiveNotifications()` can re-read what is still in the shade `[aosp-nls]`. That lets the forwarder recover alerts posted while it was unbound.
- **Keys for dedupe.** `StatusBarNotification.getKey()` is "a unique instance key for this notification record". `getPostTime()` is the post time `[aosp-sbn]`.
- **Low-RAM devices.** "Notification listeners cannot get notification access or be bound by the system on low-RAM devices running Android Q (and below)" `[aosp-nls]`. Do not use an Android Go or low-RAM phone.
- **Android 13+ sideloading.** Some settings are "restricted" for apps installed outside a store until the user taps **Allow restricted settings** in App info `[google-restricted]`. SECONDARY reporting says notification-listener access is one of these `[xda-restricted, SECONDARY]`.
- **Android 15+ OTP redaction.** Content that the system classifies as containing an OTP is hidden from listeners that are not "trusted", and they receive "Sensitive notification content hidden" `[aa-android15, SECONDARY]` `[ha-5153, SECONDARY]`. AOSP's ranking API describes sensitive content as "e.g. containing an OTP" `[aosp-nls]`.
  - **Inference:** deposit alerts are not OTPs, so this should not trigger. A misclassification would show up as unparsed events, which the server alerts on (§6.6).
- **Doze.** Doze (light and deep idle) is entered only when the screen is off **and the device is not charging** `[aosp-deviceidle]`. Doze "may involve things like turning off network access to apps" `[aosp-power]`. An app on the battery-optimisation allowlist gets "most power saving features" disabled `[aosp-power]`. **Keep the phone on a charger and allowlist the forwarder.**
- **OEM background killers.** Vendor skins kill background apps beyond stock Android. dontkillmyapp.com ranks Huawei, Xiaomi, OnePlus, Samsung and Meizu worst `[dkma, SECONDARY]`. **Inference:** prefer a phone close to stock Android, and verify with the heartbeat described in §6.5.

**Which Iranian banks send deposit alerts outside SMS.** This matters because the owner's card bank decides the channel.

| Bank / app | Deposit-alert channel (official statement) | Source | Caveat |
|---|---|---|---|
| Bank Melli (بانک ملی) | Transaction messages "in real time" through the official Bale bot «اطلاع‌رسانی بانک ملّی ایران». Also Neshan Bank, and the BAM statement. Free. | `[bmi-landing]` `[bale-bmi-bot]` | Bale messages are kept and delivered after the phone comes back online `[bale-bmi-bot]`. Bale delivery needs the SMS service active: per the FAQ, if SMS does not arrive either, the service is inactive and needs a branch visit `[bmi-landing]`. Since 2 Esfand 1400 (2022-02-21), messages under 30,000 toman are not sent by SMS `[bmi-landing]`. |
| Mellat | Transaction messages in Bale via `BankMellat_bot`, described as free | `[bale-mellat]` (Bale's own blog, not the bank) | Bale says the service ran "without a second of outage" when SMS failed during the 2026 crisis `[bale-mellat]`. |
| Saman: Blu (بلوبانک) | "Transaction alerts arrive as fast in-app notifications … a replacement for bank SMS" | `[blu-myket]` (store listing, developer بلوبانک سامان, v3.10.1.0, updated 1405/06/07 = 2026-08-29) | Notification content not documented |
| Pasargad: Wepod (ویپاد) | Deposits and withdrawals notified free as «اعلان درون‌برنامه‌ای» (in-app notifications) under the bell icon. SMS optional. | `[wepod-faq]` | May be an in-app inbox rather than an Android system notification. Must be tested. |
| Parsian | All transactions, including those under 500,000 rial, free via the iGap messenger | `[parsian-igap]` (1401/01/23 = 2022-04-12) | Still offered? Unverified |
| Tejarat | Only SMS, with selectable thresholds: all, >300k, >500k or >1M rial | `[tejarat-mb]` | A threshold setting can suppress alerts. No push statement found. |
| Saderat, Resalat, Bankino, Sepah, Keshavarzi, Refah, Maskan, Eghtesad Novin, Shahr, Sina, Ayandeh | No official push or messenger statement found | searched 2026-09-23; none found | Test the app directly |

No primary source documents what any of these alerts contain: amount, balance, time, payer card or reference. §9 therefore asks the owner for redacted samples.

**Reliability compared with SMS.**
- Melli set up the digital channels explicitly to cut SMS cost and "increase notification speed" `[bmi-landing]`. It has previously blamed an SMS outage on infrastructure outside the bank `[bmi-sms-2017]`.
- **Inference:** push or messenger alerts avoid the SMS operator hop and the SMS fee. However, they depend on the phone's data connection and on the app staying logged in.
- The listener cannot detect a notification that was never posted. That is why §6.5 adds heartbeats, balance-continuity checks and reconciliation.

**Format drift.** No bank documents its alert wording or promises stability; the search found no statement either way. **Inference:** treat every bank-app update as a possible parser break.
- Forward the raw text as well as any fields parsed on the phone, and parse on the server with a versioned parser.
- Raise an alert on the first unparsed alert from an allowlisted sender.
- Pin or delay bank-app updates on the phone and test after each one.

**Onboarding, cost, legal.**
- Onboarding and cost: nothing to sign up for. You need a mid-range Android phone (not Go/low-RAM), a SIM and data, and the owner's existing bank app or Bale account.
- Legal and ToS: no bank term was found that forbids reading one's own notifications, but bank ToS were not reviewed exhaustively. The phone holds a logged-in bank app, so it must be physically secured and dedicated to this job.
- The legal status of the business itself (§4) is unchanged.

**Effort (Inference).** About 2–4 developer-days for a minimal forwarder app, and 5–10 for the server side (ingestion, parser, matcher, approval refactor). Then a 4–8-week shadow period.

### 3.2 Open-banking statement APIs (Finnotech فینوتک)

- **What exists.** An account-statement service, `GET /oak/v2/clients/{clientId}/deposits/{deposit}/cc/statement`, returns an account's transactions for a date range `[finnotech-statement-op]`. Its limits `[finnotech-statement]`:
  - the account must be "the one activated for the client";
  - at most 31 days per request, 100 rows per page;
  - some banks need extra headers or ignore time filters.
- **Authorisation.** Client-credentials tokens cover the client's own resources; Authorization Code plus SMS-OTP is for services that need the account holder's consent `[finnotech-guide]`.
- **Not found in the current docs:** any card-to-card inquiry, any lookup of a deposit by bank reference, or any deposit webhook `[finnotech-inquiry]`.
- **Onboarding.** "Services can only be provided to legal entities" `[finnotech-faq]`. Pricing for banking services is on the Enterprise plan, by quote `[finnotech-pricing]`.
- **Prohibited business.** Finnotech's policy lists "VPN and means of bypassing the Islamic Republic's filtering". Discovery leads to suspended accounts and the owner's information being handed to the authorities `[finnotech-policy]`.
- **Regulatory context (SECONDARY).** A 1402 (2023) CBI circular was reported to forbid granting third parties API access to a legal entity's deposit account `[way2pay-api-circular, SECONDARY]`. The primary text was not found.
- **Verdict: not viable.** It is for companies, it serves the company's own accounts, and the terms prohibit this business. The only route in is misrepresenting the business, which this report rules out.

### 3.3 PSP deposit IDs, virtual accounts and "smart deposit" products

- **Jibit (جیبیت), payment identifier (PIP).**
  - A 15-digit ID paid through Paya, Satna or account-to-account transfer. Card-to-card is not among the listed rails `[jibit-pid]`.
  - Payments not approved by the business are refunded to the source account `[jibit-pid]`.
  - The API issues IDs, lists payments, verifies or fails them, and offers a callback hook for new payments `[jibit-pip-api]`.
  - Price: 5,000 rial per ID plus 2,500 rial per 1M toman deposited, plus VAT `[jibit-pid]`.
  - Jibit's "enriched statement" covers only "the business's own accounts" `[jibit-enriched]`.
- **Vandar (وندار), identified deposit (واریز شناسه‌دار).** It "only runs on embedded banking" `[vandar-cashin-docs]` and reports deposits by webhook `[vandar-cashin]`.
- **Zibal (زیبال), corporate banking.** Its deposit management explicitly covers card-to-card deposits, "with or without an ID" `[zibal-ebank]`.
  - Its FAQ answers "can individual (حقیقی) businesses use corporate banking?" with "No, currently only legal-entity businesses" `[zibal-ebank]`.
  - Activation takes 2–20 working days depending on the bank `[zibal-ebank]`.
- **Terms.**
  - Vandar lists "VPN and means of bypassing filtering" as prohibited. It may suspend the gateway, business and account and "block the funds until a judicial order" `[vandar-terms]`.
  - Sepal uses the same prohibition, with seizure of the balance `[sepal-terms]`.
  - Jibit counts any use contrary to Iranian law as "unauthorised use" `[jibit-rules]`.
  - Zibal blocks violating accounts and freezes their balance `[zibal-terms]`.
- **Other providers.** Pay.ir, IDPay, NextPay and PayPing were unreachable (DNS, expired TLS, 502, redirect loops). IDPay reportedly lost its licence `[way2pay-idpay, SECONDARY]`.
- **Verdict: not viable.** Every such product needs a business, usually a legal entity, and each provider's terms prohibit this activity, explicitly or through the "illegal use" clause (see §4.5). **Inference:** even if onboarded, most of these cover Paya/Satna/account transfers rather than retail card-to-card, and a gateway shutdown would freeze the balance held with the provider.

### 3.4 Can a card-to-card transfer carry an identifier?

- The deposit-ID products above attach the ID on **Paya, Satna or account-to-account** rails `[jibit-pid]` `[vandar-cashin]`.
- Where a provider does reconcile **card-to-card** deposits, it identifies them **by the source card or IBAN**, not by an ID the payer types `[zibal-ebank]`. Jibit's enriched statement likewise reports the origin, IBAN and counterparty name for card-to-card deposits `[jibit-enriched]`.
- This repository already assumes the description field is useless: `_payment_text` tells customers to leave «توضیحات/بابت» empty.
- **Conclusion (Inference from the above):** there is no documented, payer-set identifier that reaches the payee on a card-to-card transfer. The **amount** stays the matching key. The **payer's card** can be a second key if the owner's alert shows it (§9).
- For reseller-size transfers that go by Paya, Satna or Pol, a deposit ID needs an "identified account" product, which again means business onboarding (§3.3).

### 3.5 Receipt OCR (tracking number, amount, time, masked destination card)

- **What a receipt can prove by itself: nothing conclusive.**
  - Iran's FATA police warn that "receipt generator" apps, sites and Telegram bots produce convincing fake bank receipts. They tell sellers not to rely on the receipt image but to confirm the deposit in their own account (Mizan, the judiciary's news agency, 1403/09/13 = 2024-12-03) `[fata-mizan, SECONDARY]`.
  - The police's own site, cyberpolice.ir, refused connections from both fetch routes.
  - This matches how the fraud is described: the forger first reads the payee's name from the card number, then renders a receipt `[fata-mizan, SECONDARY]`.
- **Reuse.** A genuine receipt can be uploaded for a second order. **Inference:** OCR helps here by storing the extracted reference number (شماره پیگیری / شماره مرجع) and a perceptual hash of each image, and refusing duplicates.
- **Useful supporting checks (Inference).**
  - The amount equals the intent's amount.
  - The time falls inside the intent window.
  - The masked destination digits match `card_number`.
  - The reference number has not been seen before.
  - The payer's card last-4 matches what the bank alert shows, if it shows one.
- **Practicalities.** Persian OCR is available offline, for example Tesseract's `fas` model (Apache-2.0) `[tessdata-best]`. Receipts arrive as Telegram-compressed photos (`msg.photo[-1]`), so expect JPEG noise.
- **Verdict.** Useful for **triage and fraud flags**, never as the approving signal.

### 3.6 Internet-bank or mobile-bank automation (scraping)

- **Evidence.**
  - Card payments that need the second PIN already require a dynamic, one-time second password, valid "at most 1 minute" (CBI, 1398/09/10 = 2019-12-01) `[cbi-otp]`.
  - Whether each bank's *login* also demands an SMS OTP or captcha varies by bank; it was not verified here.
  - From outside Iran, `ib.bankmellat.ir` and `bam.bmi.ir` did not resolve at all (DNS ENOTFOUND, observed 2026-09-23 from the fetch service). This is an observation, not a published policy.
- **Risks (Inference).**
  - The owner's banking credentials would have to live on a server, or on a device reachable from it.
  - Every login needs a fresh OTP, and some need captcha solving, which amounts to bot-detection circumvention.
  - Repeated automated logins invite lockouts on the one account the business depends on.
  - Layout changes break the scraper without warning.
- **Verdict: not viable.** Option A gets the same data without credentials leaving the phone.

### 3.7 Crypto (USDT) as an alternative rail

- **On-chain verification is easy.**
  - TronGrid lists an address's TRC20 transfers (`GET /v1/accounts/{address}/transactions/trc20`, with `only_confirmed`, `only_to` and `contract_address`) `[trongrid-trc20]`.
  - `/walletsolidity/gettransactionbyid` returns only final transactions `[trongrid-txbyid]`.
  - Blocks come every 3 s. A block is final once 19 of the 27 super representatives have built on it, normally about a minute `[tron-consensus]`.
  - USDT-TRC20 contract: `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` `[tether-protocols]`.
- **But for this customer base in 2026:**
  - **Nobitex.** Nobitex's public API shows USDT on TRX (TRC20) with deposits and withdrawals disabled. BSC (BEP20) is the only USDT network enabled, with a 0.7 USDT fee and a 2 USDT minimum `[nobitex-options]`.
    - At Nobitex's quoted rate on the access date, 230,475 toman/USDT `[nobitex-stats]`, a 200,000-toman order is about 0.87 USDT.
    - That is below the minimum, and the fee alone would be about 81% of the order (Inference: arithmetic).
    - Level-1 KYC caps crypto withdrawal at 1M toman per 24 h `[nobitex-levels]`.
  - **Sanctions and freezing.**
    - OFAC designated Nobitex, Wallex, Bitpin and Ramzinex on 2026-06-02 `[ofac-sb0519]`.
    - Tether's terms (updated 2026-02-26) list Iran as a "Prohibited Jurisdiction" and reserve the right to freeze tokens and blacklist addresses `[tether-legal]`.
    - Tether has frozen large balances in coordination with OFAC `[tether-344m]`.
    - **Inference:** a receiving address fed from sanctioned exchanges risks being frozen.
  - **Iranian rules.**
    - A 2019 cabinet resolution stated that crypto is not permitted in domestic transactions `[cabinet-2019, SECONDARY copy]`. The 1401 mining regulation on rc.majlis.ir does not repeat that clause `[majlis-mining-1401]`. Whether the 2019 clause is still in force was not verified.
    - The CBI said in 2021 that only domestically mined crypto may be used, under its rules, for import payments `[cbi-crypto-1400]`.
    - The CBI's Supreme Board approved a crypto regulatory framework in Dec 2024 `[cbi-crypto-1403]`.
    - A 2025 CBI cap of USD 5,000 per person per year on stablecoin purchases was reported `[zoomit-cap, SECONDARY]`.
- **Verdict.** Not a replacement for card-to-card at retail sizes.
  - **Inference:** it could serve a few resellers who already hold USDT.
  - The owner would first need a sanctions and freezing risk assessment for their own jurisdiction. That is not researched here.

### 3.8 Bank SMS (owner-rejected; brief)

- The owner has rejected SMS as the primary signal: it arrives late or never, from varying senders.
- The official record is consistent with that:
  - Melli stopped SMS for transactions under 30,000 toman from 2022-02-21 `[bmi-landing]`.
  - Tejarat lets customers raise the SMS threshold `[tejarat-mb]`.
  - Melli has blamed SMS outages on third-party infrastructure `[bmi-sms-2017]`.
  - Bank SMS fees are reported between 37 and 70 toman per message, depending on source and year `[sms-fee, SECONDARY]`.
- **Role: corroboration only (Inference).**
  - If an SMS arrives with the same amount within a few minutes of an alert, raise confidence.
  - Never require an SMS, and never treat a missing SMS as evidence.
  - Capturing SMS on the same phone needs `RECEIVE_SMS` in a sideloaded app. That adds permission surface for little gain, so make it optional.

### 3.9 Other rails noticed

- «کیف پول ایران» (Iran Wallet) was launched by Shaparak on 1405/05/17 (2026-08-08). It is used through the USSD code `*98#`. Users register with their national ID and a SIM in their own name, and transfer money to other users by phone number.
- All transaction results are sent by SMS from the single sender `IRANWALLET` `[shaparak-iranwallet]`.
- **Inference:** a fixed sender ID would make parsing easy. However, every customer would need to register, and the rail's terms for business receipts are unknown. Revisit later; do not build for it now.

---

## 4. Regulatory constraints (dated)

These rules move fast. Each figure below carries the date printed on its source. intamedia.ir, the Tax Administration's news site, was down from both fetch routes on the access date. shaparak.ir's older document URLs return an error page since the site redesign. Those two gaps are why some rows are SECONDARY.

### 4.1 Transfer limits

| Rail | Limit | Date | Source |
|---|---|---|---|
| Card-to-card (Shetab, interbank) | **150,000,000 rial (15M toman) per card per 24 h** | Tejarat's FAQ, undated page. The press reports a CBI circular in Esfand 1404 (~Mar 2026) raising it from 10M toman | `[tejarat-faq]` `[cc-limit-1405, SECONDARY]` |
| Paya | at most 2bn rial per payment order (was 1bn) | CBI, 1402/12/15 (2024-03-05) | `[cbi-pol-1402]` |
| Satna | at least 1bn rial per customer order (was 500M) | same | `[cbi-pol-1402]` |
| Pol (پل, instant) | 500M rial non-in-person per day (was 100M); 1bn in person; **at most 5 Pol orders received per beneficiary per day** | same. The press reports a further rise to 1bn rial non-in-person in Esfand 1404 | `[cbi-pol-1402]` |
| Outgoing non-in-person transfers from a personal account | 2bn rial per day, 10bn rial per month. The purpose field is mandatory for 2–4bn rial; documents are required above 4bn | CBI circular 22848/03, 1403/02/04 (2024-04-23). The press reports 3bn/15bn from Esfand 1404 | `[cbi-gateway-1403]` |
| Incoming card deposits per person | CBI announced a cap of 20 incoming card transactions per day per national ID (1400/06/30 = 2021-09-21). The next day the Governor ordered it re-examined, saying no bank had yet implemented it | 2021-09-21 / 2021-09-22 | `[cbi-20-per-day]` `[cbi-20-review]`. Current status: not found |

**Inference:**
- Retail orders of a few hundred thousand toman are far below the card-to-card cap.
- A reseller sending more than 15M toman in a day cannot do it card-to-card from one card, so those payments arrive by Paya, Pol or Satna. Pol then limits a beneficiary to 5 receipts per day.
- The parser must understand alerts from those rails too.
- Do not design flows that split one payment across cards or days to fit a limit. Point the payer to a rail that fits instead.

### 4.2 Fees

See §5.6. Amounts are dated there; who pays is not confirmed by any primary source.

### 4.3 Tax: personal accounts that receive business deposits

- **Declaring business accounts.** Under the *Law on Store Terminals and the Taxpayers System* (قانون پایانه‌های فروشگاهی و سامانه مؤدیان, 1398/07/21 = 2019-10-13), Article 11, persons covered by the law must declare to the Tax Administration the bank accounts they use for their business activity. New accounts must be declared immediately through their portal `[majlis-terminals]`.
- **Penalty.** Under Article 22(پ), an undeclared account costs 10% of the sales that ran through it or 20M rial, whichever is higher `[majlis-terminals]`.
- **What makes an account "commercial".** Under the CBI's commercial-account framework (Shahrivar 1401 = Sep 2022), an account is "commercial" (حساب تجاری) when the Tax Administration declares it so. Commercial accounts get higher non-in-person limits, at the time 5bn rial/day and 30bn/month `[cbi-commercial-24153]` `[cbi-commercial-24156]`.
- **The published trigger for personal accounts** (Tax Administration official quoted on 1401/06/21 = 2022-09-12) `[mehr-tax-threshold, SECONDARY]`.
  - **Test:** a person's non-commercial accounts together receive **at least 100 deposits and at least 350M rial (35M toman) in one month**.
  - **Result:** the person gets an SMS, and the deposits are treated as sales and taxed. The owner can object with documents.
  - **Basis cited:** Budget Law 1400 (note 12, item م), Article 10 of the Terminals law, and a Monetary and Credit Council resolution.
  - **Not verified:** whether the thresholds are unchanged in 1405.
- **Inference on this business's volume.** The bot alone produces about 190 deposits a month (5.6 orders/day + 0.64 top-ups/day), which is above the count test. The amount test depends on the average basket and on reseller transfers. PROJECT_MAP §11b records billions of toman credited to reseller wallets. The owner should assume the receiving account is visible to this rule.
- **What this report does not suggest.** Spreading receipts across other people's or extra accounts to stay under the test would be structuring. It is not something this report entertains. Whether to register the account is a legal decision for the owner.

### 4.4 Account blocking (مسدودی حساب)

- **The CBI's concern.** The 2021 plan to cap card deposits at 20 per day (§4.1) shows the regulator is focused on many small card deposits into personal cards. Whether any bank enforces a count limit today was not found.
- **Gambling and betting law** (Majlis 1401/12/03 = 2023-02-22; Guardian Council 1401/12/13 = 2023-03-04). Anyone who knowingly puts their bank account or payment tools at an offender's disposal is punished as an accomplice, and PSPs must report `[majlis-gambling]`.
  - This is the legal backdrop to the "rented account" (حساب اجاره‌ای) crackdowns. This report does not consider rented accounts as an option.
- **FATA (2022).** FATA said more than 90% of rented cards serve crime, and that blocking is coordinated with the judiciary and the CBI `[ibena-fata-2022, SECONDARY]`.
- **No published automatic rule found.** No primary source was found for a count- or amount-based blocking rule in force in 2026.
  - **Inference:** the practical triggers are the tax designation (§4.3), complaints, judicial orders and bank-internal AML review. None of these is documented publicly.

### 4.5 Shaparak / PSP requirements and the status of VPN sales

- **eNamad (اینماد) and gateways.**
  - eNamad is issued only to authorised (مجاز) online businesses, after identity and eligibility checks. It is valid for two years and costs 175,000 toman `[enamad-faq]`.
  - Cancelling an eNamad file removes the domain from the list, "and the internet payment gateway is cut too" (FAQ 10.5). Suspension "also stops the bank gateway service" (FAQ 12.26) `[enamad-faq]`.
  - Payment gateways without a valid eNamad were cut off in a campaign starting Aban 1401 (Nov 2022), under the anti-smuggling directive `[peivast-enamad, SECONDARY]`.
- **Shaparak on VPN sellers.** In Esfand 1399 (Mar 2021) Shaparak told payment facilitators to cut e-payment service to merchants selling crypto or VPNs, or running betting or gambling `[digiato-shaparak-vpn, SECONDARY]`. No official prohibited-business list was found on shaparak.ir.
- **Supreme Council of Cyberspace resolution** (approved 1402/08/23 = 2023-11-14, published Feb 2024). Article 6 prohibits using filter-breakers (پالایش‌شکن) unless legally licensed `[scc-vpn, SECONDARY]`.
- **Computer Crimes Law** (1388/03/05 = 2009-05-26), Article 25. Producing, distributing, making available or trading software or tools used solely to commit computer crimes carries 91 days to 1 year in prison, a fine, or both `[majlis-ccl]`. It is cited against VPN sellers; whether it applies is debated (SECONDARY reporting).
- **Provider terms.**
  - Finnotech, Vandar and Sepal name VPN sales explicitly.
  - Jibit and Zibal ban any unlawful use.
  - The consequences they list are account suspension, frozen or confiscated balances, and referral to the authorities (§3.2–3.3).
- **Consequence for this project.**
  - **Every gateway, PSP, deposit-ID or open-banking route requires describing the business**, and these rules exclude it. Getting in by describing it as something else is misrepresentation, and not an option here.
  - The bank-notification route adds no new counterparty. It does not change the bank's or the tax administration's view of the account.

---

## 5. Matching design

### 5.1 Payment intents and unique amounts: the collision problem and the fix

**Today.** `_jitter_price` and `_miniapp_jitter` each draw one of **N = 99** offsets independently. Two open orders with the same base price share an exact amount with birthday-problem odds.

| Open orders at one base price | P(at least two share an amount), N = 99 (today) | N = 999 (1-toman steps) |
|---:|---:|---:|
| 2 | 1.0% | 0.10% |
| 3 | 3.0% | 0.30% |
| 5 | 9.7% | 1.0% |
| 8 | 25.2% | 2.8% |
| 10 | 37.5% | 4.4% |
| 13 | 56.1% | 7.5% |
| 20 | 87.2% | 17.4% |

- **How many are open at once.** It depends on how long an amount stays payable. In this code that is **at least 48 h**: nothing expires `pending_payment`, and cart recovery re-sends the card details for 48 h (§1.1).
- **Steady-state rate.** For *r* orders created per day at one base price, each open for *W* hours, the expected number of new same-amount pairs per day is about *r²W / (24N)*. This is Inference: arithmetic, and a Monte Carlo check agreed within 5%.
  - *r* = 6/day at one price and *W* = 48 h: about 0.73 colliding pairs per day (~22 per month). About 11% of new orders share their amount with an order that is still open.
  - Same *r*, *W* = 0.5 h (the advertised 30-minute deadline, if it were enforced): about 0.008 per day.
  - *r* = 6, *W* = 48 h, *N* = 999: about 0.07 per day.
- **Measure *r* first.** *r* counts orders **created**, including abandoned carts, not the 5.6 approved retail orders per day. The owner should run the read-only queries below before sizing anything.
- **Different base prices collide too.** Per-user prices, discount codes, renewals and free-form top-up amounts produce base prices within 990 toman of each other, so their ranges overlap. Offsets must therefore be unique across **final amounts**, not per base price.

```sql
-- Orders created per base price (last 118 days): gives r per price.
SELECT base_price, COUNT(*) AS created, ROUND(COUNT(*)/118.0, 2) AS per_day,
       SUM(status = 'approved') AS approved
FROM orders
WHERE created_at >= datetime('now','localtime','-118 days') AND base_price > 0
GROUP BY base_price ORDER BY created DESC LIMIT 15;

-- Historical pairs of orders with the same card amount created within 48 h of each other.
SELECT a.custom_price AS amount, COUNT(*) AS pairs
FROM orders a
JOIN orders b ON b.custom_price = a.custom_price AND b.id > a.id
             AND julianday(b.created_at) - julianday(a.created_at) <= 2.0
WHERE a.custom_price > 0
  AND a.created_at >= datetime('now','localtime','-118 days')
GROUP BY a.custom_price ORDER BY pairs DESC;
```

**Fix: allocate instead of drawing.**

1. **Create a `payment_intents` row when the amount is quoted.** Do this for orders, renewals, bot top-ups and mini-app top-ups. Wholesale orders get one too, and should be jittered like the rest.
2. **Allocate in one write transaction.** Inside `BEGIN IMMEDIATE`, pick a random free final amount in `[base+1, base+999]` toman, in 1-toman steps, that no intent in status `open` or `cooldown` holds.
   - SQLite allows only one write transaction at a time, and `BEGIN IMMEDIATE` takes the write lock up front `[sqlite-tx]`.
   - Enforce the rule in the schema as well, with `CREATE UNIQUE INDEX … ON payment_intents(expected_amount_rial) WHERE status IN ('open','cooldown')`. A UNIQUE partial index enforces uniqueness only among rows matching its `WHERE` `[sqlite-partial]`.
   - That `WHERE` cannot contain non-deterministic functions `[sqlite-partial]`, so it cannot compare against the current time. A sweeper therefore moves intents `open → cooldown → released` on the clock.
3. **Set the lifetimes.**
   - An intent is valid until `expires_at`. Suggestion: 48 h, to match cart recovery; or shorten both.
   - After it matches, expires or is cancelled, it sits in `cooldown` for 24 h before its amount can be reused. A late payment of a reused amount then cannot land on a stranger's order.
4. **Capacity.** 999 concurrent intents per base price. If one ever fills, fall back to a manual-review order rather than a duplicate amount.
5. **Customer friction.** None extra. Customers already copy an odd amount; 1-toman steps simply read, for example, 199,437 instead of 199,430.
6. **Store money in rial internally** (`expected_amount_rial = toman × 10`). Bank alerts often show rial, and a customer who types rial into their bank app must still match exactly.

### 5.2 Time windows and clocks

- **Match window:** `intent.created_at − 5 min ≤ event.occurred_at ≤ intent.expires_at + 30 min`. The 5 min absorbs phone and server clock skew. The 30 min absorbs alert delay. Both values are Inference, to be tuned in shadow mode.
- **Store every timestamp in UTC.** For each event keep three times: the bank's own timestamp if the alert has one, the phone's `postTime` `[aosp-sbn]`, and the server's receive time.
- Iran is UTC+03:30 with no DST `[tz-iran]` `[majlis-dst]`. The existing `created_at` columns are VPS local time, so convert them when comparing.

### 5.3 Matching keys, in order of strength

1. **Exact amount in rial.** Present in every alert, and made unique by §5.1.
2. **Time**, inside the window.
3. **Payer card last-4.** Usable only if the owner's alert shows the source card; this is unknown, see §9. The bot could then ask customers for the last 4 digits of the card they paid from (optional field).
4. **Bank reference.** The RRN or tracking number (شماره مرجع / شماره پیگیری). It is useful only if the *alert* carries the same reference that the *receipt* shows. Verify with real samples.
5. **Balance-after (مانده).** If alerts include it, every credit must satisfy `balance_n = balance_{n-1} ± amount_n`. A mismatch means an alert was missed; raise it and reconcile. **Inference:** this is the strongest available completeness check.

### 5.4 Idempotency

- **Event:**
  - `UNIQUE(device_id, event_uid)`, where the phone derives `event_uid` from the notification key, post time and a content hash. It must stay stable across retries.
  - Plus `UNIQUE(bank_ref)` where present.
  - Plus a cross-channel fingerprint `(amount, balance_after, occurred_at rounded to the minute)`, so push, Bale and SMS copies of one deposit collapse into one event with corroborations.
- **Match:** conditional `UPDATE`s only.
  - `payment_events SET matched_intent_id=? WHERE id=? AND matched_intent_id IS NULL`
  - `payment_intents SET status='matched' WHERE id=? AND status='open'`
- **Approval:**
  - Orders: the existing `claim_order_for_approval`.
  - Top-ups: a new `claim_topup_for_approval`, a conditional `UPDATE` in the same transaction as the wallet credit.
- One bank deposit can therefore approve at most one order, and one order can be approved at most once, whoever races.

### 5.5 Partial, over, duplicate and split payments

| Case | Detection | Action |
|---|---|---|
| Underpayment | Event amount below every open intent in range, and near one | Never auto. Manual queue shows the nearest intent. The admin approves, asks for the difference, or refunds. |
| Overpayment | No exact match; an intent sits just below the amount | Never auto. The admin may approve and credit the excess to the wallet. |
| Duplicate payment | Same payer pays twice: the second event finds its intent already `matched` or in `cooldown` | Unmatched queue. Suggested action: credit to the customer's wallet. |
| Duplicate alert | Same deposit seen twice (re-post, push plus Bale, retry) | Collapsed by §5.4. No action. |
| Split payment | Two or more events from one payer within a short time that sum to an intent | Suggest only (manual). Never auto-sum. |
| Paid after cancel or expiry | Event matches an intent in `cooldown` whose order is `cancelled` or unpaid | Manual queue with the history. |
| Personal or unrelated deposits | No intent matches | Stay unmatched. **Inference:** a separate sales-only account keeps this queue clean (§9). |

### 5.6 Does the received amount always equal the sent amount?

- **Fee amounts, with dates.**
  - The CBI raised the card-to-card fee from 500 to 600 toman on 1399/08/12 (2020-11-02) `[cbi-fee-1399]`.
  - Tejarat's FAQ (undated) shows 9,000 rial up to 10M rial, plus 3,200 rial per extra 10M rial `[tejarat-faq]`.
  - The 1405 schedule is reported as 1,100 toman up to 1M toman plus 350 toman per extra million `[fee-1405, SECONDARY]`. Reports give conflicting approval and effective dates.
- **Who pays: no primary source found.**
  - Not the CBI announcement, the Tejarat FAQ, or any bank page reached. None states whether the fee is charged to the sender on top of the amount or taken out of the transferred amount.
  - Secondary finance sites say the sender pays and the recipient receives the full amount `[fee-who-pays, SECONDARY]`.
  - The same gap applies to Paya, Satna and Pol fees.
- **Design rule (Inference).**
  - The matcher never adds or subtracts fees.
  - Shadow mode must confirm empirically that every class-A alert amount equals its intent amount to the rial. An alert that is a fixed fee short would surface there as a steady run of near-misses.
  - Until that holds for card-to-card and for each other rail seen, those rails stay manual.
- **Units (Inference).** Customers pay in the unit their app uses: some apps take rial, most people think in toman. Store rial internally (§5.1). Treat an amount off by exactly a factor of 10 as a class-C "unit mistake" for the admin, never as a match.

### 5.7 Confidence classes and decisions

| Class | Conditions (all required) | Shadow phase | Auto phase |
|---|---|---|---|
| **A** | Exactly one `open` intent with that amount; event inside window; parser confident; direction = credit; device healthy; event not matched before; customer not blocked; amount ≤ auto cap; daily auto count and total under caps; plus payer last-4 or receipt consistency for amounts above a second threshold | Annotate the admin's review message ("🤖 bank event #123 matches"); admin clicks | Approve through the approval service, then notify admins with an undo button |
| **B** | Unique amount match, but a soft check fails (outside window, over cap, no receipt yet, device degraded) | Annotate | One-tap proposal to admins |
| **C** | Ambiguous, no match, mismatched amount, unparsed alert, or conflicting signals | Unmatched queue | Unmatched queue |

Auto-approval also stops, falling back to class B, when any of these holds:
- the device heartbeat is stale;
- the balance-continuity check fails;
- more than *k* unparsed alerts arrived in the last hour;
- the kill switch `pay_match_mode` (§6.8) is not `auto`.

### 5.8 Shadow mode, and how to know it is safe

- **What shadow mode does.** The matcher runs on every event, intent and receipt, writes its decision to the audit table and annotates the admin's review message, but it **never approves**.
- **What to log per decision:** the class, the proposed intent, and the admin's eventual action on that order.
- **Metrics.**
  - **Precision of A:** A-proposals the admin approved *for the same order*, divided by all A-proposals.
  - **Coverage:** admin-approved card orders that had an A-proposal.
  - **Latency:** deposit to event to match.
  - **Health:** unmatched-event rate, unparsed-alert rate, and device downtime.
- **Gate for enabling auto (Inference: statistics).** With **zero** wrong pairings among *n* A-decisions, the 95% upper bound on the true error rate is about 3/*n*.
  - **n = 300:** bound ≈ 1%, about 7 weeks at today's ~6.2 approvals per day.
  - **n = 150:** bound ≈ 2%, about 4 weeks.
  - Any wrong pairing resets the count after the root cause is fixed.

---

## 6. Recommended architecture for this codebase (design level)

### 6.1 Preconditions: fix before any automatic approver exists

1. **Top-up approval.** Add `claim_topup_for_approval(rid)`: `UPDATE topup_requests SET status='processing' WHERE id=? AND status='pending'`. Credit the wallet only if `rowcount == 1`, ideally in the same transaction. Use it from `topup_approve`, `api_topup_approve`, `topup_approve_web` and the matcher.
2. **Web order reject.** Make `order_reject_web` use `reject_order_if_reviewable`.
3. **Guarded transitions.**
   - `prompt_receipt`: only from `pending_payment` or `pending_receipt`.
   - mini-app receipt: only from `pending_payment` or `pending_receipt`.
   - `cancel_order`: only from `pending_payment` or `pending_receipt`. Also move the intent to `cooldown`.
4. **Persist quoted top-up amounts** as intents, and ignore the client-supplied `amount` in `/app/api/receipt`.
5. **Replace `_jitter_price` and `_miniapp_jitter`** with one allocator (§5.1) in `core/`.

### 6.2 One approval service, independent of Telegram callbacks

- **Shape.** A new module, e.g. `core/approval.py`, with two entry points:
  - `approve_order(order_id, *, actor, source, event_id=None, bot) -> ApprovalResult`
  - `approve_topup(topup_id, *, actor, source, amount_rial, event_id=None, bot) -> ApprovalResult`
- **What it contains.** It owns the whole fulfilment, merged from `_do_approve_impl` and `_fulfill_order`:
  - claim;
  - renew, renew-subscription or create subscriptions;
  - set `approved`;
  - referral bonus and `apply_post_approval_rewards`;
  - customer messages;
  - `_clear_order_review_kbs` for every admin's copy;
  - audit row.
- **What it returns.** A result with `ok`, `error`, the created subscriptions, and admin-facing text. It never touches a `CallbackQuery`.
- **Callers become thin adapters.**
  - `approve_order_start` and `assign_server`: call the service, then `cb.answer(...)` and edit the caption from the result.
  - `order_approve_web`: calls the service.
  - `pay_with_wallet` and mini-app wallet pay: call the service with `actor=wallet`. This fixes the admin text currently sent into the customer's chat.
  - The matcher calls the service with `actor=auto`.
- **Retries.** `claim_order_for_approval` re-claims `processing` after 15 min. The matcher must never retry a claim by itself; a stuck `processing` order goes to the admin.
- **`bot` argument.** Pass the running dispatcher's `Bot`. The web layer's pattern of opening a throwaway `Bot(token=BOT_TOKEN)` per call can stay for the web routes.

### 6.3 Data model (new tables; add through `_ensure_columns` / `SCHEMA`, remembering the `;`-in-comment trap in PROJECT_MAP §13)

| Table | Key columns |
|---|---|
| `payment_intents` | `id, kind('order','topup'), order_id, topup_id, user_id, base_amount_rial, expected_amount_rial, created_at_utc, expires_at_utc, cooldown_until_utc, status('open','matched','cooldown','released','cancelled'), payer_last4, matched_event_id` + partial UNIQUE on `expected_amount_rial` for `open`/`cooldown` |
| `payment_devices` | `id, label, public_key, allowed_packages, enrolled_at, revoked_at, last_heartbeat_at, last_event_at, app_version, charging, listener_connected` |
| `payment_events` | `id, device_id, event_uid, channel('push','bale','igap','sms','manual'), package, raw_title, raw_text, bank_ts_utc, posted_at_utc, received_at_utc, parser_version, parse_status, direction, amount_rial, balance_after_rial, bank_ref, payer_hint, fingerprint, status('new','matched','unmatched','ambiguous','duplicate','ignored'), matched_intent_id, corroborates_event_id` + UNIQUE `(device_id, event_uid)`, partial UNIQUE `bank_ref` |
| `payment_audit` | `id, at_utc, actor('auto','admin:<tg id>','web','wallet'), mode('shadow','assisted','auto'), action('proposed','approved','rejected','assigned','ignored','reverted','override'), intent_id, event_id, order_id, topup_id, class, reasons_json, before_status, after_status`. Append-only: no UPDATE or DELETE paths. |
| `receipt_facts` (optional, with OCR) | `order_id/topup_id, file_id, image_phash, ocr_amount_rial, ocr_time, ocr_ref, ocr_dest_last4` + partial UNIQUE `ocr_ref` |

Raw alert text contains the account balance. Restrict it to owner-role admins, and consider a 90-day retention sweep.

### 6.4 Payment-event ingestion endpoint

- **Path.** `POST /api/pay/v1/events` and `POST /api/pay/v1/heartbeat`, **outside `/{S}/`**, the same rule the reseller API follows, so the panel's secret prefix never sits on a phone (PROJECT_MAP §4, §8c). Any future source (a statement poller, a second phone, manual entry) uses the same endpoint.
- **Enrolment.** The forwarder generates a P-256 key pair in Android Keystore. The owner enrols the public key in the panel, for example by QR code, and can revoke it there.
  - **Inference:** asymmetric keys mean a database leak does not let anyone forge deposits. With an HMAC shared secret, it would.
  - Python's `cryptography`, already installed through `python-jose[cryptography]`, verifies the signatures.
- **Per-request authentication.**
  - Headers: `X-Device-Id`, `X-Timestamp`, and `X-Signature` over `method|path|timestamp|sha256(body)`.
  - Reject if the clock skew exceeds 300 s, or the key is revoked.
  - Replays are absorbed by `UNIQUE(device_id, event_uid)`.
- **Idempotent responses.** A repeat returns `200 {"status":"duplicate","event_id":…}`. A new event returns `200 {"status":"accepted"}` before matching, so the phone's retry logic stays simple.
- **Limits.** Body at most 16 KB, per-device rate limit, and schema validation. Log through `client_ip()`, but do not allowlist IPs, because mobile IPs change.
- **Heartbeat body:** app version, whether the listener is connected, charging, battery, time of the last alert seen per package, and queue length.

### 6.5 Android forwarder (minimal app)

- **Listening.** A `NotificationListenerService` restricted to an allowlist of packages (bank app, Bale, iGap) and, for messengers, the bank bot's chat title.
- **Capture.** On `onNotificationPosted`, capture title, text, big text and MessagingStyle messages. Append them to a local queue and let a background worker POST with exponential backoff. The queue survives reboots and internet shutdowns.
- **Recovery.** On `onListenerConnected`, re-scan `getActiveNotifications()` `[aosp-nls]`. The server deduplicates.
- **Heartbeat.** At least every 15 min. The server raises a Telegram alert to admins after 30 min of silence and drops the matcher to class B.
- **Phone setup.**
  - Not low-RAM `[aosp-nls]`.
  - Permanently on a charger `[aosp-deviceidle]`.
  - Battery-optimisation allowlist `[aosp-power]`.
  - OEM auto-start settings `[dkma, SECONDARY]`.
  - "Allow restricted settings" if sideloaded `[google-restricted]`.
  - Screen lock on, no other apps, bank-app auto-update off.
- **Network (Inference).** The phone must reach the NL server from inside Iran's filtered network, so give the forwarder a route that works there, for example the owner's own tunnel via per-app split tunnelling. During nationwide shutdowns nothing gets through: 2026-01-08 to about 01-27, and 2026-02-28 to 05-26, 87 days `[cf-2026]`. Events wait in the queue, and the bot falls back to manual review.

### 6.6 Matcher

- **Triggers.** It runs on each new event, each new intent, each receipt, and a periodic sweep: expiry, cooldown release, stale-device checks.
- **Pure and testable.** It takes events, intents and device state, and returns decisions (§5.7). Side effects go only through the approval service and the audit table.
- **Parsers.** Per bank and channel, versioned, with golden tests built from the owner's real (redacted) alert samples. The first unparsed alert from an allowlisted sender pages the admins.

### 6.7 Audit, admin override, reconciliation

- **Audit.** Every proposal, approval, rejection, manual assignment and undo writes a `payment_audit` row with the reasons.
- **Admin override.**
  - Assign an unmatched event to an order or top-up.
  - Mark an event "not a sale".
  - Undo an auto-approval: disable the created subscription or debit the credited top-up, set the order to a new `reversed` status, and write an audit row.
  - Manual approval without an event stays available and is logged as `event_id = NULL`.
- **Reconciliation (Inference).** A daily report of auto-approved orders, their events and the balance continuity. The owner compares it weekly against the bank statement.

### 6.8 Settings and kill switches

`pay_events_enabled`, `pay_match_mode` (`off` | `shadow` | `assisted` | `auto`), `pay_auto_max_amount`, `pay_auto_daily_count`, `pay_auto_daily_total`, `pay_intent_ttl_hours`, `pay_intent_cooldown_hours`, `pay_device_stale_minutes`. Follow PROJECT_MAP §14 for new settings.

---

## 7. Phased rollout

| Phase | Scope | Exit criterion |
|---|---|---|
| **0 — Groundwork** (no behaviour change for customers) | §6.1 fixes; the approval service (§6.2); intents plus allocator; run the §5.1 queries | Tests: concurrent approve × approve, approve × reject, top-up double-click all yield one effect |
| **1 — Ingest + shadow** | Phone + forwarder; ingestion endpoint; parser for the owner's bank; matcher in `shadow`; annotations on review messages; unmatched-event list in the panel | ≥ 2 weeks of heartbeats with no unexplained gap; parser handles 100% of real alerts |
| **2 — Assisted** | Class A/B proposals become one-tap approvals. The customer is told "payment seen, activating". | Precision gate of §5.8 met (≈300 A-decisions, 0 wrong) |
| **3 — Auto (A only)** | `auto` for class A under caps. Every auto-approval is posted to admins with an undo button. Daily reconciliation report. | A month with no reversals caused by the matcher |
| **4 — Extend** | Top-ups credit the observed amount; resellers request top-up intents in the bot instead of off-bot transfers; optional OCR and SMS corroboration | Owner decision |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| A forged event approves an unpaid order | Device signatures; only exact matches to open intents; caps; reconciliation; undo |
| The phone dies, is unplugged, is logged out, or the bank app updates | Heartbeat alarm; automatic fallback to manual; balance-continuity check; update discipline |
| Nationwide internet shutdown (two in 2026 `[cf-2026]`) | Queue on the phone; manual fallback; the bot's messaging says when approval is manual |
| An alert is never posted (bank-side failure) | Balance continuity; unmatched receipts older than X minutes are escalated to admins |
| Same amount from an unrelated personal deposit | Allocated, non-round amounts; time window; a sales-only account (§9) |
| Parser misreads a debit as a credit, or reads a promotional notification | Strict per-bank templates; direction field required; allowlisted senders only |
| Regulatory action on the account: tax reclassification or blocking | Not solved by automation; see §4 and §9. Volume caps don't change the legal position, and splitting deposits to stay under thresholds is not an option this report entertains. |
| Staff trust erodes after one bad auto-approval | Shadow gate, undo button, audit trail |

---

## 9. Open questions for the owner

1. **Which bank** is the receiving card on? That decides the channel: Blu push, Melli or Mellat via Bale, Parsian via iGap, or a test of the app.
2. **Please share 5–10 real deposit alerts** from that channel, with the balance and names redacted, including one card-to-card deposit and one Paya/Pol deposit. We need to know whether alerts show the payer's card, a reference number, and the balance.
3. **Is the card also used for personal money?** A separate account in the owner's own name, used only for sales, would make matching cleaner and bookkeeping honest. Whether to register it as a commercial account with the tax administration is the owner's legal decision (§4).
4. **Can you dedicate an Android phone** (Android 11+, not Go/low-RAM) permanently on a charger, with a stable route to the NL server?
5. **Auto-approve caps.** Maximum order amount, maximum approvals per day, maximum total per day.
6. **Should unpaid orders expire?** Today they never do, and cart recovery keeps them payable for 48 h. The intent lifetime should follow whatever you decide.
7. **May the bot ask customers for the last 4 digits** of the card they paid from?
8. **Resellers.** Typical rail (card-to-card, Paya, Satna or Pol), sizes and frequency. Would they accept requesting a top-up in the bot and paying the exact amount it quotes?
9. **Run the two read-only SQL queries** in §5.1 on the server and share the aggregates. That tells us the real collision rate today.

---

## 10. Claims not verified from primary sources

**Money rules**
1. **Who pays the card-to-card fee**, and whether the payee always receives exactly the entered amount. Only SECONDARY sources say so; §5.6 turns this into a shadow-mode check. The same gap applies to Paya, Satna and Pol fees.
2. **The CBI's own text** of the Esfand 1404 circular that raised card-to-card to 15M toman per day. A bank FAQ gives the figure, undated; the press reports the circular.
3. **The 1405 fee schedule:** its amounts and its effective date. SECONDARY only, and the reports conflict.
4. **The tax trigger** (≥100 deposits and ≥35M toman per month).
   - It is reported through a Tax Administration official quoted in 2022, and intamedia.ir was down.
   - Its status in 1405 is unknown.
   - A reported Budget Law 1403 clause taxing deposits to non-commercial accounts could not be located in the rc.majlis.ir text.
5. **Blocking rules.** The current status of the CBI's 2021 plan for 20 card deposits per day, and whether any count- or amount-based blocking rule is in force in 2026.

**VPN sales and gateways**
6. **Shaparak's 2021 instruction** to cut VPN sellers, and any official Shaparak list of prohibited businesses. SECONDARY only.
7. **The Supreme Council of Cyberspace's VPN resolution** text. SECONDARY only.
8. **The eNamad gateway enforcement campaign** of Aban 1401. SECONDARY; the eNamad FAQ statements themselves are primary.

**Android**
9. developer.android.com and source.android.com returned HTTP 403 from both routes, so the following come only from AOSP code comments, Google Help (in general terms) and SECONDARY reports:
   - that Android 13's "restricted settings" cover notification-listener access for sideloaded apps;
   - Android 15's OTP redaction for untrusted listeners;
   - the OEM background-killer ranking.

**Receipts**
10. **The FATA warning about receipt generators.** cyberpolice.ir refused connections, so it comes from Mizan (SECONDARY).

**Bank alerts**
11. **Mellat's alerts in Bale** come from Bale's blog, not from Mellat.
12. **What any bank's alert contains** (amount, balance, payer card, reference): nothing published.
13. **Whether Wepod's "in-app notifications"** are Android system notifications.
14. **Whether Parsian's iGap alerts** still run in 2026.
15. **That alerts arrive within seconds.** "Real-time" is Melli's own wording; nothing was measured.

**Providers**
16. **The CBI's 1402 circular** forbidding third-party API access to legal entities' accounts. SECONDARY.
17. **IDPay's licence revocation** (SECONDARY). The status of Pay.ir, NextPay and PayPing is also unknown; all were unreachable.
18. **Finnotech:** IP whitelisting or an Iran-only IP requirement, statement freshness, and per-call price. None are published.
19. **Jibit, Vandar and Zibal:** IP requirements and exact onboarding documents. None are published.

**Crypto**
20. **Crypto rules and operations:**
    - the 2025 CBI stablecoin caps (SECONDARY);
    - whether the 2019 cabinet clause on domestic use is still in force;
    - Nobitex withdrawal processing times;
    - why and when TRC20 was suspended;
    - sanctions exposure in the owner's own jurisdiction (not researched).

**Other**
21. **Bank SMS fee per message:** SECONDARY, and the figures conflict (37–70 toman).
22. **Internet-bank hosts not resolving from outside Iran:** a one-off observation, not a published policy.

---

## 11. Sources

All accessed 2026-09-23. "Date" is the date printed on the source; I converted Jalali dates myself. P = PRIMARY, S = SECONDARY. `aosp-*` files are read from the AOSP `main` branch mirror, because developer.android.com returned HTTP 403.

**Android, platform, tooling**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| aosp-nls | `NotificationListenerService.java` (Android Open Source Project) | main branch | P | https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/core/java/android/service/notification/NotificationListenerService.java |
| aosp-sbn | `StatusBarNotification.java` (AOSP) | main branch | P | https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/core/java/android/service/notification/StatusBarNotification.java |
| aosp-power | `PowerManager.java` (AOSP) | main branch | P | https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/core/java/android/os/PowerManager.java |
| aosp-deviceidle | `DeviceIdleController.java` (AOSP) | main branch | P | https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/apex/jobscheduler/service/java/com/android/server/DeviceIdleController.java |
| google-restricted | "Allow restricted settings" (Google Android Help) | undated | P | https://support.google.com/android/answer/12623953 |
| xda-restricted | Android 13 "Restricted setting" blocks sideloaded notification listeners (XDA) | 2022 | S | https://www.xda-developers.com/android-13-restricted-setting-notification-listener/ |
| aa-android15 | How Android 15 protects 2FA codes from untrusted listeners (Android Authority) | 2024 | S | https://www.androidauthority.com/android-15-two-factor-authentication-codes-3492585/ |
| ha-5153 | home-assistant/android issue #5153, first-hand report of redacted OTP notifications | 2025 | S | https://github.com/home-assistant/android/issues/5153 |
| dkma | Don't kill my app! (Urbandroid) | undated | S | https://dontkillmyapp.com/ |
| tessdata-best | tesseract-ocr/tessdata_best (includes `fas`) | repo | P | https://github.com/tesseract-ocr/tessdata_best |
| sqlite-partial | Partial indexes (SQLite) | undated | P | https://www.sqlite.org/partialindex.html |
| sqlite-tx | Transactions (SQLite) | undated | P | https://www.sqlite.org/lang_transaction.html |
| tz-iran | tz database `asia` file, Iran section (IANA tz, maintained repo) | comment 2022-05-10 | P | https://raw.githubusercontent.com/eggert/tz/main/asia |
| majlis-dst | قانون نسخ قانون تغییر ساعت رسمی کشور (Majlis Research Center law database) | 1401 (2022) | P | https://rc.majlis.ir/fa/law/show/1745106 |
| cf-2026 | "Iran's Internet is partially restored" (Cloudflare) | 2026-05-27 | P | https://blog.cloudflare.com/iran-internet-partially-restored-may-2026/ |

**Banks and bank-alert channels**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| bmi-landing | سامانهٔ نوین اطلاع‌رسانی بانک ملی ایران (Bank Melli) | undated; refers to 1400/12/02 = 2022-02-21 | P | https://bank-melli.ir/landing/sms |
| bale-bmi-bot | «اطلاع‌رسانی بانک ملّی ایران» bot page (Bale) | undated | P | https://ble.ir/bam_bmi |
| bmi-sms-2017 | توصیه‌های بانک ملی ایران در پی اختلال خدمات مبتنی بر پیامک (Bank Melli) | 1396/08/07 = 2017-10-29 | P | https://bank-melli.ir/News/News/Details/14203 |
| bale-mellat | خدمات بانک ملت در بله (Bale blog; Bale's statement, not Mellat's) | 1405/04/27 = 2026-07-18 | P (for Bale) | https://blog.bale.ai/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A8%D8%A7%D9%86%DA%A9-%D9%85%D9%84%D8%AA-%D8%AF%D8%B1-%D8%A8%D9%84%D9%87 |
| blu-myket | Blu app listing, developer بلوبانک سامان (Myket) | updated 1405/06/07 = 2026-08-29 | P | https://myket.ir/app/com.samanpr.blu |
| wepod-faq | Wepod FAQ, «اطلاع‌رسانی پیامکی» (Wepod / Pasargad) | undated | P | https://wepod.ir/faq/ |
| parsian-igap | iGap free transaction alerts (Parsian Bank) | 1401/01/23 = 2022-04-12 | P | https://parsian-bank.ir/news/187591/187591.htm |
| tejarat-mb | Mobile banking page, SMS thresholds (Tejarat Bank) | Mordad 1405 | P | https://www.tejaratbank.ir/web_directory/1493-Mobile-Banking.html |
| tejarat-faq | FAQ Q25 (Shetab limit) and Q37 (card-to-card fee) (Tejarat Bank) | undated | P | https://www.tejaratbank.ir/services/FAQ/search/query/ |
| cbi-otp | نکات کلیدی در فعال‌سازی رمز دوم پویا (CBI) | 1398/09/10 = 2019-12-01 | P | https://cbi.ir/showitem/19709.aspx |
| sms-fee | Report of the 1405 bank service-fee schedule, including SMS (Faradeed) | 1405/05/25 = 2026-08-16 | S | https://faradeed.ir/%D8%A8%D8%AE%D8%B4-%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF-36/311641-%DA%A9%D8%A7%D8%B1%D9%85%D8%B2%D8%AF-%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A8%D8%A7%D9%86%DA%A9%DB%8C-%D8%A7%D9%84%DA%A9%D8%AA%D8%B1%D9%88%D9%86%DB%8C%DA%A9-%D8%A7%D8%A8%D9%84%D8%A7%D8%BA-%D8%B4%D8%AF-%D8%A7%D9%81%D8%B2%D8%A7%DB%8C%D8%B4-%D8%AA%D8%A7-%D8%AF%D8%B1%D8%B5%D8%AF%DB%8C-%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%AF%D8%B1-%D8%B3%D8%A7%D9%84 |

**Fraud**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| fata-mizan | FATA police warning on fake deposit receipts (Mizan, the judiciary's news agency; cyberpolice.ir unreachable) | 1403/09/13 = 2024-12-03 | S | https://www.mizanonline.ir/fa/news/4807460/ |

**Open banking and PSPs**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| finnotech-faq | FAQ: services only to legal entities (Finnotech) | undated | P | https://finnotech.ir/FAQ |
| finnotech-policy | Prohibited activities incl. VPN (Finnotech) | undated | P | https://finnotech.ir/policy |
| finnotech-statement | Account statement service notes (Finnotech docs) | undated | P | https://docs.finnotech.ir/services/account/cc-statement/ |
| finnotech-statement-op | `oak-cc-statement-get` operation (Finnotech docs) | undated | P | https://docs.finnotech.ir/operations/oak-cc-statement-get |
| finnotech-guide | Auth guide: client credentials vs authorization code (Finnotech docs) | undated | P | https://docs.finnotech.ir/guide.html |
| finnotech-inquiry | Inquiry services list (Finnotech docs); cited for what is absent | undated | P | https://docs.finnotech.ir/services/inquiry/ |
| finnotech-pricing | Plans (Finnotech) | undated | P | https://finnotech.ir/pricing |
| way2pay-api-circular | Reported CBI circular banning third-party API access to legal entities' accounts | 1402/05/12 = 2023-08-03 | S | https://way2pay.ir/316759/ |
| jibit-pid | Payment identifier product page (Jibit) | undated | P | https://www.jibit.io/payment-identifier/ |
| jibit-pip-api | PIP API spec (Jibit) | spec v1.0 | P | https://napi.jibit.ir/pip/v2/api-docs |
| jibit-enriched | Enriched bank statement (Jibit blog) | 1405/06/09 = 2026-08-31 | P | https://jibit.ir/blog/jibit-enriched-bank-statement/ |
| jibit-rules | Terms (Jibit) | undated | P | https://jibit.ir/rules/ |
| vandar-cashin-docs | Identified deposit API (Vandar docs) | undated | P | https://docs.vandar.io/customers_service/cash_in_code |
| vandar-cashin | Identified deposit product page (Vandar) | undated | P | https://vandar.io/cashin-code/ |
| vandar-terms | Terms, prohibited activities incl. VPN (Vandar) | updated 1398/10/26 = 2020-01-16 | P | https://vandar.io/terms/ |
| zibal-ebank | Corporate banking and FAQ (Zibal) | undated | P | https://zibal.ir/ebank |
| zibal-terms | قوانین و مقررات (Zibal) | © 1396–1405 | P | https://zibal.ir/privacy-policy |
| sepal-terms | Terms, prohibited activities incl. VPN (Sepal) | undated | P | https://sepal.ir/page/terms |
| way2pay-idpay | IDPay licence revocation report | 1402 | S | https://way2pay.ir/358114/ |

**Crypto**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| trongrid-trc20 | TRC20 transfers by account (TRON developer docs) | undated | P | https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address |
| trongrid-txbyid | `gettransactionbyid` (TRON developer docs) | undated | P | https://developers.tron.network/reference/gettransactionbyid |
| tron-consensus | Consensus and solidification (TRON developer docs) | undated | P | https://developers.tron.network/docs/concensus |
| tether-protocols | Supported protocols, USDT-TRC20 contract (Tether) | undated | P | https://tether.to/en/supported-protocols/ |
| tether-legal | Terms of Service, "Prohibited Jurisdiction" (Tether) | updated 2026-02-26 | P | https://tether.to/en/legal/ |
| tether-344m | Freeze in coordination with OFAC (Tether) | 2026-04-23 | P | https://tether.io/news/tether-supports-freeze-of-more-than-344-million-in-usdt-in-coordination-with-ofac-and-u-s-law-enforcement/ |
| ofac-sb0519 | Designation of Nobitex, Wallex, Bitpin, Ramzinex (US Treasury) | 2026-06-02 | P | https://home.treasury.gov/news/press-releases/sb0519 |
| nobitex-options | Public API `v2/options`: USDT networks, fees, minimums (Nobitex) | live | P | https://apiv2.nobitex.ir/v2/options |
| nobitex-stats | Public API USDT/IRT market stats (Nobitex) | live | P | https://apiv2.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls |
| nobitex-levels | User levels and limits (Nobitex) | undated | P | https://nobitex.ir/policies/user-levels/ |
| cabinet-2019 | Cabinet resolution 58144/ت55637هـ, reproduced copy | 1398/05/13 = 2019-08-04 | S | https://www.accpress.com/news/1398/05/%D8%A7%D8%B3%D8%AA%D8%AE%D8%B1%D8%A7%D8%AC-%D8%A8%DB%8C%D8%AA%E2%80%8C%DA%A9%D9%88%DB%8C%D9%86-%D8%B1%D8%B3%D9%85%D8%A7-%D9%82%D8%A7%D9%86%D9%88%D9%86%DB%8C-%D8%B4%D8%AF/ |
| majlis-mining-1401 | آیین‌نامه استخراج رمزدارایی‌ها (Majlis Research Center law database) | 1401/09/01 = 2022-11-22 | P | https://rc.majlis.ir/fa/law/show/1755460 |
| cbi-crypto-1400 | CBI statement on crypto use | 1400/02/15 = 2021-05-05 | P | https://www.cbi.ir/showitem/21636.aspx |
| cbi-crypto-1403 | CBI Supreme Board approves crypto framework | 1403/09/17 = 2024-12-07 | P | https://cbi.ir/showitem/31320.aspx |
| zoomit-cap | CBI stablecoin purchase/holding caps (Zoomit) | 1404/07/05 = 2025-09-27 | S | https://www.zoomit.ir/cryptocurrency/448864-cbi-stablecoin-limit-2025/ |

**Iranian regulation**

| Key | Source (owner) | Date | Type | URL |
|---|---|---|---|---|
| cc-limit-1405 | Card-to-card limit raised to 15M toman (Entekhab, citing the CBI) | 1405/03/12 = 2026-06-02 | S | https://www.entekhab.ir/fa/news/924053 |
| cbi-pol-1402 | سقف انتقال وجه … ساتنا، پایا و پل افزایش یافت (CBI) | 1402/12/15 = 2024-03-05 | P | https://cbi.ir/showitem/32286.aspx |
| cbi-gateway-1403 | Circular 22848/03 on non-in-person limits (CBI) | 1403/02/04 = 2024-04-23 | P | https://cbi.ir/showitem/29680.aspx |
| cbi-20-per-day | Limit of 20 incoming card transactions per day (CBI) | 1400/06/30 = 2021-09-21 | P | https://cbi.ir/showitem/22221.aspx |
| cbi-20-review | Governor orders the limit re-examined (CBI) | 1400/06/31 = 2021-09-22 | P | https://www.cbi.ir/showitem/22223.aspx |
| cbi-fee-1399 | افزایش کارمزد خدمات بانکی پس از ۱۰ سال (CBI) | 1399/08/12 = 2020-11-02 | P | https://cbi.ir/showitem/20710.aspx |
| fee-1405 | 1405 electronic-service fee schedule report (EcoIran) | 1405/05/28 = 2026-08-19 | S | https://ecoiran.com/%D8%A8%D8%AE%D8%B4-%D8%A8%D8%A7%D9%86%DA%A9-152/149814-%DA%A9%D8%A7%D8%B1%D9%85%D8%B2%D8%AF-%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A8%D8%A7%D9%86%DA%A9%DB%8C-%D8%AA%D8%BA%DB%8C%DB%8C%D8%B1-%DA%A9%D8%B1%D8%AF-%D9%87%D8%B2%DB%8C%D9%86%D9%87-%DA%A9%D8%A7%D8%B1%D8%AA-%D8%B3%D8%A7%D8%AA%D9%86%D8%A7-%D9%BE%D8%A7%DB%8C%D8%A7-%DA%86%D9%82%D8%AF%D8%B1-%D8%B4%D8%AF |
| fee-who-pays | Card-to-card fee explainer (hamrahcard.ir; states the fee by amount, sender-side) | 1398 | S | https://hamrahcard.ir/%DA%A9%D8%A7%D8%B1%D9%85%D8%B2%D8%AF-%DA%A9%D8%A7%D8%B1%D8%AA-%D8%A8%D9%87-%DA%A9%D8%A7%D8%B1%D8%AA/ |
| majlis-terminals | قانون پایانه‌های فروشگاهی و سامانه مؤدیان (Majlis Research Center law database) | 1398/07/21 = 2019-10-13 | P | https://rc.majlis.ir/fa/law/show/1348789 |
| cbi-commercial-24153 | Separating commercial from non-commercial accounts (CBI) | 1401/06/14 = 2022-09-05 | P | https://cbi.ir/showitem/24153.aspx |
| cbi-commercial-24156 | دستورالعمل ناظر بر حساب سپرده تجاری (CBI) | Shahrivar 1401 = Sep 2022 | P | https://cbi.ir/showitem/24156.aspx |
| mehr-tax-threshold | Tax Administration official on the 100-deposit / 35M-toman test (Mehr) | 1401/06/21 = 2022-09-12 | S | https://www.mehrnews.com/news/5588141 |
| majlis-gambling | Gambling/betting amendment, Penal Code Arts. 705–711 (Majlis Research Center law database) | 1401/12 = Feb–Mar 2023 | P | https://rc.majlis.ir/fa/law/show/1777243 |
| ibena-fata-2022 | FATA on rented cards and blocking (IBENA) | 1401/04/19 = 2022-07-10 | S | https://www.ibena.ir/fa/news/134380 |
| enamad-faq | eNamad FAQ 1.1, 2.6, 10.5, 12.26 (E-commerce Development Center) | undated | P | https://www.enamad.ir/Faq |
| peivast-enamad | Gateways without eNamad cut off (Peivast, quoting the directive) | 1401/08/21 = 2022-11-12 | S | https://peivast.com/p/146466 |
| digiato-shaparak-vpn | Shaparak tells payment facilitators to cut crypto/VPN merchants (Digiato) | 2021-03-03 | S | https://digiato.com/article/2021/03/03/%D8%B4%D8%A7%D9%BE%D8%B1%DA%A9-%D8%B1%D9%85%D8%B2%D8%A7%D8%B1%D8%B2-%D9%82%D8%B7%D8%B9-%D8%AF%D8%B1%DA%AF%D8%A7%D9%87 |
| scc-vpn | Supreme Council of Cyberspace resolution, Article 6 (Peivast) | 1402/12/01 = 2024-02-20 | S | https://peivast.com/p/190850 |
| majlis-ccl | قانون جرایم رایانه‌ای, Article 25 (Majlis Research Center law database) | 1388/03/05 = 2009-05-26 | P | https://rc.majlis.ir/fa/law/show/135717 |
| shaparak-iranwallet | «کیف پول ایران» launch (Shaparak) | 1405/05/17 = 2026-08-08 | P | https://shaparak.ir/fa/news/SHP-1786174808622 |

**Unreachable or unusable on 2026-09-23**
- **Android docs:** developer.android.com, developer.android.google.cn and source.android.com returned HTTP 403 (both fetch routes).
- **cyberpolice.ir:** connection refused.
- **intamedia.ir:** "temporarily unavailable".
- **shaparak.ir:** legacy `/docs`, `/tips` and `/page` URLs return an error page; `www.shaparak.ir` has TLS errors from the fetch service.
- **Other PSPs:** pay.ir (DNS), idpay.ir (expired TLS), nextpay.org (502), payping.ir (redirect loop).
- **Finnotech:** devbeta.finnotech.ir (DNS).
- **Bank sites:** bankmellat.ir (TLS name mismatch); ib.bankmellat.ir and bam.bmi.ir (DNS, from outside Iran).
- **OFAC:** ofac.treasury.gov (connection reset).
