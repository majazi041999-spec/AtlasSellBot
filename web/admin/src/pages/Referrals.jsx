import React, { useEffect, useRef, useState } from "react";
import { api, fmt, BASE } from "../api.js";
import { Card, Loading, Empty, Modal, toast, liveNum, rawNum } from "../components/ui.jsx";

const KINDS = { wallet: "شارژ کیف پول", service: "سرویس (حجم/زمان)", gb: "حجم (قدیمی)" };

function TierModal({ tier, onClose, onSaved }) {
  const editing = !!tier;
  const r = useRef({});
  const [kind, setKind] = useState(tier?.reward_kind || "wallet");
  const [unlimited, setUnlimited] = useState(String(tier?.is_unlimited ?? 0));
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => { r.current[k] = e.target.value; };

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        referrals_needed: parseInt(r.current.referrals_needed ?? tier?.referrals_needed ?? 1) || 1,
        reward_kind: kind,
        reward_amount: rawNum(r.current.reward_amount ?? String(tier?.reward_amount ?? 0)),
        reward_gb: parseFloat(r.current.reward_gb ?? tier?.reward_gb ?? 0) || 0,
        duration_days: parseInt(r.current.duration_days ?? tier?.duration_days ?? 0) || 0,
        is_unlimited: unlimited,
        label: r.current.label ?? tier?.label ?? "",
      };
      await api.form(editing ? `/referrals/tiers/${tier.id}/edit` : `/referrals/tiers/add`, body);
      toast(editing ? "سطح ذخیره شد ✅" : "سطح اضافه شد ✅");
      onSaved();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };

  return (
    <Modal title={editing ? "✏️ ویرایش سطح پاداش" : "➕ سطح پاداش جدید"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>تعداد دعوت لازم</label>
            <input className="inp" type="number" min="1" defaultValue={tier?.referrals_needed ?? 1} onInput={set("referrals_needed")} dir="ltr" /></div>
          <div className="field"><label>نوع پاداش</label>
            <select className="inp" value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></div>
        </div>
        {kind === "wallet" && (
          <div className="field"><label>مبلغ شارژ (تومان)</label>
            <input className="inp" defaultValue={fmt(tier?.reward_amount || 0)} onInput={(e) => { liveNum(e); set("reward_amount")(e); }} dir="ltr" /></div>
        )}
        {(kind === "service" || kind === "gb") && (
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            <div className="field"><label>حجم (GB)</label>
              <input className="inp" type="number" step="0.1" defaultValue={tier?.reward_gb ?? 0} onInput={set("reward_gb")} dir="ltr" disabled={unlimited === "1"} /></div>
            <div className="field"><label>مدت (روز)</label>
              <input className="inp" type="number" defaultValue={tier?.duration_days ?? 0} onInput={set("duration_days")} dir="ltr" /></div>
            <div className="field"><label>نامحدود</label>
              <select className="inp" value={unlimited} onChange={(e) => setUnlimited(e.target.value)}>
                <option value="0">خیر</option><option value="1">بله</option></select></div>
          </div>
        )}
        <div className="field"><label>برچسب (اختیاری)</label>
          <input className="inp" defaultValue={tier?.label || ""} onInput={set("label")} /></div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

function Toggle({ on, onChange, label }) {
  return (
    <div className="row between" style={{ padding: "6px 0" }}>
      <span style={{ fontSize: ".9rem" }}>{label}</span>
      <button className={"btn xs " + (on ? "success" : "")} onClick={() => onChange(!on)}>{on ? "✅ روشن" : "⭕️ خاموش"}</button>
    </div>
  );
}

export default function Referrals() {
  const [d, setD] = useState(null);
  const [s, setS] = useState(null);
  const [tier, setTier] = useState(null);
  const [busy, setBusy] = useState("");
  const bannerRef = useRef();

  const load = () => api.get("/api/referrals").then((r) => { setD(r); setS(r.settings); }).catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);

  const set = (k, v) => setS((o) => ({ ...o, [k]: v }));
  const saveSettings = async () => {
    setBusy("save");
    try { await api.form("/referrals/settings", s); toast("ذخیره شد ✅"); load(); }
    catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };
  const tierAct = async (id, kind) => {
    if (kind === "delete" && !confirm("این سطح حذف شود؟")) return;
    try { await api.post(`/referrals/tiers/${id}/${kind}`); load(); } catch (e) { toast("خطا", "error"); }
  };
  const claimAct = async (id, kind) => {
    try { const r = await api.post(`/referrals/claims/${id}/${kind}`); toast(r.success ? "انجام شد ✅" : (r.error || "خطا"), r.success ? "success" : "error"); load(); }
    catch (e) { toast("خطا", "error"); }
  };
  const uploadBanner = async () => {
    const file = bannerRef.current?.files?.[0];
    if (!file) { toast("عکسی انتخاب نشده", "error"); return; }
    setBusy("banner");
    try { await api.form("/referrals/banner", { banner: file }); toast("بنر ذخیره شد ✅"); load(); }
    catch (e) { toast("خطا در آپلود بنر", "error"); } finally { setBusy(""); }
  };

  if (!d || !s) return <Loading />;
  const tiers = d.tiers || [];
  const claims = d.claims || [];

  const tierReward = (t) => t.reward_kind === "wallet" ? `${fmt(t.reward_amount)} ت`
    : t.is_unlimited ? `حجم نامحدود ${t.duration_days ? `/${t.duration_days} روز` : ""}`
    : `${t.reward_gb}GB ${t.duration_days ? `/${t.duration_days} روز` : ""}`;

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      {claims.length > 0 && (
        <Card title="🎁 درخواست‌های پاداش در انتظار" sub={`${claims.length} مورد`}>
          <div className="grid" style={{ gap: 8 }}>
            {claims.map((c) => (
              <div key={c.id} className="between" style={{ background: "rgba(251,191,36,.06)", border: "1px solid rgba(251,191,36,.2)", borderRadius: 12, padding: "10px 13px", gap: 10, flexWrap: "wrap" }}>
                <div><b>{c.full_name || "—"}</b> <span className="muted tiny">{c.username ? `@${c.username}` : ""} <span className="mono">{c.telegram_id}</span></span>
                  <div className="muted tiny">{c.reward_text}</div></div>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn xs success" onClick={() => claimAct(c.id, "approve")}>تایید</button>
                  <button className="btn xs danger" onClick={() => claimAct(c.id, "reject")}>رد</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="⚙️ تنظیمات رفرال">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle on={String(s.referral_enabled) === "1"} onChange={(v) => set("referral_enabled", v ? "1" : "0")} label="سیستم رفرال فعال باشد" />
          <div className="field"><label>پاداش ثابت هر دعوت موفق (تومان، ۰ = فقط سطوح)</label>
            <input className="inp" defaultValue={fmt(s.referral_per_referral_amount || 0)} onInput={(e) => { liveNum(e); set("referral_per_referral_amount", rawNum(e.target.value)); }} dir="ltr" /></div>
          <div className="field"><label>متن صفحه دعوت</label>
            <textarea value={s.referral_caption || ""} onChange={(e) => set("referral_caption", e.target.value)}
              style={{ width: "100%", minHeight: 80, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)", color: "var(--txt)", border: "1px solid var(--line)" }} /></div>
          <Toggle on={String(s.referral_reminder_enabled) === "1"} onChange={(v) => set("referral_reminder_enabled", v ? "1" : "0")} label="یادآوری به دعوت‌شده‌های بدون خرید" />
          <div className="field"><label>کد تخفیف یادآوری</label>
            <input className="inp mono" value={s.referral_reminder_code || ""} onChange={(e) => set("referral_reminder_code", e.target.value)} dir="ltr" list="rcodes" /></div>
          <button className="btn primary sm" disabled={busy === "save"} onClick={saveSettings}>💾 ذخیره تنظیمات</button>
        </div>
      </Card>

      <Card title="🏆 سطوح پاداش" right={<button className="btn sm primary" onClick={() => setTier({})}>➕ سطح جدید</button>}>
        {!tiers.length ? <Empty emoji="🏆">هنوز سطحی تعریف نشده.</Empty> : (
          <div className="grid" style={{ gap: 8 }}>
            {tiers.map((t) => (
              <div key={t.id} className="between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: "10px 13px", gap: 10, flexWrap: "wrap" }}>
                <div>
                  <b>{t.label || `${t.referrals_needed} دعوت`}</b>{" "}
                  <span className={"badge " + (t.is_active ? "b-green" : "b-red")}>{t.is_active ? "فعال" : "غیرفعال"}</span>
                  <div className="muted tiny">{t.referrals_needed} دعوت → {tierReward(t)} · {KINDS[t.reward_kind]}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn xs" onClick={() => setTier(t)}>✏️</button>
                  <button className="btn xs" onClick={() => tierAct(t.id, "toggle")}>{t.is_active ? "🔴" : "🟢"}</button>
                  <button className="btn xs danger" onClick={() => tierAct(t.id, "delete")}>🗑</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="🖼 بنر معرفی">
        <div className="row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {d.banner_set && <img src={`${BASE}/referrals/banner/preview`} alt="banner" style={{ maxWidth: 160, borderRadius: 10, border: "1px solid var(--line)" }} />}
          <input type="file" accept="image/*" ref={bannerRef} className="inp" style={{ maxWidth: 260 }} />
          <button className="btn sm" disabled={busy === "banner"} onClick={uploadBanner}>⬆️ آپلود بنر</button>
        </div>
        <p className="muted tiny" style={{ margin: "8px 0 0" }}>بنر در صفحه‌ی دعوت به کاربران نشان داده می‌شود.</p>
      </Card>

      <datalist id="rcodes">{(d.codes || []).map((c) => <option key={c} value={c} />)}</datalist>
      {tier && <TierModal tier={tier.id ? tier : null} onClose={() => setTier(null)} onSaved={() => { setTier(null); load(); }} />}
    </div>
  );
}
