import React, { useEffect, useState } from "react";
import { api, BASE } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

// Small controlled field helpers ------------------------------------------------
function Text({ s, set, k, label, ph, ltr }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input className="inp" value={s[k] ?? ""} onChange={(e) => set(k, e.target.value)} placeholder={ph} dir={ltr ? "ltr" : "rtl"} />
    </div>
  );
}
function Area({ s, set, k, label, mono }) {
  return (
    <div className="field">
      <label>{label}</label>
      <textarea value={s[k] ?? ""} onChange={(e) => set(k, e.target.value)}
        style={{ width: "100%", minHeight: 84, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)",
          color: "var(--txt)", border: "1px solid var(--line)", fontFamily: mono ? "monospace" : "inherit",
          fontSize: mono ? ".78rem" : ".9rem", direction: mono ? "ltr" : "rtl" }} />
    </div>
  );
}
function Toggle({ s, set, k, label }) {
  const on = String(s[k]) === "1";
  return (
    <div className="row between" style={{ padding: "6px 0" }}>
      <span style={{ fontSize: ".9rem" }}>{label}</span>
      <button className={"btn xs " + (on ? "success" : "")} onClick={() => set(k, on ? "0" : "1")}>
        {on ? "✅ روشن" : "⭕️ خاموش"}
      </button>
    </div>
  );
}
function Select({ s, set, k, label, options }) {
  return (
    <div className="field">
      <label>{label}</label>
      <select className="inp" value={String(s[k] ?? "")} onChange={(e) => set(k, e.target.value)}>
        {options.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
      </select>
    </div>
  );
}

export default function Settings() {
  const [s, setS] = useState(null);
  const [servers, setServers] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/api/settings").then((r) => { setS(r.settings); setServers(r.servers || []); })
      .catch(() => toast("خطا در بارگذاری تنظیمات", "error"));
  }, []);

  const set = (k, v) => setS((o) => ({ ...o, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      // Submit the COMPLETE snapshot — the endpoint resets any omitted field.
      const body = {};
      Object.entries(s).forEach(([k, v]) => { body[k] = v == null ? "" : v; });
      await api.form("/settings", body);
      toast("تنظیمات ذخیره شد ✅");
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  if (!s) return <Loading />;
  const srvOpts = [{ v: "0", t: "— انتخاب نشده —" }, ...servers.map((x) => ({ v: String(x.id), t: x.name + (x.is_active ? "" : " (غیرفعال)") }))];

  return (
    <div className="screen grid" style={{ gap: 16, paddingBottom: 80 }}>
      <Card title="🏷 برند و ظاهر">
        <div className="grid" style={{ gap: 8 }}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="ui_brand_name" label="نام برند" />
            <Text s={s} set={set} k="ui_logo_emoji" label="ایموجی لوگو" ltr />
          </div>
          <Text s={s} set={set} k="ui_panel_subtitle" label="زیرعنوان پنل" />
          <Text s={s} set={set} k="ui_topbar_note" label="یادداشت نوار بالا" />
        </div>
      </Card>

      <Card title="🧬 سابسکریپشن">
        <div className="grid" style={{ gap: 8 }}>
          <Text s={s} set={set} k="public_base_url" label="آدرس پایه عمومی (public base url)" ph="https://domain.com" ltr />
          <Toggle s={s} set={set} k="sub_info_enabled" label="نمایش خط اطلاعات در ساب" />
          <Toggle s={s} set={set} k="sub_info_sync_on_render" label="سینک در لحظه‌ی رندر ساب" />
          <Text s={s} set={set} k="sub_info_template" label="قالب خط اطلاعات" />
          <Text s={s} set={set} k="sub_brand_template" label="قالب خط برند" />
          <p className="muted tiny" style={{ margin: 0 }}>حداقل/حداکثر نود حذف شده؛ هر ساب روی همه‌ی نودها ساخته می‌شود.</p>
        </div>
      </Card>

      <Card title="🏢 نمایندگان">
        <div className="field"><label>حداقل شارژ اولیه نماینده (تومان)</label>
          <input className="inp" value={s.rep_min_topup ?? ""} onChange={(e) => set("rep_min_topup", e.target.value.replace(/[^\d]/g, ""))} dir="ltr" />
          <p className="muted tiny" style={{ margin: "4px 0 0" }}>نماینده تا این مبلغ شارژ نکند، «ساخت سرویس» برایش فعال نمی‌شود (ضد سوءاستفاده). در قوانین نمایندگی هم نشان داده می‌شود.</p>
        </div>
      </Card>

      <Card title="🎁 اکانت تست">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle s={s} set={set} k="test_account_enabled" label="فعال بودن اکانت تست" />
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="test_account_traffic_gb" label="حجم (GB)" ltr />
            <Text s={s} set={set} k="test_account_duration_days" label="مدت (روز)" ltr />
          </div>
        </div>
      </Card>

      <Card title="💳 اطلاعات کارت">
        <div className="grid" style={{ gap: 8 }}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="card_number" label="شماره کارت" ltr />
            <Text s={s} set={set} k="card_bank" label="بانک" />
          </div>
          <Text s={s} set={set} k="card_holder" label="نام صاحب کارت" />
        </div>
      </Card>

      <Card title="📢 عضویت اجباری و پشتیبانی">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle s={s} set={set} k="force_channel" label="عضویت اجباری در کانال" />
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="channel_username" label="یوزرنیم کانال (بدون @)" ltr />
            <Text s={s} set={set} k="support_username" label="یوزرنیم پشتیبانی" ltr />
          </div>
        </div>
      </Card>

      <Card title="🖥 سرورها و مهاجرت">
        <div className="grid" style={{ gap: 8 }}>
          <Select s={s} set={set} k="default_server_id" label="سرور پیش‌فرض" options={srvOpts} />
          <Toggle s={s} set={set} k="auto_least_loaded_server" label="انتخاب خودکار کم‌بارترین سرور" />
          <Toggle s={s} set={set} k="legacy_sync_enabled" label="سینک کانفیگ‌های قدیمی" />
        </div>
      </Card>

      <Card title="💬 متن‌های ربات">
        <div className="grid" style={{ gap: 8 }}>
          <Area s={s} set={set} k="welcome_message" label="پیام خوش‌آمد" />
          <Toggle s={s} set={set} k="maintenance_mode" label="حالت تعمیر (Maintenance)" />
          <Area s={s} set={set} k="maintenance_message" label="پیام حالت تعمیر" />
          <Area s={s} set={set} k="support_body" label="متن پشتیبانی" />
        </div>
      </Card>

      <Card title="🎨 CSS/JS سفارشی (پیشرفته)">
        <div className="grid" style={{ gap: 8 }}>
          <Area s={s} set={set} k="ui_custom_css" label="CSS سفارشی" mono />
          <Area s={s} set={set} k="ui_custom_js" label="JS سفارشی" mono />
        </div>
      </Card>

      <Card title="🔐 پیشرفته (SSL / دامنه / همه‌ی متن‌ها)"
        sub="تنظیم دامنه و گواهی SSL و بقیه‌ی متن‌های ربات فعلاً در صفحه‌ی کامل قدیمی انجام می‌شود.">
        <a className="btn sm" href={`${BASE}/settings`}>باز کردن تنظیمات کامل (SSL/دامنه) ↗</a>
      </Card>

      <div style={{ position: "sticky", bottom: 12 }}>
        <button className="btn primary" style={{ width: "100%" }} disabled={busy} onClick={save}>
          {busy ? "…" : "💾 ذخیره همه‌ی تنظیمات"}
        </button>
      </div>
    </div>
  );
}
