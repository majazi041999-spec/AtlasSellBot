import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Pager, Modal, Avatar, toast, liveNum, rawNum } from "../components/ui.jsx";

const ROLES = { none: "کاربر عادی", finance: "ادمین ساده", full: "ادمین کل" };

function UserModal({ user, onClose, onChanged }) {
  const [u, setU] = useState(user);
  const [busy, setBusy] = useState("");
  const disc = useRef(); const ppg = useRef(); const unl = useRef();
  const balAmt = useRef(); const balNote = useRef(); const repBrand = useRef();
  const [role, setRole] = useState(u.admin_role || "none");

  const saveRepBrand = async () => {
    setBusy("repbrand");
    try {
      const r = await api.post(`/users/${u.id}/rep_brand`, { brand: repBrand.current.value });
      setU({ ...u, rep_brand_name: r.rep_brand_name });
      toast("برند نماینده ذخیره شد ✅");
      onChanged();
    } catch (e) { toast("خطا", "error"); } finally { setBusy(""); }
  };

  const savePricing = async () => {
    setBusy("price");
    try {
      await api.post(`/users/${u.id}/pricing`, {
        discount_percent: parseFloat(disc.current.value || 0) || 0,
        price_per_gb: rawNum(ppg.current.value),
        unlimited_price: rawNum(unl.current.value),
      });
      toast("قیمت‌گذاری ذخیره شد ✅");
      onChanged();
    } catch (e) { toast("خطا در ذخیره", "error"); } finally { setBusy(""); }
  };
  const adjustBalance = async () => {
    const amount = rawNum(balAmt.current.value);
    if (!amount) { toast("مبلغ را وارد کنید", "error"); return; }
    setBusy("bal");
    try {
      const r = await api.post(`/users/${u.id}/balance_adjust`, { amount, note: balNote.current.value || "manual" });
      setU({ ...u, balance_toman: r.new_balance ?? u.balance_toman });
      balAmt.current.value = "";
      toast("موجودی اعمال شد ✅");
      onChanged();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };
  const saveRole = async () => {
    setBusy("role");
    try { await api.post(`/users/${u.id}/admin_role`, { role }); setU({ ...u, admin_role: role }); toast("سطح دسترسی ذخیره شد ✅"); onChanged(); }
    catch (e) { toast("خطا", "error"); } finally { setBusy(""); }
  };
  const toggle = async (kind) => {
    setBusy(kind);
    try {
      const r = await api.post(`/users/${u.id}/${kind}`);
      if (kind === "toggle_block") setU({ ...u, is_blocked: u.is_blocked ? 0 : 1 });
      if (kind === "toggle_wholesale") setU({ ...u, is_wholesale: r.is_wholesale ? 1 : 0, wholesale_request_pending: 0 });
      if (kind === "toggle_hide_brand") setU({ ...u, hide_brand: r.hide_brand ? 1 : 0 });
      toast("انجام شد ✅"); onChanged();
    } catch (e) { toast("خطا", "error"); } finally { setBusy(""); }
  };

  return (
    <Modal title={`مدیریت کاربر — ${u.full_name || u.telegram_id}`} onClose={onClose}>
      <div className="row" style={{ gap: 8, marginBottom: 14 }}>
        {u.is_blocked ? <span className="badge b-red">🔴 بلاک</span> : <span className="badge b-green">🟢 فعال</span>}
        {u.is_wholesale ? <span className="badge b-purple">نماینده</span> : null}
        {u.hide_brand ? <span className="badge b-blue">بدون برند</span> : null}
        {u.admin_role && u.admin_role !== "none" ? <span className="badge b-blue">{ROLES[u.admin_role]}</span> : null}
        <span className="muted tiny mono">{u.telegram_id}</span>
      </div>

      <div className="card" style={{ marginBottom: 12, padding: 14 }}>
        <div className="card-h"><h3 style={{ fontSize: ".92rem" }}>💲 قیمت‌گذاری اختصاصی</h3></div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <div className="field"><label>تخفیف %</label><input className="inp" ref={disc} defaultValue={u.discount_percent || 0} type="number" min="0" max="100" step="0.5" /></div>
          <div className="field"><label>قیمت هر GB</label><input className="inp" ref={ppg} defaultValue={fmt(u.price_per_gb)} onInput={liveNum} dir="ltr" /></div>
          <div className="field"><label>قیمت نامحدود</label><input className="inp" ref={unl} defaultValue={fmt(u.unlimited_price)} onInput={liveNum} dir="ltr" /></div>
        </div>
        <p className="muted tiny" style={{ margin: "8px 0 0" }}>صفر بگذارید تا به قیمت پیش‌فرض پکیج برگردد.</p>
        <button className="btn sm primary" style={{ marginTop: 10 }} disabled={busy === "price"} onClick={savePricing}>💾 ذخیره قیمت‌گذاری</button>
      </div>

      <div className="card" style={{ marginBottom: 12, padding: 14 }}>
        <div className="card-h between"><h3 style={{ fontSize: ".92rem" }}>💳 کیف پول</h3><b style={{ color: "var(--p2)" }}>{fmt(u.balance_toman)} ت</b></div>
        <div className="row" style={{ gap: 8 }}>
          <input className="inp" ref={balAmt} placeholder="مبلغ (+ شارژ / − کسر)" onInput={liveNum} dir="ltr" style={{ flex: 2 }} />
          <input className="inp" ref={balNote} placeholder="توضیح" style={{ flex: 1 }} />
          <button className="btn sm accent" disabled={busy === "bal"} onClick={adjustBalance}>اعمال</button>
        </div>
      </div>

      <div className="card" style={{ padding: 14 }}>
        <div className="row between" style={{ gap: 10, marginBottom: 10 }}>
          <div className="field" style={{ flex: 1 }}>
            <label>سطح دسترسی</label>
            <select className="inp" value={role} onChange={(e) => setRole(e.target.value)}>
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <button className="btn sm" style={{ alignSelf: "flex-end" }} disabled={busy === "role"} onClick={saveRole}>ذخیره نقش</button>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm" disabled={busy === "toggle_block"} onClick={() => toggle("toggle_block")}>{u.is_blocked ? "🔓 آنبلاک" : "🔒 بلاک"}</button>
          <button className="btn sm" disabled={busy === "toggle_wholesale"} onClick={() => toggle("toggle_wholesale")}>{u.is_wholesale ? "لغو نمایندگی" : "تایید نماینده"}</button>
        </div>
        <div className="between" style={{ gap: 10, marginTop: 12, alignItems: "center" }}>
          <div style={{ minWidth: 0 }}>
            <b style={{ fontSize: ".9rem" }}>🏷️ حذف برند از لینک سابسکریپشن</b>
            <p className="muted tiny" style={{ margin: "2px 0 0" }}>برای نماینده — نام برند شما در لینک سابسکریپشن او نمایش داده نمی‌شود.</p>
          </div>
          <button className={`btn sm ${u.hide_brand ? "danger" : "primary"}`} disabled={busy === "toggle_hide_brand"} onClick={() => toggle("toggle_hide_brand")}>{u.hide_brand ? "نمایش برند" : "حذف برند"}</button>
        </div>
      </div>

      {u.is_wholesale ? (
        <div className="card" style={{ marginTop: 12, padding: 14 }}>
          <div className="card-h"><h3 style={{ fontSize: ".92rem" }}>🏷️ برند نماینده</h3></div>
          <p className="muted tiny" style={{ margin: "0 0 8px" }}>نام برندی که در لینک سابسکریپشن مشتری‌های این نماینده نمایش داده می‌شود (نماینده هم می‌تواند از داخل ربات تنظیمش کند).</p>
          <div className="row" style={{ gap: 8 }}>
            <input className="inp" ref={repBrand} defaultValue={u.rep_brand_name || ""} placeholder="مثال: Sara VPN" maxLength={32} style={{ flex: 1 }} />
            <button className="btn sm primary" disabled={busy === "repbrand"} onClick={saveRepBrand}>💾 ذخیره</button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

export default function Users() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState(null);
  const tmr = useRef();

  const load = (p = 1, query = q) => {
    setData(null);
    api.get(`/api/users?page=${p}&q=${encodeURIComponent(query)}`).then(setData).catch(() => setData({ users: [] }));
  };
  useEffect(() => { load(1, ""); }, []);
  const onSearch = (v) => {
    setQ(v); clearTimeout(tmr.current);
    tmr.current = setTimeout(() => { setPage(1); load(1, v); }, 350);
  };

  const topups = (data && data.pending_topups) || [];

  const topupAct = async (rid, kind) => {
    try { await api.post(`/api/topups/${rid}/${kind}`); toast(kind === "approve" ? "شارژ تایید شد ✅" : "رد شد"); load(page, q); }
    catch (e) { toast("خطا", "error"); }
  };

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <input className="inp" style={{ maxWidth: 340 }} placeholder="🔍 جستجو: نام، یوزرنیم یا آیدی تلگرام…" value={q} onChange={(e) => onSearch(e.target.value)} />
        {data && <span className="muted tiny">{fmt(data.total)} کاربر</span>}
      </div>

      {topups.length > 0 && (
        <Card title="درخواست‌های شارژ کیف پول" sub={`${topups.length} در انتظار`}>
          <div className="grid" style={{ gap: 8 }}>
            {topups.map((t) => (
              <div key={t.id} className="between" style={{ background: "rgba(251,191,36,.06)", border: "1px solid rgba(251,191,36,.2)", borderRadius: 12, padding: "10px 13px", flexWrap: "wrap", gap: 10 }}>
                <div><b>{fmt(t.amount)} ت</b> <span className="muted tiny">· {t.full_name || "—"} {t.username ? `@${t.username}` : ""} <span className="mono">{t.telegram_id}</span></span></div>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn xs success" onClick={() => topupAct(t.id, "approve")}>تایید</button>
                  <button className="btn xs danger" onClick={() => topupAct(t.id, "reject")}>رد</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {!data ? <Loading /> : !data.users.length ? (
        <Card><Empty emoji="🔍">کاربری یافت نشد</Empty></Card>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>کاربر</th><th>کیف پول</th><th>آمار</th><th>قیمت‌گذاری</th><th>وضعیت</th><th>عملیات</th>
            </tr></thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="row" style={{ gap: 10 }}>
                      <Avatar name={u.full_name} />
                      <div style={{ minWidth: 0 }}>
                        <div><b>{u.full_name || "—"}</b></div>
                        <div className="muted tiny">{u.username ? `@${u.username}` : ""} <span className="mono">{u.telegram_id}</span></div>
                      </div>
                    </div>
                  </td>
                  <td><b style={{ color: "var(--p2)" }}>{fmt(u.balance_toman)}</b> <span className="muted tiny">ت</span></td>
                  <td className="tiny muted">✅ {u.business.approved_orders || 0}<br />🔑 {u.business.active_configs || 0}/{u.business.total_configs || 0}</td>
                  <td className="tiny">
                    {u.price_per_gb > 0 ? <div>هر GB: <b>{fmt(u.price_per_gb)}</b></div> : null}
                    {u.unlimited_price > 0 ? <div>نامحدود: <b>{fmt(u.unlimited_price)}</b></div> : null}
                    {u.discount_percent > 0 ? <div>تخفیف: <b>{u.discount_percent}%</b></div> : null}
                    {!u.price_per_gb && !u.unlimited_price && !u.discount_percent ? <span className="muted">پیش‌فرض</span> : null}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      {u.is_blocked ? <span className="badge b-red">بلاک</span> : <span className="badge b-green">فعال</span>}
                      {u.is_wholesale ? <span className="badge b-purple">نماینده</span> : (u.wholesale_request_pending ? <span className="badge b-yellow">درخواست</span> : null)}
                      {u.admin_role && u.admin_role !== "none" ? <span className="badge b-blue">{ROLES[u.admin_role]}</span> : null}
                    </div>
                  </td>
                  <td>
                    <button className="btn xs primary" onClick={() => setSel(u)}>⚙️ مدیریت</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && !q && <Pager page={data.page} totalPages={data.total_pages} onGo={(p) => { setPage(p); load(p, q); }} />}

      {sel && <UserModal user={sel} onClose={() => setSel(null)} onChanged={() => load(page, q)} />}
    </div>
  );
}
