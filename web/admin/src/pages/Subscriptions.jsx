import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, Empty, Modal, toast } from "../components/ui.jsx";

// ─────────────────────────────── live progress log ───────────────────────────
// Polls a job-log endpoint while an operation runs and renders the streamed
// lines. Used for both the full sync and per-node (nodeops) reconciliation.
function OpsLog({ logPath, active, onIdle, title }) {
  const [data, setData] = useState({ lines: [], running: false, status: "idle" });
  const box = useRef();
  const tmr = useRef();

  useEffect(() => {
    if (!active) return;
    let stop = false;
    const tick = async () => {
      try {
        const d = await api.get(logPath);
        if (stop) return;
        setData(d);
        if (!d.running && d.status !== "idle") { onIdle && onIdle(d); return; }
      } catch (e) { /* keep polling */ }
      tmr.current = setTimeout(tick, 1000);
    };
    tick();
    return () => { stop = true; clearTimeout(tmr.current); };
  }, [active, logPath]);

  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [data]);

  if (!active && !(data.lines || []).length) return null;
  const color = data.status === "error" ? "var(--red)" : data.status === "ok" ? "var(--green)" : "var(--p2)";
  return (
    <div style={{ marginTop: 12 }}>
      <div className="row between" style={{ marginBottom: 6 }}>
        <b style={{ fontSize: ".85rem" }}>{title}</b>
        <span className="tiny" style={{ color }}>
          {data.running ? "⏳ در حال اجرا…" : data.status === "ok" ? "✅ تمام شد" : data.status === "error" ? "❌ خطا" : ""}
        </span>
      </div>
      <div ref={box} className="mono tiny" style={{
        background: "rgba(0,0,0,.28)", border: "1px solid var(--line)", borderRadius: 10,
        padding: 10, maxHeight: 240, overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7,
      }}>
        {(data.lines || []).join("\n") || "…"}
      </div>
    </div>
  );
}

