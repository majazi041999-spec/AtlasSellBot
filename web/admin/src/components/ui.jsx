import React, { useEffect, useState } from "react";

export function Spinner({ lg }) { return <div className={"spinner" + (lg ? " lg" : "")} />; }
export function Loading() { return <div className="loading-screen"><Spinner lg /></div>; }

/* ── toast ── */
let _toastId = 0;
const _listeners = new Set();
export function toast(msg, kind = "success") {
  const t = { id: ++_toastId, msg, kind };
  _listeners.forEach((l) => l(t));
}
export function ToastHost() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const add = (t) => {
      setItems((s) => [...s, t]);
      setTimeout(() => setItems((s) => s.filter((x) => x.id !== t.id)), 2600);
    };
    _listeners.add(add);
    return () => _listeners.delete(add);
  }, []);
  return (
    <div className="toast-wrap">
      {items.map((t) => <div key={t.id} className={"toast " + t.kind}>{t.msg}</div>)}
    </div>
  );
}

export function Stat({ icon, value, label, foot, grad }) {
  return (
    <div className="stat" style={grad ? { "--grad": grad } : undefined}>
      <div className="stat-ico" style={grad ? { background: grad } : undefined}>{icon}</div>
      <div className="stat-val">{value}</div>
      <div className="stat-lbl">{label}</div>
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  );
}

export function Card({ title, sub, right, children, style }) {
  return (
    <div className="card" style={style}>
      {(title || right) && (
        <div className="card-h between">
          <div className="row" style={{ gap: 8 }}>
            {title && <h3>{title}</h3>}
            {sub && <span className="sub">{sub}</span>}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Empty({ emoji = "📭", children }) {
  return <div className="empty"><div className="em">{emoji}</div>{children}</div>;
}

export function Modal({ title, children, onClose }) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {title && <h3>{title}</h3>}
        {children}
      </div>
    </div>
  );
}

export function Pager({ page, totalPages, onGo }) {
  if (totalPages <= 1) return null;
  return (
    <div className="pager">
      <button className="btn sm" disabled={page <= 1} onClick={() => onGo(page - 1)}>قبلی ›</button>
      <span className="muted tiny">صفحه {page} از {totalPages}</span>
      <button className="btn sm" disabled={page >= totalPages} onClick={() => onGo(page + 1)}>‹ بعدی</button>
    </div>
  );
}

export function Avatar({ name }) {
  const ch = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return <div className="avatar">{ch}</div>;
}

// comma-format an input's value live (digits only)
export function liveNum(e) {
  const raw = e.target.value.replace(/[^\d-]/g, "");
  const neg = raw.startsWith("-");
  const digits = raw.replace(/-/g, "");
  e.target.value = digits ? (neg ? "-" : "") + Number(digits).toLocaleString("en-US") : (neg ? "-" : "");
}
export function rawNum(v) { return parseInt(String(v ?? "").replace(/[^\d-]/g, "") || "0", 10) || 0; }
