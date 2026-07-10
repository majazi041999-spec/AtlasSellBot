import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Modal, toast, liveNum, rawNum } from "../components/ui.jsx";

function CodeModal({ code, packages, onClose, onSaved }) {
  const editing = !!code;
  const r = useRef({});
  const [kind, setKind] = useState(code?.kind || "percent");
  const [pkg, setPkg] = useState(String(code?.package_id ?? 0));
  const [targeted, setTargeted] = useState(String(code?.targeted ?? 0));
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => { r.current[k] = e.target.value; };

  const save = async () => {
    const c = (r.current.code ?? code?.code ?? "").trim();
    if (!c) { toast("کد لازم است", "error"); return; }
    setBusy(true);
    try {
      const body = {
        code: c, kind,
        value: parseFloat(r.current.value ?? code?.value ?? 0) || 0,
        max_uses: parseInt(r.current.max_uses ?? code?.max_uses ?? 0) || 0,
        per_user_limit: parseInt(r.current.per_user_limit ?? code?.per_user_limit ?? 1) || 0,
        min_amount: rawNum(r.current.min_amount ?? String(code?.min_amount ?? 0)),
        package_id: parseInt(pkg) || 0,
        expires: r.current.expires ?? code?.expires ?? "",
        note: r.current.note ?? code?.note ?? "",
        campaign: r.current.campaign ?? code?.campaign ?? "",
        targeted,
      };
      await api.form(editing ? `/discounts/${code.id}/edit` : `/discounts/add`, body);
      toast(editing ? "کد ذخیره شد ✅" : "کد اضافه شد ✅");
      onSaved();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };

  return (
    <Modal title={editing ? `✏️ ویرایش کد — ${code.code}` : "➕ کد تخفیف جدید"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
          <div className="field"><label>کد</label>
            <input className="inp mono" defaultValue={code?.code || ""} onInput={set("code")} dir="ltr" placeholder="OFF20" /></div>
          <div className="field"><label>نوع</label>
            <select className="inp" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="percent">درصدی</option><option value="fixed">مبلغ ثابت</option>
            </select></div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <div className="field"><label>{kind === "percent" ? "درصد" : "مبلغ (تومان)"}</label>
            <input className="inp" defaultValue={code?.value ?? 0} onInput={set("value")} dir="ltr" /></div>
          <div className="field"><label>سقف کل مصرف (۰=∞)</label>
            <input className="inp" type="number" defaultValue={code?.max_uses ?? 0} onInput={set("max_uses")} dir="ltr" /></div>
          <div className="field"><label>سقف هر کاربر (۰=∞)</label>
            <input className="inp" type="number" defaultValue={code?.per_user_limit ?? 1} onInput={set("per_user_limit")} dir="ltr" /></div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>حداقل مبلغ سفارش</label>
            <input className="inp" defaultValue={fmt(code?.min_amount || 0)} onInput={(e) => { liveNum(e); set("min_amount")(e); }} dir="ltr" /></div>
          <div className="field"><label>انقضا (YYYY-MM-DD)</label>
            <input className="inp" defaultValue={code?.expires || ""} onInput={set("expires")} dir="ltr" placeholder="خالی = بدون انقضا" /></div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>محدود به پکیج</label>
            <select className="inp" value={pkg} onChange={(e) => setPkg(e.target.value)}>
              <option value="0">همه پکیج‌ها</option>
              {packages.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></div>
          <div className="field"><label>فقط کاربران هدف کمپین</label>
            <select className="inp" value={targeted} onChange={(e) => setTargeted(e.target.value)}>
              <option value="0">خیر</option><option value="1">بله</option>
            </select></div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>کمپین</label>
            <input className="inp" defaultValue={code?.campaign || ""} onInput={set("campaign")} /></div>
          <div className="field"><label>یادداشت</label>
            <input className="inp" defaultValue={code?.note || ""} onInput={set("note")} /></div>
        </div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function Discounts() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);
  const load = () => api.get("/api/discounts").then(setData).catch(() => setData({ codes: [], packages: [] }));
  useEffect(() => { load(); }, []);

  const toggle = async (c) => { try { await api.post(`/discounts/${c.id}/toggle`); load(); } catch (e) { toast("خطا", "error"); } };
  const del = async (c) => { if (!confirm(`کد «${c.code}» حذف شود؟`)) return; try { await api.post(`/discounts/${c.id}/delete`); toast("حذف شد"); load(); } catch (e) { toast("خطا", "error"); } };

  if (!data) return <Loading />;
  const codes = data.codes || [];
  const pkgName = (id) => (data.packages.find((p) => p.id === id) || {}).name;

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <span className="muted tiny">{codes.length} کد تخفیف</span>
        <button className="btn sm primary" onClick={() => setModal({})}>➕ کد جدید</button>
      </div>
      {!codes.length ? <Card><Empty emoji="🎟">هنوز کد تخفیفی نیست.</Empty></Card> : (
        <div className="grid" style={{ gap: 10 }}>
          {codes.map((c) => (
            <Card key={c.id}>
              <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>
                    <span className="mono">{c.code}</span>{" "}
                    <span className={"badge " + (c.is_active ? "b-green" : "b-red")}>{c.is_active ? "فعال" : "غیرفعال"}</span>{" "}
                    <span className="badge b-blue">{c.kind === "percent" ? `${c.value}%` : `${fmt(c.value)} ت`}</span>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    <span className="muted tiny">مصرف: {c.used_count}{c.max_uses ? `/${c.max_uses}` : ""}</span>
                    <span className="muted tiny">هر کاربر: {c.per_user_limit || "∞"}</span>
                    {c.min_amount ? <span className="muted tiny">حداقل: {fmt(c.min_amount)} ت</span> : null}
                    {c.package_id ? <span className="muted tiny">پکیج: {pkgName(c.package_id) || c.package_id}</span> : null}
                    {c.expires ? <span className="muted tiny">انقضا: {c.expires}</span> : null}
                    {c.targeted ? <span className="badge b-purple">هدفمند</span> : null}
                    {c.campaign ? <span className="badge b-yellow">{c.campaign}</span> : null}
                  </div>
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <button className="btn xs" onClick={() => setModal(c)}>✏️</button>
                  <button className="btn xs" onClick={() => toggle(c)}>{c.is_active ? "🔴" : "🟢"}</button>
                  <button className="btn xs danger" onClick={() => del(c)}>🗑</button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {modal !== null && <CodeModal code={modal.id ? modal : null} packages={data.packages || []} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} />}
    </div>
  );
}
