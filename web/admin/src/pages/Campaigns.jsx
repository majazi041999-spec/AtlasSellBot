import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Stat, Loading, toast } from "../components/ui.jsx";

function Toggle({ on, onChange, label }) {
  return (
    <div className="row between" style={{ padding: "6px 0" }}>
      <span style={{ fontSize: ".9rem" }}>{label}</span>
      <button className={"btn xs " + (on ? "success" : "")} onClick={() => onChange(!on)}>{on ? "✅ روشن" : "⭕️ خاموش"}</button>
    </div>
  );
}

export default function Campaigns() {
  const [d, setD] = useState(null);
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState("");

  const load = () => api.get("/api/campaigns").then((r) => { setD(r); setS(r.settings); }).catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);

  const set = (k, v) => setS((o) => ({ ...o, [k]: v }));
  const save = async () => {
    setBusy("save");
    try { await api.form("/campaigns/settings", s); toast("ذخیره شد ✅"); load(); }
    catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };
  const run = async (name) => {
    setBusy(name);
    try { const r = await api.post(`/campaigns/${name}/run`); toast(`ارسال شد: ${fmt(r.sent || 0)} پیام ✅`); load(); }
    catch (e) { toast(e.message || "خطا در اجرا", "error"); } finally { setBusy(""); }
  };
  const reset = async (name) => {
    if (!confirm("فلگ ارسال این کمپین ریست شود؟ (به همه دوباره ارسال می‌شود)")) return;
    try { const r = await api.post(`/campaigns/${name}/reset`); toast(`ریست شد: ${fmt(r.cleared || 0)}`); load(); }
    catch (e) { toast("خطا", "error"); }
  };

  if (!d || !s) return <Loading />;
  const kpi = d.kpi || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="grid stat-grid">
        <Stat icon="💰" value={fmt(kpi.revenue)} label="درآمد کمپین‌ها (ت)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
        <Stat icon="🎯" value={fmt(kpi.conversions)} label="تبدیل‌ها" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="📨" value={fmt(kpi.sent)} label="پیام ارسال‌شده" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
        <Stat icon="🎟" value={fmt(kpi.discount)} label="تخفیف داده‌شده (ت)" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
      </div>

      <Card title="📊 عملکرد کمپین‌ها">
        <div className="grid" style={{ gap: 10 }}>
          {(d.overview || []).map((c) => (
            <div key={c.campaign} className="between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: "10px 13px", gap: 10, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0 }}>
                <b>{c.label}</b>
                <div className="muted tiny">ارسال: {fmt(c.sent)} · تبدیل: {fmt(c.conversions)} · درآمد: {fmt(c.revenue)} ت</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                {(c.campaign === "trial2paid" || c.campaign === "winback") && (
                  <>
                    <button className="btn xs primary" disabled={busy === c.campaign} onClick={() => run(c.campaign)}>▶️ اجرا</button>
                    <button className="btn xs" onClick={() => reset(c.campaign)}>ریست</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="🎁 کمپین «تست → خرید»">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle on={String(s.campaign_trial_enabled) === "1"} onChange={(v) => set("campaign_trial_enabled", v ? "1" : "0")} label="فعال باشد" />
          <div className="field"><label>کد تخفیف پیشنهادی</label>
            <input className="inp mono" value={s.campaign_trial_code || ""} onChange={(e) => set("campaign_trial_code", e.target.value)} dir="ltr" list="codes" /></div>
          <div className="field"><label>متن پیام</label>
            <textarea value={s.campaign_trial_template || ""} onChange={(e) => set("campaign_trial_template", e.target.value)}
              style={{ width: "100%", minHeight: 90, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)", color: "var(--txt)", border: "1px solid var(--line)" }} /></div>
        </div>
      </Card>

      <Card title="🔄 کمپین «بازگشت مشتری» (Winback)">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle on={String(s.campaign_winback_enabled) === "1"} onChange={(v) => set("campaign_winback_enabled", v ? "1" : "0")} label="فعال باشد" />
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="field"><label>کد تخفیف</label>
              <input className="inp mono" value={s.campaign_winback_code || ""} onChange={(e) => set("campaign_winback_code", e.target.value)} dir="ltr" list="codes" /></div>
            <div className="field"><label>بعد از چند روز غیرفعالی</label>
              <input className="inp" type="number" min="1" value={s.campaign_winback_days || 14} onChange={(e) => set("campaign_winback_days", e.target.value)} dir="ltr" /></div>
          </div>
          <div className="field"><label>متن پیام</label>
            <textarea value={s.campaign_winback_template || ""} onChange={(e) => set("campaign_winback_template", e.target.value)}
              style={{ width: "100%", minHeight: 90, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)", color: "var(--txt)", border: "1px solid var(--line)" }} /></div>
        </div>
      </Card>

      <datalist id="codes">{(d.codes || []).map((c) => <option key={c} value={c} />)}</datalist>
      <div style={{ position: "sticky", bottom: 12 }}>
        <button className="btn primary" style={{ width: "100%" }} disabled={busy === "save"} onClick={save}>💾 ذخیره تنظیمات کمپین‌ها</button>
      </div>
    </div>
  );
}
