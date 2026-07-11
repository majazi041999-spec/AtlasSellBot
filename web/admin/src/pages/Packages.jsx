import React, { useRef, useState, useEffect } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Modal, toast, liveNum, rawNum } from "../components/ui.jsx";

function PkgModal({ pkg, onClose, onSaved }) {
  const editing = !!pkg;
  const r = useRef({});
  const [busy, setBusy] = useState(false);
  const [unlimited, setUnlimited] = useState(!!(pkg?.is_unlimited));
  const set = (k) => (e) => { r.current[k] = e.target.value; };

  const save = async () => {
    const name = (r.current.name ?? pkg?.name ?? "").trim();
    if (!name) { toast("نام پکیج لازم است", "error"); return; }
    setBusy(true);
    try {
      const body = {
        name,
        traffic_gb: parseFloat(r.current.traffic_gb ?? pkg?.traffic_gb ?? 0) || 0,
        duration_days: parseInt(r.current.duration_days ?? pkg?.duration_days ?? 0) || 0,
        price: rawNum(r.current.price ?? String(pkg?.price ?? 0)),
        description: r.current.description ?? pkg?.description ?? "",
        inbound_id: parseInt(r.current.inbound_id ?? pkg?.inbound_id ?? 0) || 0,
        is_unlimited: unlimited ? "1" : "0",
      };
      await api.form(editing ? `/packages/${pkg.id}/edit` : `/packages/add`, body);
      toast(editing ? "پکیج ذخیره شد ✅" : "پکیج اضافه شد ✅");
      onSaved();
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  return (
    <Modal title={editing ? `✏️ ویرایش پکیج — ${pkg.name}` : "➕ افزودن پکیج"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="field"><label>نام پکیج</label>
          <input className="inp" defaultValue={pkg?.name || ""} onInput={set("name")} /></div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>حجم (GB) — ۰ = نامحدود</label>
            <input className="inp" type="number" step="0.1" min="0" defaultValue={pkg?.traffic_gb ?? 0} onInput={set("traffic_gb")} dir="ltr" /></div>
          <div className="field"><label>مدت (روز)</label>
            <input className="inp" type="number" min="0" defaultValue={pkg?.duration_days ?? 0} onInput={set("duration_days")} dir="ltr" /></div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>قیمت (تومان)</label>
            <input className="inp" defaultValue={fmt(pkg?.price || 0)} onInput={(e) => { liveNum(e); set("price")(e); }} dir="ltr" /></div>
          <div className="field"><label>Inbound ID (۰ = پیش‌فرض)</label>
            <input className="inp" type="number" min="0" defaultValue={pkg?.inbound_id ?? 0} onInput={set("inbound_id")} dir="ltr" /></div>
        </div>
        <div className="field"><label>توضیحات</label>
          <input className="inp" defaultValue={pkg?.description || ""} onInput={set("description")} /></div>
        <div style={{ border: "1px solid var(--line)", borderRadius: 12, padding: 12, background: unlimited ? "rgba(52,211,153,.07)" : "transparent" }}>
          <div className="row between">
            <div>
              <b style={{ fontSize: ".9rem" }}>♾ این یک پلن نامحدود است</b>
              <p className="muted tiny" style={{ margin: "3px 0 0" }}>اگر روشن باشد، قیمت این پلن از «قیمت نامحدود» کاربر محاسبه می‌شود، نه گیگی — حتی اگر حجم بالا آستانه مصرف باشد.</p>
            </div>
            <button type="button" className={"btn xs " + (unlimited ? "success" : "")} onClick={() => setUnlimited((v) => !v)}>{unlimited ? "✅ بله" : "خیر"}</button>
          </div>
        </div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function Packages() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);

  const load = () => api.get("/api/packages").then(setData).catch(() => setData({ packages: [] }));
  useEffect(() => { load(); }, []);

  const toggle = async (p) => { try { await api.post(`/packages/${p.id}/toggle`); load(); } catch (e) { toast("خطا", "error"); } };
  const del = async (p) => { if (!confirm(`پکیج «${p.name}» حذف شود؟`)) return; try { await api.post(`/packages/${p.id}/delete`); toast("حذف شد"); load(); } catch (e) { toast("خطا", "error"); } };

  if (!data) return <Loading />;
  const pkgs = data.packages || [];

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <span className="muted tiny">{pkgs.length} پکیج</span>
        <button className="btn sm primary" onClick={() => setModal({})}>➕ افزودن پکیج</button>
      </div>
      {!pkgs.length ? (
        <Card><Empty emoji="📦">هنوز پکیجی تعریف نشده است.</Empty></Card>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          {pkgs.map((p) => (
            <Card key={p.id}>
              <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>
                    {p.name} <span className={"badge " + (p.is_active ? "b-green" : "b-red")}>{p.is_active ? "فعال" : "غیرفعال"}</span>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    {p.is_unlimited ? <span className="badge b-green">♾ نامحدود{p.traffic_gb ? ` (آستانه ${p.traffic_gb}GB)` : ""}</span> : <span className="muted tiny">حجم: {p.traffic_gb ? `${p.traffic_gb}GB` : "نامحدود"}</span>}
                    <span className="muted tiny">مدت: {p.duration_days} روز</span>
                    <span className="badge b-blue">{fmt(p.price)} ت</span>
                    {p.inbound_id ? <span className="muted tiny">Inbound: {p.inbound_id}</span> : null}
                  </div>
                  {p.description ? <div className="muted tiny" style={{ marginTop: 4 }}>{p.description}</div> : null}
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <button className="btn xs" onClick={() => setModal(p)}>✏️ ویرایش</button>
                  <button className="btn xs" onClick={() => toggle(p)}>{p.is_active ? "🔴 غیرفعال" : "🟢 فعال"}</button>
                  <button className="btn xs danger" onClick={() => del(p)}>🗑</button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {modal !== null && (
        <PkgModal pkg={modal.id ? modal : null} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }} />
      )}
    </div>
  );
}
