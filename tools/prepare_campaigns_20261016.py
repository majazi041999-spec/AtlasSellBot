"""Prepare campaign artwork/drafts without sending messages or changing rewards.

Dry-run by default. Run on the bot host with --apply after deploying the media
fix. Existing images, delivery history, discounts and referral rules survive.
"""
import argparse
import base64
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.campaign_media import campaign_photo_bytes

REFERRAL_MESSAGE = (
    "🎁 {name} عزیز، با معرفی دوستات از {brand} هدیه بگیر!\n\n"
    "دوستت باید با لینک اختصاصی تو عضو شود و اولین خریدش را انجام دهد.\n\n"
    "{referral_rewards}\n\n"
    "🔗 لینک دعوت تو:\n{referral_link}\n\n"
    "جزئیات و درخواست جایزه: منوی «دعوت دوستان»"
)

NEW_CAMPAIGNS = [
    {
        "slug": "service_toolkit_20261016", "title": "ابزارهای سرویس همیشه در دسترس", "emoji": "🧾",
        "segment": "active_subs",
        "message": (
            "🧾 {name} عزیز، QR سرویس و لینکت همیشه دم دستته!\n\n"
            "🤖 توی ربات: «سرویس‌های من» ← انتخاب سرویس ← «نمایش QR اشتراک»\n"
            "📱 توی مینی‌اپ: «سرویس‌ها» ← «نمایش QR»\n\n"
            "برای افزودن سرویس روی دستگاه دیگرت، QR را از برنامهٔ اتصال اسکن کن. "
            "اگر همین گوشی را استفاده می‌کنی، لینک اشتراک را کپی کن.\n\n"
            "🔄 بعد از اطلاع‌رسانی تغییر سرورها، اشتراک را داخل برنامه‌ات به‌روز کن.\n"
            "🎬 آموزش‌ها: https://t.me/atlastutorial"
        ),
        "notes": "آموزش قابلیت آماده‌شده QR و کاهش درخواست پشتیبانی؛ مخاطب اشتراک فعال. پیش‌نویس، فقط ارسال دستی مدیریت.",
    },
    {
        "slug": "choose_route_20261016", "title": "انتخاب مسیر مناسب اینترنتت", "emoji": "📶",
        "segment": "active_subs",
        "message": (
            "📶 {name} عزیز، اگر اتصال روی اینترنتت کند شده، یک مسیر دیگه را هم امتحان کن.\n\n"
            "🇫🇮 Finland Frost و 🇹🇷 Turkey Nitro هم توی اشتراکت در دسترس‌اند.\n"
            "🔄 اول اشتراک را در برنامه به‌روز کن؛ بعد سرورها را روی اینترنت خودت تست کن.\n\n"
            "📊 از بخش «وضعیت سرورها» در ربات، وضعیت فعلی را بررسی کن. "
            "عملکرد هر مسیر به اپراتور و شرایط لحظه‌ای شبکه بستگی دارد.\n\n"
            "🛠 اگر همچنان مشکل داشتی، نام سرور، اپراتور و برنامهٔ اتصال را برای پشتیبانی بفرست."
        ),
        "notes": "معرفی مسیرهای موجود و ابزار وضعیت؛ بدون ادعای تعرفه داخلی، تضمین سرعت یا اشاره به تونل. پیش‌نویس ارسال دستی.",
    },
]


def prepare(database: Path, apply: bool) -> dict:
    manifest = json.loads((ROOT / "assets/campaigns/manifest.json").read_text(encoding="utf-8"))
    pictures = {}
    for item in manifest:
        data = (ROOT / "assets/campaigns" / item["file"]).read_bytes()
        value = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        campaign_photo_bytes(value)
        pictures[item["campaign_slug"]] = value
    connection = sqlite3.connect(str(database) if apply else "file:" + str(database) + "?mode=ro", uri=not apply)
    connection.row_factory = sqlite3.Row
    try:
        existing = {row["slug"]: dict(row) for row in connection.execute("SELECT * FROM custom_campaigns")}
        result = {"apply": apply, "new_drafts": [c["title"] for c in NEW_CAMPAIGNS if c["slug"] not in existing],
                  "fill_missing_images": [slug for slug in pictures if slug in existing and not existing[slug].get("photo")],
                  "preserved_images": [c["title"] for c in existing.values() if c.get("photo")], "messages_sent": 0}
        if not apply:
            return result
        connection.execute("BEGIN IMMEDIATE")
        for camp in NEW_CAMPAIGNS:
            connection.execute(
                "INSERT INTO custom_campaigns(slug,title,emoji,segment,message,notes,status) VALUES(?,?,?,?,?,?,'draft') ON CONFLICT(slug) DO NOTHING",
                tuple(camp[key] for key in ("slug", "title", "emoji", "segment", "message", "notes")),
            )
        for slug, value in pictures.items():
            connection.execute("UPDATE custom_campaigns SET photo=? WHERE slug=? AND COALESCE(photo,'')=''", (value, slug))
        connection.execute("UPDATE custom_campaigns SET message=? WHERE slug='referral_push'", (REFERRAL_MESSAGE,))
        # Automatic followups have separate settings; custom-card media was
        # never an implicit source for them. Initialize once, preserve edits.
        winback = existing.get("winback_blast", {}).get("photo") or pictures["renewal_save"]
        campaign_photo_bytes(winback)
        for key, value in [("campaign_trial_photo", pictures["trial_push"]), ("campaign_winback_photo", winback)]:
            connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING", (key, value))
        connection.commit()
        result["campaigns_with_photo"] = connection.execute("SELECT COUNT(*) FROM custom_campaigns WHERE COALESCE(photo,'')<>''").fetchone()[0]
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", type=Path, default=ROOT / "atlas.db")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(prepare(args.db, args.apply), ensure_ascii=False))
