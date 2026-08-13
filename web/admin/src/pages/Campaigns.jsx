import React, { useEffect, useRef, useState } from "react";
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

const TA = { width: "100%", minHeight: 90, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)", color: "var(--txt)", border: "1px solid var(--line)" };

function copyText(t) {
  const done = () => toast("کپی شد ✅");
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(t).then(done).catch(() => {});
  else {
    const el = document.createElement("textarea");
    el.value = t; document.body.appendChild(el); el.select();
    try { document.execCommand("copy"); done(); } catch {}
    el.remove();
  }
}

/* One targeted campaign: collapsed row → inline editor. */
function CustomCampaign({ c, segments, counts, codes, onChanged, startOpen }) {
  const [open, setOpen] = useState(!!startOpen);
  const [f, setF] = useState(null); // edit buffer (photo only present when re-picked)
  const [busy, setBusy] = useState("");
  const fileRef = useRef(null);

  const edit = () => {
    setF({ id: c.id || 0, title: c.title || "", emoji: c.emoji || "🎯", segment: c.segment || "all",
           message: c.message || "", code: c.code || "", image_prompt: c.image_prompt || "", notes: c.notes || "" });
    setOpen(true);
  };
  const set = (k, v) => setF((o) => ({ ...o, [k]: v }));

  const pickPhoto = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast("عکس باید کمتر از ۲ مگابایت باشد", "error"); return; }
    const r = new FileReader();
    r.onload = () => set("photo", String(r.result || ""));
    r.readAsDataURL(file);
  };

  const save = async () => {
    setBusy("save");
    try { await api.post("/api/campaigns/custom", f); toast("ذخیره شد ✅"); setOpen(false); setF(null); onChanged(); }
    catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(""); }
  };
  const del = async () => {
    if (!confirm(`کمپین «${c.title}» حذف شود؟`)) return;
    try { await api.post(`/api/campaigns/custom/${c.id}/delete`); toast("حذف شد"); onChanged(); } catch { toast("خطا", "error"); }
  };
  const send = async () => {
    const n = counts?.[c.segment] ?? "?";
    if (!confirm(`ارسال به سگمنت «${segLabel}» (${n} نفر)؟\nهر کاربر فقط یک‌بار این کمپین را می‌گیرد.`)) return;
    setBusy("send");
    try { const r = await api.post(`/api/campaigns/custom/${c.id}/send`); toast(`ارسال شد: ${fmt(r.sent || 0)} پیام ✅`); onChanged(); }
    catch (e) { toast(e.message || "خطا در ارسال", "error"); } finally { setBusy(""); }
  };

  const segLabel = segments.find((s) => s.key === c.segment)?.label || c.segment;
  const sent = c.status === "sent";

  return (
    <div style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: "10px 13px" }}>
      <div className="between" style={{ gap: 10, flexWrap: "wrap", cursor: "pointer" }} onClick={() => (open ? (setOpen(false), setF(null)) : edit())}>
        <div style={{ minWidth: 0 }}>
          <b>{c.emoji} {c.title}</b>
          <div className="muted tiny">
            {segLabel} · {fmt(counts?.[c.segment] ?? 0)} نفر
            {c.code ? <> · 🎟 <span className="mono">{c.code}</span></> : null}
            {c.has_photo ? " · 🖼 عکس دارد" : ""}
          </div>
        </div>
        <div className="row" style={{ gap: 6, alignItems: "center" }}>
          {sent
            ? <span className="tiny" style={{ color: "#34d399" }}>✅ ارسال: {fmt(c.sent_count)}{c.conversions ? ` · تبدیل: ${fmt(c.conversions)} · ${fmt(c.revenue)} ت` : ""}</span>
            : <span className="tiny" style={{ color: "#fbbf24" }}>📝 پیش‌نویس</span>}
          <span className="muted">{open ? "▴" : "▾"}</span>
        </div>
      </div>

      {open && f && (
        <div className="grid" style={{ gap: 8, marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 10 }} onClick={(e) => e.stopPropagation()}>
          <div className="grid" style={{ gridTemplateColumns: "60px 1fr 1fr", gap: 10 }}>
            <div className="field"><label>ایموجی</label><input className="inp" value={f.emoji} onChange={(e) => set("emoji", e.target.value)} /></div>
            <div className="field"><label>عنوان</label><input className="inp" value={f.title} onChange={(e) => set("title", e.target.value)} /></div>
            <div className="field"><label>کد تخفیف ({"{code}"})</label>
              <input className="inp mono" dir="ltr" list="codes" value={f.code} onChange={(e) => set("code", e.target.value)} /></div>
          </div>
          <div className="field"><label>مخاطبان (سگمنت)</label>
            <select className="inp" value={f.segment} onChange={(e) => set("segment", e.target.value)}>
              {segments.map((s) => <option key={s.key} value={s.key}>{s.label} — {fmt(counts?.[s.key] ?? 0)} نفر</option>)}
            </select></div>
          <div className="field"><label>متن پیام — جای‌گذاری‌ها: {"{name} {code} {brand}"}</label>
            <textarea style={{ ...TA, minHeight: 150 }} value={f.message} onChange={(e) => set("message", e.target.value)} /></div>

          <div className="field"><label>عکس کمپین (اختیاری — کپشن بالای ۱۰۲۴ کاراکتر جدا ارسال می‌شود)</label>
            <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button className="btn xs" onClick={() => fileRef.current?.click()}>🖼 انتخاب عکس</button>
              <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={pickPhoto} />
              {f.photo ? <img src={f.photo} alt="" style={{ height: 54, borderRadius: 8 }} /> : (c.has_photo ? <span className="muted tiny">عکس ذخیره‌شده دارد ✔</span> : <span className="muted tiny">عکسی ندارد</span>)}
              {(f.photo || c.has_photo) && <button className="btn xs danger" onClick={() => set("photo", "")}>حذف عکس</button>}
            </div></div>

          {f.image_prompt ? (
            <div className="field">
              <label className="row between" style={{ gap: 8 }}>
                <span>🎨 پرامپت ساخت عکس (برای ایجنت تصویر)</span>
                <button className="btn xs" onClick={() => copyText(f.image_prompt)}>📋 کپی پرامپت</button>
              </label>
              <textarea style={{ ...TA, minHeight: 70, direction: "ltr", fontSize: ".78rem" }} value={f.image_prompt} onChange={(e) => set("image_prompt", e.target.value)} />
            </div>
          ) : null}

          {f.notes ? (
            <div style={{ background: "rgba(124,111,255,.08)", border: "1px dashed rgba(124,111,255,.4)", borderRadius: 10, padding: "8px 11px", fontSize: ".82rem", lineHeight: 1.9 }}>
              💡 <b>استراتژی:</b> {f.notes}
            </div>
          ) : null}

          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <button className="btn xs primary" disabled={busy === "save"} onClick={save}>💾 ذخیره</button>
            {c.id ? <button className="btn xs success" disabled={busy === "send"} onClick={send}>{busy === "send" ? "در حال ارسال..." : "▶️ ارسال کمپین"}</button> : null}
            {c.id ? <button className="btn xs danger" onClick={del}>🗑 حذف</button> : null}
            {sent ? <span className="muted tiny">آخرین ارسال: {c.sent_at}</span> : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Campaigns() {
  const [d, setD] = useState(null);
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => api.get("/api/campaigns").then((r) => { setD(r); setS(r.settings); setAdding(false); }).catch(() => setD({ error: true }));
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
  const segments = d.segments || [];
  const counts = d.segment_counts || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="grid stat-grid">
        <Stat icon="💰" value={fmt(kpi.revenue)} label="درآمد کمپین‌ها (ت)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
        <Stat icon="🎯" value={fmt(kpi.conversions)} label="تبدیل‌ها" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="📨" value={fmt(kpi.sent)} label="پیام ارسال‌شده" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
        <Stat icon="🎟" value={fmt(kpi.discount)} label="تخفیف داده‌شده (ت)" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
      </div>

      <Card title="🎯 کمپین‌های هدفمند" sub="بر اساس داده فروش خودت طراحی شده؛ ویرایش کن، عکس بگذار و بفرست. هر کاربر هر کمپین را فقط یک‌بار می‌گیرد."
            right={<button className="btn xs primary" onClick={() => setAdding(true)}>+ کمپین جدید</button>}>
        <div className="grid" style={{ gap: 10 }}>
          {adding && (
            <CustomCampaign key="new" startOpen
              c={{ id: 0, title: "", emoji: "🎯", segment: "all", message: "", code: "", image_prompt: "", notes: "", status: "draft" }}
              segments={segments} counts={counts} codes={d.codes} onChanged={load} />
          )}
          {(d.custom || []).map((c) => (
            <CustomCampaign key={c.id} c={c} segments={segments} counts={counts} codes={d.codes} onChanged={load} />
          ))}
          {!(d.custom || []).length && !adding && <div className="muted tiny">هنوز کمپینی نداری — «+ کمپین جدید» را بزن.</div>}
        </div>
      </Card>

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
            <textarea value={s.campaign_trial_template || ""} onChange={(e) => set("campaign_trial_template", e.target.value)} style={TA} /></div>
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
            <textarea value={s.campaign_winback_template || ""} onChange={(e) => set("campaign_winback_template", e.target.value)} style={TA} /></div>
        </div>
      </Card>

      <datalist id="codes">{(d.codes || []).map((c) => <option key={c} value={c} />)}</datalist>
      <div style={{ position: "sticky", bottom: 12 }}>
        <button className="btn primary" style={{ width: "100%" }} disabled={busy === "save"} onClick={save}>💾 ذخیره تنظیمات کمپین‌ها</button>
      </div>
    </div>
  );
}
