import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

// Keys are the exact setting names core/client_app.py allowlists. Anything not
// in that allowlist is silently ignored by the server, so the two lists must
// stay in step — that is deliberate: a typo here cannot reach an unrelated
// setting.
const EMPTY = {
  clientapp_promo_enabled: "0",
  clientapp_promo_id: "",
  clientapp_promo_title: "",
  clientapp_promo_text: "",
  clientapp_promo_button: "",
  clientapp_promo_url: "",
  clientapp_promo_image_url: "",
  clientapp_version_code: "0",
  clientapp_version_name: "",
  clientapp_version_notes: "",
  clientapp_version_mandatory: "0",
  clientapp_api_key: "",
};

/**
 * Says whether the app is actually being served a banner, and if not, why.
 *
 * The two failure modes are silent from the panel's point of view — the fields
 * look filled in either case — so the reason comes from the server, computed by
 * the same code that builds the app's payload. Guessing it here could disagree
 * with reality, which is exactly the confusion this is meant to end.
 */
function PromoStatus({ status }) {
  const map = {
    live: { c: "#2bd98a", t: "✅ بنر روی اپ نمایش داده می‌شود." },
    disabled: { c: "#ffb020", t: "⚠️ تیک «بنر فعال باشد» زده نشده — اپ چیزی نمی‌بیند." },
    empty: { c: "#ffb020", t: "⚠️ عنوان و متن هر دو خالی‌اند — حداقل یکی لازم است." },
  };
  const s = map[status];
  if (!s) return null;
  return (
    <div style={{
      background: s.c + "1f", border: "1px solid " + s.c + "55",
      color: s.c, borderRadius: 12, padding: "10px 12px", fontSize: 13,
    }}>{s.t}</div>
  );
}

