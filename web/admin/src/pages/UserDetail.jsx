import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Modal, Stat, toast, liveNum, rawNum } from "../components/ui.jsx";

const ROLES = { none: "کاربر عادی", finance: "ادمین ساده", full: "ادمین کل" };
const gb = (b) => (Number(b || 0) / 1024 ** 3).toFixed(2);
const tsInput = (ms) => { if (!ms) return ""; const d = new Date(Number(ms)); const p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };

function EditSubModal({ p, onClose, onSaved }) {
  const email = useRef(); const traffic = useRef(); const expire = useRef(); const [active, setActive] = useState(String(p.is_active)); const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.form(`/subs/profiles/${p.id}/edit`, { email: email.current.value, traffic_gb: traffic.current.value, expire_at: expire.current.value, is_active: active }); toast("ذخیره شد ✅"); onSaved(); }
    catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };
  return (
    <Modal title={`✏️ ویرایش سرویس — ${p.name}`} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="field"><label>ایمیل/شناسه</label><input className="inp mono" ref={email} defaultValue={p.email} dir="ltr" /></div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>حجم (GB)</label><input className="inp" ref={traffic} type="number" step="0.1" defaultValue={p.traffic_gb} dir="ltr" /></div>
          <div className="field"><label>وضعیت</label><select className="inp" value={active} onChange={(e) => setActive(e.target.value)}><option value="1">فعال</option><option value="0">غیرفعال</option></select></div>
        </div>
        <div className="field"><label>انقضا</label><input className="inp" ref={expire} type="datetime-local" defaultValue={tsInput(p.expire_timestamp)} dir="ltr" /></div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function UserDetail({ uid, go }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState("");
  const [editSub, setEditSub] = useState(null);
  const disc = useRef(); const ppg = useRef(); const unl = useRef(); const balAmt = useRef(); const balNote = useRef(); const repBrand = useRef();
  const [role, setRole] = useState("none");

  const load = () => api.get(`/api/users/${uid}`).then((r) => { setD(r); setRole(r.user.admin_role || "none"); }).catch(() => setD({ error: true }));
  useEffect(() => { load(); }, [uid]);

  if (!d) return <Loading />;
  if (d.error) return <Card><Empty emoji="🚫">کاربر یافت نشد</Empty></Card>;
  const u = d.user, fin = d.rep_financials, b = d.business || {};

  const post = async (key, path, body, opt = {}) => {
    setBusy(key);
    try { const r = opt.form ? await api.form(path, body) : await api.post(path, body); toast("انجام شد ✅"); await load(); return r; }
    catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };
  const savePricing = () => post("price", `/users/${uid}/pricing`, { discount_percent: parseFloat(disc.current.value || 0) || 0, price_per_gb: rawNum(ppg.current.value), unlimited_price: rawNum(unl.current.value) });
  const adjustBal = () => { const amount = rawNum(balAmt.current.value); if (!amount) return toast("مبلغ؟", "error"); post("bal", `/users/${uid}/balance_adjust`, { amount, note: balNote.current.value || "manual" }).then(() => { balAmt.current.value = ""; }); };
  const saveRole = () => post("role", `/users/${uid}/admin_role`, { role });
  const saveRepBrand = () => post("repbrand", `/users/${uid}/rep_brand`, { brand: repBrand.current.value });
  const subAct = (id, kind, cm) => { if (cm && !confirm(cm)) return; post("sub" + id + kind, `/subs/profiles/${id}/${kind}`); };
  const cfgAct = (id, kind, cm) => { if (cm && !confirm(cm)) return; post("cfg" + id + kind, `/configs/${id}/${kind}`); };
  const copy = (url) => navigator.clipboard?.writeText(url).then(() => toast("کپی شد ✅"));

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row" style={{ gap: 10 }}>
        <button className="btn sm" onClick={() => go("/users")}>‹ بازگشت</button>
        <div style={{ fontWeight: 800, fontSize: "1.05rem" }}>{u.full_name || "—"}</div>
      </div>

      <Card>
        <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          {u.is_blocked ? <span className="badge b-red">🔴 بلاک</span> : <span className="badge b-green">🟢 فعال</span>}
          {u.is_wholesale ? <span className="badge b-purple">نماینده</span> : (u.wholesale_request_pending ? <span className="badge b-yellow">درخواست نمایندگی</span> : null)}
          {u.rep_brand_name ? <span className="badge b-blue">🏷️ {u.rep_brand_name}</span> : null}
          {u.admin_role !== "none" ? <span className="badge b-blue">{ROLES[u.admin_role]}</span> : null}
        </div>
        <div className="muted tiny">{u.username ? `@${u.username} · ` : ""}<span className="mono">{u.telegram_id}</span> · عضویت: {(u.created_at || "").slice(0, 10)}</div>
        <div className="grid stat-grid" style={{ marginTop: 12 }}>
          <Stat icon="💳" value={fmt(u.balance_toman)} label="کیف پول (ت)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
          <Stat icon="🧬" value={fmt(d.profiles.length)} label="سرویس‌ها" grad="linear-gradient(135deg,#34d399,#10b981)" />
          <Stat icon="✅" value={fmt(b.approved_orders || 0)} label="سفارش موفق" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
          <Stat icon="🔑" value={`${b.active_configs || 0}/${b.total_configs || 0}`} label="کانفیگ فعال" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
        </div>
      </Card>

      {fin && (
        <Card title="📈 گزارش مالی نماینده">
          <div className="grid stat-grid">
            <Stat icon="💸" value={fmt(fin.total_spent)} label="کل خرید (ت)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
            <Stat icon="📅" value={fmt(fin.month_spent)} label="خرید این ماه (ت)" grad="linear-gradient(135deg,#34d399,#10b981)" />
            <Stat icon="🧾" value={fmt(fin.orders)} label="سفارش‌ها" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
            <Stat icon="🔑" value={`${fin.active_services}/${fin.total_services}`} label="سرویس فعال/کل" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
          </div>
        </Card>
      )}

      {/* Pricing + wallet + role management */}
      <Card title="💲 قیمت‌گذاری اختصاصی">
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <div className="field"><label>تخفیف %</label><input className="inp" ref={disc} defaultValue={u.discount_percent || 0} type="number" dir="ltr" /></div>
          <div className="field"><label>قیمت هر GB</label><input className="inp" ref={ppg} defaultValue={fmt(u.price_per_gb)} onInput={liveNum} dir="ltr" /></div>
          <div className="field"><label>قیمت نامحدود</label><input className="inp" ref={unl} defaultValue={fmt(u.unlimited_price)} onInput={liveNum} dir="ltr" /></div>
        </div>
        <button className="btn sm primary" style={{ marginTop: 10 }} disabled={busy === "price"} onClick={savePricing}>💾 ذخیره قیمت</button>
      </Card>

      <Card title="💳 کیف پول">
        <div className="row" style={{ gap: 8 }}>
          <input className="inp" ref={balAmt} placeholder="+ شارژ / − کسر" onInput={liveNum} dir="ltr" style={{ flex: 2 }} />
          <input className="inp" ref={balNote} placeholder="توضیح" style={{ flex: 1 }} />
          <button className="btn sm accent" disabled={busy === "bal"} onClick={adjustBal}>اعمال</button>
        </div>
      </Card>

      <Card title="🛠 دسترسی و نمایندگی">
        <div className="row between" style={{ gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
          <select className="inp" style={{ maxWidth: 200 }} value={role} onChange={(e) => setRole(e.target.value)}>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <button className="btn sm" disabled={busy === "role"} onClick={saveRole}>ذخیره نقش</button>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn sm" disabled={busy.startsWith("tgl")} onClick={() => post("tglb", `/users/${uid}/toggle_block`)}>{u.is_blocked ? "🔓 آنبلاک" : "🔒 بلاک"}</button>
          <button className="btn sm" disabled={busy.startsWith("tgl")} onClick={() => post("tglw", `/users/${uid}/toggle_wholesale`)}>{u.is_wholesale ? "لغو نمایندگی" : "تایید نماینده"}</button>
          <button className="btn sm" disabled={busy.startsWith("tgl")} onClick={() => post("tglh", `/users/${uid}/toggle_hide_brand`)}>{u.hide_brand ? "نمایش برند" : "حذف برند"}</button>
        </div>
        {u.is_wholesale && (
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input className="inp" ref={repBrand} defaultValue={u.rep_brand_name || ""} placeholder="برند نماینده" maxLength={32} style={{ flex: 1 }} />
            <button className="btn sm primary" disabled={busy === "repbrand"} onClick={saveRepBrand}>💾 برند</button>
          </div>
        )}
      </Card>

      {/* Services (subscriptions) */}
      <Card title={`🧬 سرویس‌های ساب (${d.profiles.length})`}>
        {!d.profiles.length ? <Empty emoji="🧬">سرویسی نیست</Empty> : (
          <div className="grid" style={{ gap: 8 }}>
            {d.profiles.map((p) => (
              <div key={p.id} style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: 11 }}>
                <div className="row between" style={{ gap: 8, flexWrap: "wrap" }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <b>{p.name}</b> <span className={"badge " + (p.is_active ? "b-green" : "b-red")}>{p.is_active ? "فعال" : "غیرفعال"}</span>
                    <div className="muted tiny">{gb(p.used_bytes)}/{p.traffic_gb || "∞"}GB ({p.used_pct}%) · {p.days_left < 0 ? "بدون انقضا" : `${p.days_left} روز`}</div>
                  </div>
                  <div className="row" style={{ gap: 5, flexWrap: "wrap" }}>
                    <button className="btn xs" onClick={() => copy(p.url)}>🔗</button>
                    <button className="btn xs" onClick={() => setEditSub(p)}>✏️</button>
                    <button className="btn xs" onClick={() => subAct(p.id, "toggle")}>{p.is_active ? "🔴" : "🟢"}</button>
                    <button className="btn xs" onClick={() => subAct(p.id, "reset-usage", "مصرف صفر شود؟")}>♻️</button>
                    <button className="btn xs" onClick={() => subAct(p.id, "rebuild", "بازسازی لینک‌ها؟")}>🔧</button>
                    <button className="btn xs danger" onClick={() => subAct(p.id, "delete", "حذف کامل سرویس؟")}>🗑</button>
                  </div>
                </div>
                <div style={{ height: 4, background: "rgba(255,255,255,.07)", borderRadius: 3, marginTop: 7, overflow: "hidden" }}><div style={{ width: `${p.used_pct}%`, height: "100%", background: p.used_pct > 85 ? "#f43f5e" : "var(--p2)" }} /></div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {d.configs.length > 0 && (
        <Card title={`🔑 کانفیگ‌های قدیمی (${d.configs.length})`}>
          <div className="grid" style={{ gap: 8 }}>
            {d.configs.map((c) => (
              <div key={c.id} className="row between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: "9px 12px", gap: 8, flexWrap: "wrap" }}>
                <div><b className="mono tiny">{c.name}</b> <span className={"badge " + (c.is_active ? "b-green" : "b-red")}>{c.is_active ? "فعال" : "غیرفعال"}</span> <span className="muted tiny">{c.server_name}</span></div>
                <div className="row" style={{ gap: 5 }}>
                  <button className="btn xs" onClick={() => cfgAct(c.id, "toggle")}>{c.is_active ? "🔴" : "🟢"}</button>
                  <button className="btn xs danger" onClick={() => cfgAct(c.id, "delete", "حذف کانفیگ؟")}>🗑</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title={`🧾 سفارش‌ها (${d.orders.length})`}>
        {!d.orders.length ? <Empty emoji="🧾">سفارشی نیست</Empty> : (
          <div className="table-wrap"><table><thead><tr><th>#</th><th>پکیج</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr></thead><tbody>
            {d.orders.map((o) => (
              <tr key={o.id}><td>{o.id}</td><td>{o.pkg_name || "—"}</td><td>{fmt(o.price)}</td>
                <td><span className={"badge " + (o.status === "approved" ? "b-green" : o.status === "pending" ? "b-yellow" : "b-gray")}>{o.status}</span></td>
                <td className="muted tiny">{(o.created_at || "").slice(0, 10)}</td></tr>
            ))}
          </tbody></table></div>
        )}
      </Card>

      {editSub && <EditSubModal p={editSub} onClose={() => setEditSub(null)} onSaved={() => { setEditSub(null); load(); }} />}
    </div>
  );
}
