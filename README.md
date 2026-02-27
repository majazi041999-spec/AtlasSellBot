# AtlasSellBot

ربات فروش + پنل وب مدیریت سرویس VPN (Atlas Account) با امکان نصب/آپدیت سریع و منیجر ترمینالی شبیه `x-ui`.

---

## ویژگی‌ها

- ربات تلگرام برای ثبت سفارش، پرداخت، مشاهده سرویس و انتقال.
- پنل وب مدیریت (FastAPI + Template) برای:
  - سرورها
  - پکیج‌ها
  - سفارش‌ها
  - کاربران
  - تنظیمات
- پشتیبانی از چند Inbound در هر سرور:
  - `inbound_id` پیش‌فرض
  - `inbound_ids` لیست اینباندهای قابل استفاده
- انتخاب Inbound در سطح پکیج (`packages.inbound_id`).
- ابزار مدیریت ترمینالی `atlas` (مشابه تجربه `x-ui`).
- اسکریپت‌های نصب/آپدیت/حذف.

---

## نصب سریع (مشابه 3x-ui)

### 1) نصب با یک خط

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh)
```

این دستور:
1. ریپو را در مسیر پیش‌فرض `/opt/AtlasSellBot` کلون می‌کند.
2. `install.sh` را اجرا می‌کند.
3. سرویس `atlas-bot` را بالا می‌آورد.
4. دستور `atlas` را روی سیستم نصب می‌کند.

### 2) آپدیت با یک خط

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) update
```

### 3) فقط تنظیم مجدد `.env`

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) configure
```

---

## تجربه شبیه x-ui در ترمینال

بعد از نصب، فقط کافی است بزنید:

```bash
atlas
```

یک منوی تعاملی باز می‌شود و تا وقتی گزینه خروج را نزنید، داخل برنامه می‌ماند.

گزینه‌های اصلی:
- مشاهده وضعیت سرویس
- start/stop/restart
- مشاهده لاگ زنده
- آپدیت امن (`pull`)
- آپدیت اجباری (`hard`)
- بازسازی سرویس systemd
- اجرای نصب مجدد
- تنظیم `.env` (توکن/ادمین/پسورد)
- حذف

حالت دستوری هم پشتیبانی می‌شود:

```bash
atlas status
atlas restart
atlas update
atlas configure
```

---

## نصب دستی (بدون bootstrap)

```bash
git clone https://github.com/majazi041999-spec/AtlasSellBot.git
cd AtlasSellBot
bash install.sh
```

> اگر `.env` وجود داشته باشد ولی مقادیر مهم خالی/پیش‌فرض باشند، نصب‌گر دوباره از شما می‌پرسد.

فقط تنظیم `.env`:

```bash
bash install.sh --configure-only
```

---

## مدیریت سرویس

```bash
systemctl status atlas-bot
systemctl restart atlas-bot
journalctl -u atlas-bot -f
```

---

## ساختار اسکریپت‌ها

- `bootstrap.sh`:
  - ورودی one-liner از `curl`
  - install / update / configure / restart / status / uninstall
- `install.sh`:
  - نصب وابستگی‌ها
  - ساخت venv
  - نصب پکیج‌ها
  - تنظیم `.env`
  - نصب سرویس systemd
  - نصب دستور `atlas`
- `atlas_menu.sh`:
  - منوی تعاملی مدیریت (سبک x-ui)
- `update.sh`:
  - آپدیت امن با مدیریت تغییرات لوکال (auto-stash)
- `uninstall.sh`:
  - حذف سرویس و فایل‌های runtime

---

## تنظیمات مهم `.env`

حداقل این موارد باید درست باشند:

```env
BOT_TOKEN=...
ADMIN_IDS=123456789
WEB_ADMIN_PASSWORD=...
WEB_SECRET_PATH=AtlasPanel2024
WEB_PORT=8000
JWT_SECRET=...
```

---

## پنل وب

آدرس پنل:

```text
http://SERVER_IP:WEB_PORT/WEB_SECRET_PATH/
```

مثال پیش‌فرض:

```text
http://1.2.3.4:8000/AtlasPanel2024/
```

---

## نکات چند Inbound

- در **Servers**:
  - `Inbound ID` = پیش‌فرض سرور
  - `Inbound IDs` = لیست مجاز مثل `1,2,3`
- در **Packages**:
  - `Inbound ID`:
    - `0` یعنی پیش‌فرض سرور
    - عدد > 0 یعنی تلاش برای استفاده از همان inbound روی سرور انتخابی

در تایید سفارش، اگر inbound پکیج در لیست inboundهای سرور باشد، همان استفاده می‌شود؛ در غیر این صورت fallback به inbound پیش‌فرض سرور انجام می‌شود.

---

## حذف کامل

```bash
bash uninstall.sh
```

حذف کامل دایرکتوری پروژه:

```bash
bash uninstall.sh --purge-self --force
```

---

## Troubleshooting

### `atlas: command not found`

نصب دستور `atlas` را دوباره انجام دهید:

```bash
bash install.sh --configure-only
```

یا:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh)
```

### هنگام update خطای local changes می‌گیرید

از آپدیت امن استفاده کنید:

```bash
atlas update
```

یا:

```bash
bash update.sh pull
```

---

## License

For internal/private use unless otherwise specified by repository owner.
