import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, Empty, Modal, toast } from "../components/ui.jsx";

function ServerModal({ server, onClose, onSaved }) {
  const editing = !!server;
  const f = useRef({});
  const [busy, setBusy] = useState(false);
  const val = (k, d = "") => (f.current[k] !== undefined ? f.current[k] : (server?.[k] ?? d));
  const set = (k) => (e) => { f.current[k] = e.target.value; };

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        name: val("name"), url: val("url"), username: val("username"),
        password: f.current.password || "", api_token: f.current.api_token || "",
        sub_path: val("sub_path"), inbound_id: val("inbound_id", 1),
        inbound_ids: val("inbound_ids"), note: val("note"),
        max_active_configs: val("max_active_configs", 0),
      };
      // Existing endpoints take form-encoded and redirect; api.form treats the
      // redirect/HTML response as success.
      await api.form(editing ? `/servers/${server.id}/edit` : `/servers/add`, body);
      toast(editing ? "سرور ذخیره شد ✅" : "سرور اضافه شد ✅");
      onSaved();
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  const Field = ({ k, label, type = "text", ph = "", ltr = true, def = "" }) => (
    <div className="field">
      <label>{label}</label>
      <input className="inp" type={type} defaultValue={server?.[k] ?? def} placeholder={ph}
        onInput={set(k)} dir={ltr ? "ltr" : "rtl"} />
    </div>
  );

  return (
    <Modal title={editing ? `✏️ ویرایش سرور — ${server.name}` : "➕ افزودن سرور"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <Field k="name" label="نام سرور" ltr={false} ph="مثال: Netherland-1" />
        <Field k="url" label="آدرس پنل (URL)" ph="https://host:port" />
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field k="username" label="یوزرنیم پنل" />
          <div className="field">
            <label>پسورد پنل {editing && <span className="muted tiny">(خالی = بدون تغییر)</span>}</label>
            <input className="inp" type="password" placeholder={editing ? "بدون تغییر" : ""} onInput={set("password")} dir="ltr" />
          </div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field k="sub_path" label="Sub Path (اختیاری)" ph="sub" />
          <div className="field">
            <label>API Token {editing && server.has_api_token && <span className="muted tiny">(ذخیره‌شده)</span>}</label>
            <input className="inp" type="password" placeholder={editing && server.has_api_token ? "بدون تغییر" : ""} onInput={set("api_token")} dir="ltr" />
          </div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <Field k="inbound_id" label="Inbound ID پیش‌فرض" type="number" def={1} />
          <Field k="inbound_ids" label="Inbound IDs (کاما)" ph="1,2,3" />
          <Field k="max_active_configs" label="ظرفیت (۰=∞)" type="number" def={0} />
        </div>
        <Field k="note" label="یادداشت" ltr={false} />
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function Servers() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);

  const load = () => api.get("/api/servers").then(setData).catch(() => setData({ servers: [] }));
  useEffect(() => { load(); }, []);

  const toggle = async (s) => { try { await api.post(`/servers/${s.id}/toggle`); load(); } catch (e) { toast("خطا", "error"); } };
  const del = async (s) => { if (!confirm(`سرور «${s.name}» حذف شود؟`)) return; try { await api.post(`/servers/${s.id}/delete`); toast("حذف شد"); load(); } catch (e) { toast("خطا", "error"); } };
  const test = async (s) => {
    toast("در حال تست اتصال…");
    try { const r = await api.post(`/servers/${s.id}/test`); toast(r.success ? "✅ اتصال سالم" : "❌ اتصال ناموفق", r.success ? "success" : "error"); }
    catch (e) { toast("❌ خطا", "error"); }
  };

  if (!data) return <Loading />;
  const servers = data.servers || [];

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <span className="muted tiny">{servers.length} سرور</span>
        <button className="btn sm primary" onClick={() => setModal({})}>➕ افزودن سرور</button>
      </div>
      {!servers.length ? (
        <Card><Empty emoji="🖥">هنوز سروری اضافه نشده است.</Empty></Card>
      ) : servers.map((s) => (
        <Card key={s.id}>
          <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700 }}>
                {s.name} <span className={"badge " + (s.is_active ? "b-green" : "b-red")}>{s.is_active ? "فعال" : "غیرفعال"}</span>
              </div>
              <div className="muted tiny mono" style={{ marginTop: 4 }}>{s.url}</div>
              <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                <span className="muted tiny">یوزر: {s.username}</span>
                <span className="muted tiny">اینباند: {s.inbound_id}{s.inbound_ids ? ` (${s.inbound_ids})` : ""}</span>
                <span className="muted tiny">ظرفیت: {s.active_configs}/{s.max_active_configs || "∞"}</span>
                {s.has_api_token ? <span className="badge b-blue">API Token</span> : null}
              </div>
              {s.note ? <div className="muted tiny" style={{ marginTop: 4 }}>📝 {s.note}</div> : null}
            </div>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <button className="btn xs" onClick={() => test(s)}>🔌 تست</button>
              <button className="btn xs" onClick={() => setModal(s)}>✏️ ویرایش</button>
              <button className="btn xs" onClick={() => toggle(s)}>{s.is_active ? "🔴 غیرفعال" : "🟢 فعال"}</button>
              <button className="btn xs danger" onClick={() => del(s)}>🗑</button>
            </div>
          </div>
        </Card>
      ))}
      {modal !== null && (
        <ServerModal server={modal.id ? modal : null} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }} />
      )}
    </div>
  );
}