// ─────────────────────────────── add / edit node ─────────────────────────────
function NodeModal({ node, servers, onClose, onSaved }) {
  const editing = !!node;
  const [server, setServer] = useState(node?.server_id || servers[0]?.id || "");
  const [inbound, setInbound] = useState(node?.inbound_id || 1);
  const [label, setLabel] = useState(node?.label || "");
  const [priority, setPriority] = useState(node?.priority || 100);
  const [cap, setCap] = useState(node?.max_active_profiles || 0);
  const [host, setHost] = useState(node?.connect_host || "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!server) { toast("سرور را انتخاب کنید", "error"); return; }
    setBusy(true);
    try {
      const body = {
        server_id: Number(server), inbound_id: Number(inbound), label: label.trim(),
        priority: Number(priority) || 100, max_active_profiles: Number(cap) || 0,
        connect_host: host.trim(),
      };
      const path = editing ? `/subs/nodes/${node.id}/edit` : `/subs/nodes/add`;
      const r = await api.post(path, body);
      toast(editing ? "نود ذخیره شد ✅" : "نود اضافه شد ✅");
      onSaved(r.job_started);
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  return (
    <Modal title={editing ? "✏️ ویرایش نود" : "➕ افزودن نود ساب"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
          <div className="field"><label>سرور</label>
            <select className="inp" value={server} onChange={(e) => setServer(e.target.value)}>
              {servers.map((s) => <option key={s.id} value={s.id}>{s.name}{s.is_active ? "" : " (غیرفعال)"}</option>)}
            </select>
          </div>
          <div className="field"><label>Inbound ID</label>
            <input className="inp" type="number" min="1" value={inbound} onChange={(e) => setInbound(e.target.value)} dir="ltr" />
          </div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "2fr 1fr 1fr", gap: 10 }}>
          <div className="field"><label>نام نمایشی</label>
            <input className="inp" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="مثال: Netherland VIP" />
          </div>
          <div className="field"><label>اولویت</label>
            <input className="inp" type="number" min="1" value={priority} onChange={(e) => setPriority(e.target.value)} dir="ltr" />
          </div>
          <div className="field"><label>ظرفیت (۰=∞)</label>
            <input className="inp" type="number" min="0" value={cap} onChange={(e) => setCap(e.target.value)} dir="ltr" />
          </div>
        </div>
        <div className="field">
          <label>دامین اتصال اختصاصی (اختیاری)</label>
          <input className="inp" value={host} onChange={(e) => setHost(e.target.value)} dir="ltr" placeholder="مثال: customize.bagsale.click" />
          <p className="muted tiny" style={{ margin: "4px 0 0" }}>
            اگر پر شود، فقط <b>آدرس اتصال</b> در لینک با این دامین جایگزین می‌شود (پورت، SNI، host و path دست‌نخورده می‌مانند). خالی = آدرس خود اینباند.
          </p>
        </div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

// ─────────────────────────────── inbound editor ──────────────────────────────
function InboundModal({ node, onClose, onSaved }) {
  const [loading, setLoading] = useState(true);
  const [inb, setInb] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stop = false;
    api.get(`/subs/nodes/${node.id}/inbound`)
      .then((r) => { if (!stop) { setInb(r.inbound); setLoading(false); } })
      .catch((e) => { if (!stop) { setErr(e.message || "خطا"); setLoading(false); } });
    return () => { stop = true; };
  }, [node.id]);

  const upd = (k, v) => setInb((s) => ({ ...s, [k]: v }));

  const save = async () => {
    // Client-side JSON sanity check for the three string fields before sending.
    for (const k of ["settings", "streamSettings", "sniffing"]) {
      const v = inb[k];
      if (typeof v === "string" && v.trim()) {
        try { JSON.parse(v); } catch (e) { toast(`JSON نامعتبر در ${k}`, "error"); return; }
      }
    }
    setBusy(true);
    try {
      await api.post(`/subs/nodes/${node.id}/inbound`, {
        remark: inb.remark, port: Number(inb.port) || undefined, enable: !!inb.enable,
        settings: inb.settings, streamSettings: inb.streamSettings, sniffing: inb.sniffing,
      });
      toast("اینباند ذخیره شد؛ لینک‌ها در حال بازسازی ✅");
      onSaved();
    } catch (e) { toast(e.message || "خطا در ذخیره اینباند", "error"); } finally { setBusy(false); }
  };

  const ta = { width: "100%", minHeight: 96, fontFamily: "monospace", fontSize: ".78rem", direction: "ltr",
    background: "rgba(0,0,0,.22)", color: "var(--txt)", border: "1px solid var(--line)", borderRadius: 8, padding: 8 };

  return (
    <Modal title={`🛠 ویرایش اینباند — ${node.label || node.server_name} #${node.inbound_id}`} onClose={onClose}>
      {loading ? <Loading /> : err ? <Empty emoji="⚠️">{err}</Empty> : (
        <div className="grid" style={{ gap: 10 }}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr 1fr", gap: 10 }}>
            <div className="field"><label>Remark</label>
              <input className="inp" value={inb.remark || ""} onChange={(e) => upd("remark", e.target.value)} /></div>
            <div className="field"><label>Port</label>
              <input className="inp" type="number" value={inb.port || ""} onChange={(e) => upd("port", e.target.value)} dir="ltr" /></div>
            <div className="field"><label>وضعیت</label>
              <select className="inp" value={inb.enable ? "1" : "0"} onChange={(e) => upd("enable", e.target.value === "1")}>
                <option value="1">فعال</option><option value="0">غیرفعال</option>
              </select></div>
          </div>
          <div className="field"><label>settings (JSON)</label>
            <textarea style={ta} value={inb.settings || ""} onChange={(e) => upd("settings", e.target.value)} /></div>
          <div className="field"><label>streamSettings (JSON)</label>
            <textarea style={ta} value={inb.streamSettings || ""} onChange={(e) => upd("streamSettings", e.target.value)} /></div>
          <div className="field"><label>sniffing (JSON)</label>
            <textarea style={ta} value={inb.sniffing || ""} onChange={(e) => upd("sniffing", e.target.value)} /></div>
          <p className="muted tiny" style={{ margin: 0 }}>پس از ذخیره، لینک همه ساب‌های این نود به‌صورت خودکار بازسازی می‌شود.</p>
          <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره اینباند"}</button>
        </div>
      )}
    </Modal>
  );
}

// ─────────────────────────────── page ────────────────────────────────────────
export default function Subscriptions() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);      // {kind:'node'|'inbound', node}
  const [ops, setOps] = useState(false);          // nodeops running/watching
  const [sync, setSync] = useState(false);        // full sync running/watching

  const load = () => { api.get("/api/subs").then(setData).catch(() => setData({ nodes: [], servers: [] })); };
  useEffect(() => { load(); }, []);

  const act = async (fn, watchOps = true) => {
    try {
      const r = await fn();
      if (watchOps && r && r.job_started) setOps(true);
      load();
      return r;
    } catch (e) { toast(e.message || "خطا", "error"); }
  };

  const toggle = (n) => act(() => api.post(`/subs/nodes/${n.id}/toggle`));
  const del = (n) => { if (confirm(`نود «${n.label || n.server_name}» حذف شود؟ از همه لینک‌ها هم پاک می‌شود.`)) act(() => api.post(`/subs/nodes/${n.id}/delete`)); };
  const reconcile = (n) => act(() => api.post(`/subs/nodes/${n.id}/reconcile`));
  const testNode = async (n) => {
    toast("در حال تست…");
    try { const r = await api.post(`/subs/nodes/${n.id}/test`); toast(r.success ? `✅ ${r.msg || "سالم"}` : `❌ ${r.msg || "خطا"}`, r.success ? "success" : "error"); }
    catch (e) { toast("❌ خطا در تست", "error"); }
  };
  const startSync = async (deep) => {
    try { await api.form(`/subs/sync-nodes/start`, { deep: deep ? "1" : "0" }); setSync(true); }
    catch (e) { toast(e.message || "همگام‌سازی شروع نشد", "error"); }
  };

  if (!data) return <Loading />;
  const nodes = data.nodes || [];
  const servers = data.servers || [];

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="🔄 همگام‌سازی نودها" sub="افزودن/غیرفعال‌سازی نودها به‌صورت لحظه‌ای اعمال می‌شود؛ این‌ها فقط برای بازبینی کلی‌اند.">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn sm" disabled={sync} onClick={() => startSync(false)}>⚡ سریع (نودهای ناقص)</button>
          <button className="btn sm" disabled={sync} onClick={() => startSync(true)}>🔁 بازسازی کامل لینک‌ها</button>
          <button className="btn sm primary" onClick={() => setModal({ kind: "node" })} disabled={!servers.length}>➕ افزودن نود</button>
        </div>
        {!servers.length && <p className="muted tiny" style={{ marginTop: 8 }}>اول از پنل قدیم یک سرور اضافه کنید.</p>}
        <OpsLog logPath="/subs/sync-nodes/log" active={sync} title="گزارش همگام‌سازی کامل" onIdle={() => { setSync(false); load(); }} />
        <OpsLog logPath="/subs/nodes/ops/log" active={ops} title="گزارش عملیات لحظه‌ای نود" onIdle={() => { setOps(false); load(); }} />
      </Card>

      {!nodes.length ? (
        <Card><Empty emoji="🧬">هنوز نودی برای ساب تعریف نشده است.</Empty></Card>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          {nodes.map((n) => {
            const on = n.is_active && n.server_active;
            return (
              <Card key={n.id}>
                <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700 }}>
                      {n.label || n.server_name} <span className="muted mono">#{n.inbound_id}</span>
                    </div>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                      <span className={"badge " + (on ? "b-green" : "b-red")}>{on ? "فعال" : "غیرفعال"}</span>
                      <span className={"badge " + (n.usable ? "b-green" : "b-yellow")}>{n.usable_label}</span>
                      <span className="muted tiny">سرور: {n.server_name}</span>
                      <span className="muted tiny">اولویت: {n.priority}</span>
                      <span className="muted tiny">ظرفیت: {n.active_profiles}/{n.max_active_profiles || "∞"}</span>
                      {n.connect_host ? <span className="badge b-blue">🌐 {n.connect_host}</span> : null}
                    </div>
                    <div className="muted tiny mono" style={{ marginTop: 4 }}>{n.server_url}</div>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                    <button className="btn xs" onClick={() => testNode(n)}>🔗 تست</button>
                    <button className="btn xs" onClick={() => setModal({ kind: "inbound", node: n })}>🛠 اینباند</button>
                    <button className="btn xs" onClick={() => reconcile(n)}>♻️ بازسازی لینک‌ها</button>
                    <button className="btn xs" onClick={() => setModal({ kind: "node", node: n })}>✏️ ویرایش</button>
                    <button className="btn xs" onClick={() => toggle(n)}>{n.is_active ? "🔴 غیرفعال" : "🟢 فعال"}</button>
                    <button className="btn xs danger" onClick={() => del(n)}>🗑</button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {modal?.kind === "node" && (
        <NodeModal node={modal.node} servers={servers} onClose={() => setModal(null)}
          onSaved={(jobStarted) => { setModal(null); if (jobStarted) setOps(true); load(); }} />
      )}
      {modal?.kind === "inbound" && (
        <InboundModal node={modal.node} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); setOps(true); load(); }} />
      )}
    </div>
  );
}
