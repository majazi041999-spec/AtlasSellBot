import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Modal, Pager, toast } from "../components/ui.jsx";

const gb = (bytes) => (Number(bytes || 0) / 1024 ** 3).toFixed(2);
const tsToInput = (ms) => {
  if (!ms) return "";
  const d = new Date(Number(ms));
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function EditModal({ p, onClose, onSaved }) {
  const email = useRef(); const traffic = useRef(); const expire = useRef(); const [active, setActive] = useState(String(p.is_active));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.form(`/subs/profiles/${p.id}/edit`, {
        email: email.current.value, traffic_gb: traffic.current.value,
        expire_at: expire.current.value, is_active: active,
      });
      toast("ذخیره شد ✅"); onSaved();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };
  return (
    <Modal title={`✏️ ویرایش ساب — ${p.name || p.email}`} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="field"><label>ایمیل/شناسه</label><input className="inp mono" ref={email} defaultValue={p.email} dir="ltr" /></div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>حجم (GB)</label><input className="inp" ref={traffic} type="number" step="0.1" defaultValue={p.traffic_gb} dir="ltr" /></div>
          <div className="field"><label>وضعیت</label>
            <select className="inp" value={active} onChange={(e) => setActive(e.target.value)}>
              <option value="1">فعال</option><option value="0">غیرفعال</option>
            </select></div>
        </div>
        <div className="field"><label>انقضا</label><input className="inp" ref={expire} type="datetime-local" defaultValue={tsToInput(p.expire_timestamp)} dir="ltr" /></div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function SubProfiles() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null);
  const tmr = useRef();

  const load = (p = 1, query = q) => { setData(null); api.get(`/api/subs/profiles?page=${p}&q=${encodeURIComponent(query)}`).then(setData).catch(() => setData({ profiles: [] })); };
  useEffect(() => { load(1, ""); }, []);
  const onSearch = (v) => { setQ(v); clearTimeout(tmr.current); tmr.current = setTimeout(() => load(1, v), 350); };

  const act = async (id, kind, confirmMsg) => {
    if (confirmMsg && !confirm(confirmMsg)) return;
    try { await api.post(`/subs/profiles/${id}/${kind}`); toast("انجام شد ✅"); load(data.page, q); }
    catch (e) { toast("خطا", "error"); }
  };
  const copy = (url) => { navigator.clipboard?.writeText(url).then(() => toast("لینک کپی شد ✅")); };

  if (!data) return <Loading />;
  const profiles = data.profiles || [];

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <input className="inp" style={{ maxWidth: 340 }} placeholder="🔍 نام، ایمیل یا آیدی تلگرام…" value={q} onChange={(e) => onSearch(e.target.value)} />
        {data.total != null && <span className="muted tiny">{fmt(data.total)} ساب</span>}
      </div>
      {!profiles.length ? <Card><Empty emoji="📄">سابی یافت نشد.</Empty></Card> : (
        <div className="grid" style={{ gap: 10 }}>
          {profiles.map((p) => (
            <Card key={p.id}>
              <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 700 }}>
                    {p.name || p.email} <span className={"badge " + (p.is_active ? "b-green" : "b-red")}>{p.is_active ? "فعال" : "غیرفعال"}</span>
                  </div>
                  <div className="muted tiny" style={{ marginTop: 3 }}>
                    {p.full_name || "—"} {p.username ? `@${p.username}` : ""} <span className="mono">{p.telegram_id}</span>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    <span className="muted tiny">حجم: {gb(p.used_bytes)}/{p.traffic_gb || "∞"} GB ({p.used_pct}%)</span>
                    <span className="muted tiny">{p.days_left < 0 ? "بدون انقضا" : `${p.days_left} روز مانده`}</span>
                  </div>
                  <div style={{ height: 5, background: "rgba(255,255,255,.07)", borderRadius: 4, marginTop: 6, overflow: "hidden" }}>
                    <div style={{ width: `${p.used_pct}%`, height: "100%", background: p.used_pct > 85 ? "var(--red,#f43f5e)" : "var(--p2)" }} />
                  </div>
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <button className="btn xs" onClick={() => copy(p.url)}>🔗 لینک</button>
                  <button className="btn xs" onClick={() => setEdit(p)}>✏️</button>
                  <button className="btn xs" onClick={() => act(p.id, "toggle")}>{p.is_active ? "🔴" : "🟢"}</button>
                  <button className="btn xs" onClick={() => act(p.id, "reset-usage", "مصرف صفر شود؟")}>♻️ حجم</button>
                  <button className="btn xs" onClick={() => act(p.id, "reset-time", "زمان از نو شود؟")}>⏱ زمان</button>
                  <button className="btn xs" onClick={() => act(p.id, "rebuild", "لینک‌ها بازسازی شوند؟")}>🔧</button>
                  <button className="btn xs danger" onClick={() => act(p.id, "delete", `ساب «${p.name || p.email}» کامل حذف شود؟`)}>🗑</button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {data.total_pages > 1 && <Pager page={data.page} totalPages={data.total_pages} onGo={(pg) => load(pg, q)} />}
      {edit && <EditModal p={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(data.page, q); }} />}
    </div>
  );
}