export default function ClientApp() {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.get("/api/client/config")
      .then((d) => setCfg({ ...EMPTY, ...d }))
      .catch((e) => toast(e.message || "خطا در خواندن تنظیمات", "error"));
  };
  useEffect(load, []);

  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? (e.target.checked ? "1" : "0") : e.target.value;
    setCfg((s) => ({ ...s, [k]: v }));
  };

  const save = async () => {
    setBusy(true);
    try {
      const d = await api.post("/api/client/config", cfg);
      // The server echoes back what it actually stored, so a value it rejected
      // (a non-https URL, a malformed hash) visibly reverts instead of looking
      // saved until the next page load.
      setCfg({ ...EMPTY, ...(d.config || {}) });
      toast("ذخیره شد ✅");
    } catch (e) {
      toast(e.message || "ذخیره نشد", "error");
    } finally {
      setBusy(false);
    }
  };

  if (!cfg) return <Loading />;

  const promoOn = cfg.clientapp_promo_enabled === "1";
  const versionCode = parseInt(cfg.clientapp_version_code || "0", 10) || 0;

  return (
    <div className="grid" style={{ gap: 14 }}>
      <Card
        title="📣 بنر تبلیغاتی اپ اندروید"
        sub="در صفحهٔ اصلی برنامه نمایش داده می‌شود. کاربر می‌تواند ببندد و تا وقتی «شناسه» عوض نشود دیگر نمی‌بیند."
      >
        <div className="grid" style={{ gap: 10 }}>
          <PromoStatus status={cfg._promo_status} />

          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={promoOn} onChange={set("clientapp_promo_enabled")} />
            <span>بنر فعال باشد</span>
          </label>

          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="field">
              <label>عنوان</label>
              <input className="inp" value={cfg.clientapp_promo_title}
                     onChange={set("clientapp_promo_title")} placeholder="تخفیف ویژه" />
            </div>
            <div className="field">
              <label>متن دکمه</label>
              <input className="inp" value={cfg.clientapp_promo_button}
                     onChange={set("clientapp_promo_button")} placeholder="دریافت کد" />
            </div>
          </div>

          <div className="field">
            <label>متن</label>
            <textarea className="inp" rows={2} value={cfg.clientapp_promo_text}
                      onChange={set("clientapp_promo_text")} placeholder="۲۰٪ تخفیف روی تمدید" />
          </div>

          <div className="field">
            <label>لینک دکمه — فقط https</label>
            <input className="inp" dir="ltr" value={cfg.clientapp_promo_url}
                   onChange={set("clientapp_promo_url")} placeholder="https://t.me/atlas_account_bot" />
          </div>

          <div className="field">
            <label>
              شناسهٔ بنر
              <span style={{ opacity: 0.6, fontSize: 12 }}>
                {" "}— برای نمایش دوبارهٔ بنر به کسانی که بسته‌اند، این را عوض کن
              </span>
            </label>
            <input className="inp" dir="ltr" value={cfg.clientapp_promo_id}
                   onChange={set("clientapp_promo_id")} placeholder="خالی = خودکار از روی متن" />
          </div>
        </div>
      </Card>

      <Card
        title="⬆️ نسخهٔ اپ"
        sub="برنامه فقط نسخهٔ جدید را اعلام می‌کند و کاربر را به کانال می‌فرستد؛ خودش دانلود و نصب نمی‌کند."
      >
        <div className="grid" style={{ gap: 10 }}>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            <div className="field">
              <label>versionCode</label>
              <input className="inp" type="number" dir="ltr" value={cfg.clientapp_version_code}
                     onChange={set("clientapp_version_code")} />
            </div>
            <div className="field">
              <label>نام نسخه</label>
              <input className="inp" dir="ltr" value={cfg.clientapp_version_name}
                     onChange={set("clientapp_version_name")} placeholder="1.1.0" />
            </div>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={cfg.clientapp_version_mandatory === "1"}
                     onChange={set("clientapp_version_mandatory")} />
              <span>اجباری</span>
            </label>
          </div>

          <div style={{ opacity: 0.75, fontSize: 13, lineHeight: 1.9 }}>
            برنامه فایلی دانلود یا نصب نمی‌کند. وقتی versionCode اینجا از نسخهٔ
            نصب‌شدهٔ کاربر بیشتر باشد، پیام «نسخهٔ جدید موجود است» می‌آید و دکمه‌اش
            کاربر را مستقیم به کانال تلگرام می‌برد.
          </div>

          <div className="field">
            <label>تغییرات این نسخه</label>
            <textarea className="inp" rows={2} value={cfg.clientapp_version_notes}
                      onChange={set("clientapp_version_notes")} placeholder="چه چیزی عوض شده" />
          </div>

          {versionCode === 0 && (
            <div style={{ opacity: 0.7, fontSize: 13 }}>
              versionCode صفر یعنی «نسخه‌ای منتشر نشده» — اپ آن را به‌روز فرض می‌کند و چیزی نشان نمی‌دهد.
            </div>
          )}
        </div>
      </Card>

      <Card
        title="🔑 کلید API اپ"
        sub="اختیاری. اگر پرش کنی، اپ آن را در هدر X-Atlas-Key می‌فرستد و درخواست‌های بدون آن رد می‌شوند."
      >
        <div className="field">
          <input className="inp" dir="ltr" value={cfg.clientapp_api_key}
                 onChange={set("clientapp_api_key")} placeholder="خالی = بدون کلید" />
        </div>
        <div style={{ opacity: 0.7, fontSize: 13, marginTop: 8, lineHeight: 1.8 }}>
          ⚠️ این «امنیت» واقعی نمی‌دهد: هر کلید ثابتی داخل APK با apktool در چند دقیقه استخراج
          می‌شود. فقط یک سرعت‌گیر ضد اسکرپر است. به همین دلیل این اندپوینت‌ها هیچ دادهٔ کاربری
          برنمی‌گردانند — فقط بنر و شمارهٔ نسخه.
          <br />
          اگر کلید را اینجا عوض کنی، باید در <code>atlas.properties</code> اپ هم عوض شود و
          بیلد جدید بگیری، وگرنه نسخه‌های قدیمی بنر و آپدیت را نمی‌بینند.
        </div>
      </Card>

      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn primary" disabled={busy} onClick={save}>
          {busy ? "در حال ذخیره…" : "ذخیره"}
        </button>
        <button className="btn" disabled={busy} onClick={load}>بازخوانی</button>
      </div>
    </div>
  );
}
