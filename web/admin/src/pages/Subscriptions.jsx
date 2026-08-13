import React, { useEffect, useRef, useState } from "react";
import { api, fmt, fmtFa } from "../api.js";
import { Card, Loading, Empty, Modal, toast } from "../components/ui.jsx";

// ─────────────────────────────── auto-node helpers ───────────────────────────
const AUTO_LABEL = "🚀 خودکار";

/** "3,7" → [3, 7]  (node-config ids; empty = every active node). */
const parsePool = (raw) =>
  String(raw || "").split(",").map((x) => parseInt(x, 10)).filter((x) => x > 0);

/** epoch-ms → «۲ دقیقه پیش». 0/missing = the panel was never polled. */
function agoFa(ms) {
  const t = Number(ms || 0);
  if (!t) return "هنوز خوانده نشده";
  const m = Math.floor(Math.max(0, Date.now() - t) / 60000);
  if (m < 1) return "همین حالا";
  if (m < 60) return `${fmtFa(m)} دقیقه پیش`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${fmtFa(h)} ساعت پیش`;
  return `${fmtFa(Math.floor(h / 24))} روز پیش`;
}

/** An online count is a number OR null — null means "panel unreachable", which
    must never be drawn as 0 (a dead server would look like the emptiest one). */
const onlineText = (v) => (v == null ? "نامشخص" : `${fmt(v)} آنلاین`);

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
        <div style={{ border: "1px solid var(--p2)", borderRadius: 12, padding: 12, background: "rgba(99,102,241,.06)" }}>
          <label style={{ fontWeight: 700, display: "block", marginBottom: 4 }}>🌐 دامین اتصال اختصاصی (اختیاری)</label>
          <input className="inp" value={host} onChange={(e) => setHost(e.target.value)} dir="ltr" placeholder="مثال: customize.bagsale.click" />
          <p className="muted tiny" style={{ margin: "6px 0 0" }}>
            اگر پر شود، فقط <b>آدرس اتصال</b> در لینک همه‌ی ساب‌ها با این دامین جایگزین می‌شود (پورت، SNI، host و path دست‌نخورده). خالی = آدرس خود اینباند.
          </p>
        </div>
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
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

// ─────────────────────────────── add / edit AUTO node ────────────────────────
// An auto node owns no server/inbound of its own, so it gets its own form: the
// normal one's server + inbound + capacity fields are meaningless here.
function AutoNodeModal({ node, nodes, onClose, onSaved }) {
  const editing = !!node;
  const [label, setLabel] = useState(node?.label || AUTO_LABEL);
  const [priority, setPriority] = useState(node?.priority || 1);
  const [pool, setPool] = useState(() => parsePool(node?.auto_pool));
  const [showServer, setShowServer] = useState(!!node?.auto_show_server);
  const [host, setHost] = useState(node?.connect_host || "");
  const [busy, setBusy] = useState(false);

  const member = (id) => setPool((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        label: label.trim() || AUTO_LABEL,
        priority: Number(priority) || 1,
        auto_pool: pool.join(","),           // "" = همه‌ی نودهای فعال
        auto_show_server: showServer ? "1" : "0",
        connect_host: host.trim(),
      };
      const path = editing ? `/subs/nodes/${node.id}/edit` : `/subs/nodes/add_auto`;
      const r = await api.post(path, body);
      toast(editing ? "نود خودکار ذخیره شد ✅" : "نود خودکار اضافه شد ✅");
      onSaved(r.job_started);
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  return (
    <Modal title={editing ? "✏️ ویرایش نود خودکار" : "🚀 افزودن نود خودکار"} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div style={{ border: "1px solid var(--p2)", borderRadius: 12, padding: 12, background: "rgba(99,102,241,.06)" }}>
          <p className="tiny" style={{ margin: 0, lineHeight: 1.9 }}>
            یک ورودی <b>اضافه</b> در ساب همه‌ی مشتری‌ها ساخته می‌شود که همیشه به سروری وصل است که
            <b> همین حالا کمترین کاربر آنلاین</b> را دارد (تعداد آنلاین‌ها زنده از پنل 3x-ui هر سرور خوانده می‌شود).
            یک کارگر پس‌زمینه مرتب این عددها را دوباره می‌خواند و ساب‌ها را کم‌کم بین سرورها پخش می‌کند تا بار یک‌جا جمع نشود و سرعت همه بالا بماند.
          </p>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
          <div className="field"><label>نام نمایشی</label>
            <input className="inp" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={AUTO_LABEL} />
          </div>
          <div className="field"><label>اولویت</label>
            <input className="inp" type="number" min="1" value={priority} onChange={(e) => setPriority(e.target.value)} dir="ltr" />
          </div>
        </div>
        <p className="muted tiny" style={{ margin: "-4px 0 0" }}>عدد <b>کمتر</b> یعنی این نود <b>بالاتر</b> در لیست مشتری دیده می‌شود.</p>

        <div className="field">
          <label>استخر نودها (این نود فقط بین این‌ها جابه‌جا می‌شود)</label>
          <div className="chips">
            <button className={"chip" + (!pool.length ? " on" : "")} onClick={() => setPool([])}>همه‌ی نودهای فعال</button>
            {nodes.map((n) => (
              <button key={n.id} className={"chip" + (pool.includes(n.id) ? " on" : "")} onClick={() => member(n.id)}>
                {n.label || n.server_name}
              </button>
            ))}
          </div>
          <p className="muted tiny" style={{ margin: "2px 0 0" }}>
            پیش‌فرض <b>خالی</b> است، یعنی همه‌ی نودهای فعال. اگر چند نود را انتخاب کنید فقط همان‌ها در گردش قرار می‌گیرند.
          </p>
        </div>

        <div className="row between" style={{ padding: "2px 0" }}>
          <span style={{ fontSize: ".85rem" }}>نمایش نام سرور فعلی کنار برچسب</span>
          <button className={"btn xs " + (showServer ? "success" : "")} onClick={() => setShowServer(!showServer)}>
            {showServer ? "✅ روشن" : "⭕️ خاموش"}
          </button>
        </div>
        <p className="muted tiny" style={{ margin: "-6px 0 0" }}>
          اگر روشن باشد، مشتری کنار نام این نود می‌بیند که همین حالا روی کدام سرور است.
        </p>

        <div className="field"><label>🌐 دامین اتصال اختصاصی (اختیاری)</label>
          <input className="inp" value={host} onChange={(e) => setHost(e.target.value)} dir="ltr" placeholder="مثال: auto.bagsale.click" />
          <p className="muted tiny" style={{ margin: "2px 0 0" }}>
            اگر پر شود، فقط <b>آدرس اتصال</b> این نود با این دامین جایگزین می‌شود. خالی = آدرس خود سروری که انتخاب شده.
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
  // Guard against a fork returning objects instead of JSON strings ([object Object]).
  const asText = (v) => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v, null, 2));

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
            <textarea style={ta} value={asText(inb.settings)} onChange={(e) => upd("settings", e.target.value)} /></div>
          <div className="field"><label>streamSettings (JSON)</label>
            <textarea style={ta} value={asText(inb.streamSettings)} onChange={(e) => upd("streamSettings", e.target.value)} /></div>
          <div className="field"><label>sniffing (JSON)</label>
            <textarea style={ta} value={asText(inb.sniffing)} onChange={(e) => upd("sniffing", e.target.value)} /></div>
          <p className="muted tiny" style={{ margin: 0 }}>پس از ذخیره، لینک همه ساب‌های این نود به‌صورت خودکار بازسازی می‌شود.</p>
          <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره اینباند"}</button>
        </div>
      )}
    </Modal>
  );
}

// ─────────────────────────────── auto node: tuning knobs ─────────────────────
function Knob({ label, suffix, hint, value, onChange }) {
  return (
    <div className="field">
      <label>{label}{suffix ? ` (${suffix})` : ""}</label>
      <input className="inp" type="number" min="0" value={value} onChange={(e) => onChange(e.target.value)} dir="ltr" />
      <span className="muted tiny">{hint}</span>
    </div>
  );
}

function AutoSettings({ settings, enabled, onSaved }) {
  const st = settings || {};
  const [f, setF] = useState({
    on: enabled ? "1" : "0",
    poll: st.poll_seconds ?? 120,
    stale: st.stale_seconds ?? 900,
    margin: Math.round((Number(st.margin) || 0) * 100),   // نسبت → درصد
    delta: st.min_delta ?? 3,
    cooldown: st.cooldown_minutes ?? 60,
    moves: st.max_moves ?? 25,
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const num = (v) => { const n = Number(String(v ?? "").replace(/[^\d.]/g, "")); return isFinite(n) && n > 0 ? n : 0; };

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.post("/subs/autonode/settings", {
        autonode_enabled: f.on,
        autonode_poll_seconds: String(num(f.poll)),
        autonode_stale_seconds: String(num(f.stale)),
        autonode_margin: String(num(f.margin) / 100),      // ۲۵٪ → 0.25
        autonode_min_delta: String(num(f.delta)),
        autonode_cooldown_minutes: String(num(f.cooldown)),
        autonode_max_moves: String(num(f.moves)),
      });
      toast("تنظیمات نود خودکار ذخیره شد ✅");
      onSaved(r.autonode);
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  return (
    <div className="grid" style={{ gap: 10, marginTop: 10, borderTop: "1px solid var(--bd)", paddingTop: 12 }}>
      <div className="row between">
        <span style={{ fontSize: ".85rem", fontWeight: 600 }}>پخش خودکار بار</span>
        <button className={"btn xs " + (f.on === "1" ? "success" : "")} onClick={() => set("on", f.on === "1" ? "0" : "1")}>
          {f.on === "1" ? "✅ روشن" : "⭕️ خاموش"}
        </button>
      </div>
      <p className="muted tiny" style={{ margin: "-4px 0 0" }}>
        خاموش کنید تا کارگر پس‌زمینه دیگر کسی را جابه‌جا نکند (نود خودکار سر جایش می‌ماند).
      </p>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Knob label="فاصله‌ی خواندن آنلاین‌ها" suffix="ثانیه" value={f.poll} onChange={(v) => set("poll", v)}
              hint="هر چند ثانیه یک‌بار تعداد کاربران آنلاین از پنل هر سرور خوانده شود." />
        <Knob label="اعتبار عدد آنلاین" suffix="ثانیه" value={f.stale} onChange={(v) => set("stale", v)}
              hint="عددی قدیمی‌تر از این دیگر معتبر نیست و آن سرور «نامشخص» حساب می‌شود." />
        <Knob label="آستانه‌ی اختلاف" suffix="٪" value={f.margin} onChange={(v) => set("margin", v)}
              hint="جابه‌جایی فقط وقتی که بار سرور فعلی دست‌کم این درصد بیشتر از بهترین سرور باشد." />
        <Knob label="حداقل اختلاف کاربر" suffix="نفر" value={f.delta} onChange={(v) => set("delta", v)}
              hint="…و اختلاف دست‌کم این تعداد کاربر آنلاین باشد؛ جلوی جابه‌جایی بی‌دلیل را می‌گیرد." />
        <Knob label="فاصله‌ی امن هر ساب" suffix="دقیقه" value={f.cooldown} onChange={(v) => set("cooldown", v)}
              hint="یک ساب تا این مدت بعد از جابه‌جایی، دوباره جابه‌جا نمی‌شود." />
        <Knob label="سقف جابه‌جایی هر دور" suffix="ساب" value={f.moves} onChange={(v) => set("moves", v)}
              hint="در هر دور توزیع، حداکثر این تعداد ساب جابه‌جا می‌شود تا تغییرات تدریجی بماند." />
      </div>
      <button className="btn sm primary" disabled={busy} onClick={save} style={{ justifySelf: "start" }}>
        {busy ? "…" : "💾 ذخیره تنظیمات"}
      </button>
    </div>
  );
}

// ─────────────────────────────── auto node: server load ──────────────────────
function AutoNodePanel({ auto, normalNodes, onAdd, onEdit, onAuto, onOps }) {
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState(false);
  const servers = auto.servers || [];
  const autos = auto.nodes || [];
  // Unknown counts never contribute to the peak — they are not zeros.
  const peak = Math.max(1, ...servers.map((s) => (s.online == null ? 0 : Number(s.online) || 0)));

  const refresh = async () => {
    setBusy("refresh");
    try {
      const r = await api.post("/subs/autonode/refresh");
      onAuto(r.autonode);
      toast(`✅ ${fmt(r.polled)} سرور خوانده شد` + (r.unknown ? ` — ${fmt(r.unknown)} نامشخص` : ""));
    } catch (e) { toast(e.message || "خطا در به‌روزرسانی", "error"); } finally { setBusy(""); }
  };
  const rebalance = async () => {
    setBusy("rebalance");
    try {
      const r = await api.post("/subs/autonode/rebalance");
      if (r.job_started) onOps();
      toast("توزیع مجدد شروع شد ⚖️ — گزارش زنده در «همگام‌سازی نودها» بالای صفحه");
    } catch (e) { toast(e.message || "توزیع مجدد شروع نشد", "error"); } finally { setBusy(""); }
  };

  return (
    <Card
      title="🚀 نود خودکار"
      sub="یک ورودی اضافه در ساب همه‌ی مشتری‌ها که همیشه روی کم‌بارترین سرور است"
      right={<span className={"badge " + (auto.enabled ? "b-green" : "b-gray")}>{auto.enabled ? "پخش بار روشن" : "پخش بار خاموش"}</span>}
    >
      {!autos.length ? (
        <div className="row between" style={{ gap: 10, flexWrap: "wrap" }}>
          <p className="muted tiny" style={{ margin: 0, maxWidth: 620, lineHeight: 1.9 }}>
            هنوز نود خودکاری ساخته نشده است. با ساختن آن، یک ورودی اضافه به ساب همه‌ی مشتری‌ها اضافه می‌شود که
            همیشه به سروری وصل است که همین حالا کمترین کاربر آنلاین را دارد؛ بار بین سرورها پخش می‌شود و سرعت بالا می‌ماند.
          </p>
          <button className="btn sm primary" onClick={onAdd} disabled={!normalNodes.length}>🚀 افزودن نود خودکار</button>
        </div>
      ) : (
        <div className="grid" style={{ gap: 8 }}>
          {autos.map((a) => (
            <div key={a.id} className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6 }}>
                  <b style={{ fontSize: ".9rem" }}>{a.label || "نود خودکار"}</b>
                  <span className={"badge " + (a.is_active ? "b-green" : "b-red")}>{a.is_active ? "فعال" : "غیرفعال"}</span>
                  {a.auto_show_server ? <span className="badge b-gray">نام سرور روی برچسب</span> : null}
                  {a.connect_host ? <span className="badge b-blue">🌐 {a.connect_host}</span> : null}
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 5 }}>
                  <span className="muted tiny">استخر: {fmt((a.candidates || []).length)} سرور</span>
                  <span className="muted tiny">سرویس‌های روی این نود: {fmt(a.assigned_total)}</span>
                  <span className="muted tiny">اولویت: {a.priority}</span>
                </div>
                {(a.candidates || []).length ? (
                  <div className="row" style={{ gap: 5, flexWrap: "wrap", marginTop: 6 }}>
                    {a.candidates.map((c) => (
                      <span key={c.id} className={"badge " + (c.online == null ? "b-yellow" : "b-gray")} title={`سرور: ${c.server_name}`}>
                        {c.label} · {onlineText(c.online)} · {fmt(c.assigned)} ساب
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="muted tiny" style={{ marginTop: 6 }}>هیچ نود قابل استفاده‌ای در استخر نیست.</div>
                )}
              </div>
              <button className="btn xs" onClick={() => onEdit(a)}>✏️ ویرایش</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--bd)", marginTop: 12, paddingTop: 12 }}>
        <div className="row between" style={{ marginBottom: 8 }}>
          <b style={{ fontSize: ".85rem" }}>📊 بار سرورها</b>
          <span className="muted tiny">از کم‌بارترین به پربارترین</span>
        </div>
        {!servers.length ? (
          <p className="muted tiny" style={{ margin: 0 }}>هنوز سروری ثبت نشده است.</p>
        ) : (
          <div className="grid" style={{ gap: 9 }}>
            {servers.map((s) => {
              const unknown = s.online == null;
              const pct = unknown ? 100 : Math.max(2, Math.round((Number(s.online) || 0) / peak * 100));
              return (
                <div key={s.id} className="row between" style={{ gap: 10, alignItems: "center" }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="row" style={{ gap: 6 }}>
                      <span style={{ fontSize: ".84rem", fontWeight: 600 }}>{s.name}</span>
                      {unknown
                        ? <span className="badge b-yellow" title="پنل این سرور پاسخ نداد — این عدد صفر نیست، نامشخص است.">⚠️ نامشخص</span>
                        : <span className="muted tiny">{fmt(s.online)} کاربر آنلاین</span>}
                      {s.stale ? <span className="badge b-yellow">عدد کهنه</span> : null}
                      {!s.is_active ? <span className="badge b-gray">سرور غیرفعال</span> : null}
                    </div>
                    <div style={{ height: 5, background: "rgba(255,255,255,.07)", borderRadius: 4, marginTop: 6, overflow: "hidden" }}>
                      <div style={{
                        width: `${pct}%`, height: "100%",
                        background: unknown
                          ? "repeating-linear-gradient(90deg, rgba(251,191,36,.45) 0 5px, transparent 5px 10px)"
                          : "var(--p2)",
                      }} />
                    </div>
                  </div>
                  <span className="muted tiny" style={{ whiteSpace: "nowrap" }}>{agoFa(s.checked_at)}</span>
                </div>
              );
            })}
          </div>
        )}
        <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <button className="btn sm" disabled={!!busy} onClick={refresh}>{busy === "refresh" ? "…" : "🔄 به‌روزرسانی الان"}</button>
          <button className="btn sm" disabled={!!busy || !autos.length} onClick={rebalance}>{busy === "rebalance" ? "…" : "⚖️ توزیع مجدد الان"}</button>
          {autos.length ? <button className="btn sm primary" onClick={onAdd} disabled={!normalNodes.length}>🚀 افزودن نود خودکار</button> : null}
          <button className="btn sm ghost" onClick={() => setOpen(!open)}>{open ? "بستن تنظیمات" : "⚙️ تنظیمات"}</button>
        </div>
        {!normalNodes.length && (
          <p className="muted tiny" style={{ margin: "8px 0 0" }}>برای نود خودکار اول باید حداقل یک نود معمولی بسازید.</p>
        )}
      </div>

      {open && <AutoSettings settings={auto.settings} enabled={auto.enabled} onSaved={onAuto} />}
    </Card>
  );
}

// ─────────────────────────────── page ────────────────────────────────────────
export default function Subscriptions() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);      // {kind:'node'|'auto'|'inbound', node}
  const [ops, setOps] = useState(false);          // nodeops running/watching
  const [sync, setSync] = useState(false);        // full sync running/watching

  const load = () => { api.get("/api/subs").then(setData).catch(() => setData({ nodes: [], servers: [] })); };
  useEffect(() => { load(); }, []);

  // refresh / settings return a fresh `autonode` — swap it in without a reload.
  const setAuto = (autonode) => { if (autonode) setData((d) => (d ? { ...d, autonode } : d)); };

  const act = async (fn, watchOps = true) => {
    try {
      const r = await fn();
      if (watchOps && r && r.job_started) setOps(true);
      load();
      return r;
    } catch (e) { toast(e.message || "خطا", "error"); }
  };

  const toggle = (n) => act(() => api.post(`/subs/nodes/${n.id}/toggle`));
  const del = (n) => { if (confirm(`نود «${n.label || n.server_name || "خودکار"}» حذف شود؟ از همه لینک‌ها هم پاک می‌شود.`)) act(() => api.post(`/subs/nodes/${n.id}/delete`)); };
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
  const auto = data.autonode || null;
  const normalNodes = nodes.filter((n) => !n.is_auto);
  const autoById = {};
  (auto?.nodes || []).forEach((a) => { autoById[a.id] = a; });

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="🔄 همگام‌سازی نودها" sub="افزودن/غیرفعال‌سازی نودها به‌صورت لحظه‌ای اعمال می‌شود؛ این‌ها فقط برای بازبینی کلی‌اند.">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn sm" disabled={sync} onClick={() => startSync(false)}>⚡ سریع (نودهای ناقص)</button>
          <button className="btn sm" disabled={sync} onClick={() => startSync(true)}>🔁 بازسازی کامل لینک‌ها</button>
          <button className="btn sm primary" onClick={() => setModal({ kind: "node" })} disabled={!servers.length}>➕ افزودن نود</button>
          {auto && (
            <button className="btn sm primary" onClick={() => setModal({ kind: "auto" })} disabled={!normalNodes.length}
                    title="یک ورودی اضافه که همیشه روی کم‌بارترین سرور است">🚀 افزودن نود خودکار</button>
          )}
        </div>
        {!servers.length && <p className="muted tiny" style={{ marginTop: 8 }}>اول از پنل قدیم یک سرور اضافه کنید.</p>}
        <OpsLog logPath="/subs/sync-nodes/log" active={sync} title="گزارش همگام‌سازی کامل" onIdle={() => { setSync(false); load(); }} />
        <OpsLog logPath="/subs/nodes/ops/log" active={ops} title="گزارش عملیات لحظه‌ای نود" onIdle={() => { setOps(false); load(); }} />
      </Card>

      {auto && (
        <AutoNodePanel
          auto={auto} normalNodes={normalNodes}
          onAdd={() => setModal({ kind: "auto" })}
          onEdit={(a) => setModal({ kind: "auto", node: nodes.find((x) => x.id === a.id) || a })}
          onAuto={setAuto}
          onOps={() => setOps(true)}
        />
      )}

      {!nodes.length ? (
        <Card><Empty emoji="🧬">هنوز نودی برای ساب تعریف نشده است.</Empty></Card>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          {nodes.map((n) => {
            // An auto node has no server of its own (server_id=0, negative
            // inbound_id) — never show either, and don't gate it on server_active.
            const isAuto = !!n.is_auto;
            const on = isAuto ? !!n.is_active : !!(n.is_active && n.server_active);
            const info = isAuto ? autoById[n.id] : null;
            const poolCount = info ? (info.candidates || []).length : parsePool(n.auto_pool).length;
            return (
              <Card key={n.id}>
                <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700 }}>
                      {isAuto ? (
                        <>{n.label || "نود خودکار"} <span className="badge b-purple">🚀 خودکار</span></>
                      ) : (
                        <>{n.label || n.server_name} <span className="muted mono">#{n.inbound_id}</span></>
                      )}
                    </div>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                      <span className={"badge " + (on ? "b-green" : "b-red")}>{on ? "فعال" : "غیرفعال"}</span>
                      <span className={"badge " + (n.usable ? "b-green" : "b-yellow")}>{n.usable_label}</span>
                      {isAuto ? (
                        <>
                          <span className="muted tiny">استخر: {fmt(poolCount)} سرور</span>
                          <span className="muted tiny">سرویس‌های روی این نود: {fmt(n.active_profiles)}</span>
                          <span className="muted tiny">اولویت: {n.priority}</span>
                          {n.auto_show_server ? <span className="badge b-gray">نام سرور روی برچسب</span> : null}
                        </>
                      ) : (
                        <>
                          <span className="muted tiny">سرور: {n.server_name}</span>
                          <span className="muted tiny">اولویت: {n.priority}</span>
                          <span className="muted tiny">ظرفیت: {n.active_profiles}/{n.max_active_profiles || "∞"}</span>
                        </>
                      )}
                      {n.connect_host ? <span className="badge b-blue">🌐 {n.connect_host}</span> : null}
                    </div>
                    <div className="muted tiny" style={{ marginTop: 4 }}>
                      {isAuto
                        ? "همیشه به سروری وصل می‌شود که همین حالا کمترین کاربر آنلاین را دارد."
                        : <span className="mono">{n.server_url}</span>}
                    </div>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                    {!isAuto && <button className="btn xs" onClick={() => testNode(n)}>🔗 تست</button>}
                    {!isAuto && <button className="btn xs" onClick={() => setModal({ kind: "inbound", node: n })}>🛠 اینباند</button>}
                    <button className="btn xs" onClick={() => reconcile(n)}>♻️ بازسازی لینک‌ها</button>
                    <button className="btn xs" onClick={() => setModal({ kind: isAuto ? "auto" : "node", node: n })}>✏️ ویرایش</button>
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
      {modal?.kind === "auto" && (
        <AutoNodeModal node={modal.node} nodes={normalNodes} onClose={() => setModal(null)}
          onSaved={(jobStarted) => { setModal(null); if (jobStarted) setOps(true); load(); }} />
      )}
      {modal?.kind === "inbound" && (
        <InboundModal node={modal.node} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); setOps(true); load(); }} />
      )}
    </div>
  );
}
