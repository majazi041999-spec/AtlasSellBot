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

/* ── sort / filter toolbar ──────────────────────────────────────────────
   Shared by every list page so search + sort + filter look identical
   everywhere. All three are controlled; pages own the state (and usually
   persist it through usePref). */

export function Toolbar({ children, right }) {
  return (
    <div className="toolbar">
      <div className="toolbar-main">{children}</div>
      {right && <div className="toolbar-right">{right}</div>}
    </div>
  );
}

export function Search({ value, onChange, placeholder }) {
  return (
    <div className="search">
      <span className="search-i">🔍</span>
      <input className="inp search-inp" value={value} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} />
      {value ? <button className="search-x" title="پاک کردن" onClick={() => onChange("")}>✕</button> : null}
    </div>
  );
}

/** options: [{k, label}] */
export function Select({ label, value, onChange, options }) {
  return (
    <label className="sel">
      {label ? <span className="sel-lbl">{label}</span> : null}
      <select className="inp sel-inp" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.k} value={o.k}>{o.label}</option>)}
      </select>
    </label>
  );
}

/** options: [{k, label, count?}] */
export function Chips({ options, value, onChange }) {
  return (
    <div className="chips">
      {options.map((o) => (
        <button key={o.k} className={"chip" + (value === o.k ? " on" : "")}
                onClick={() => onChange(o.k)}>
          {o.label}
          {o.count != null ? <em className="chip-n">{o.count}</em> : null}
        </button>
      ))}
    </div>
  );
}

/** Clickable table header. `pair` = [ascKey, descKey]; clicking flips between
    them, and the active direction shows an arrow. */
export function SortTh({ children, pair, sort, onSort, style }) {
  const [asc, desc] = pair || [];
  const active = sort === asc || sort === desc;
  const next = sort === desc ? asc : desc;   // first click = descending
  return (
    <th className={"sort-th" + (active ? " on" : "")} style={style}
        onClick={() => onSort(next)} title="مرتب‌سازی">
      {children}<span className="sort-ar">{active ? (sort === asc ? "▲" : "▼") : "↕"}</span>
    </th>
  );
}

/** State that survives navigation + reloads (per-key, localStorage). */
export function usePref(key, initial) {
  const k = "atlas.pref." + key;
  const [v, setV] = useState(() => {
    try { return localStorage.getItem(k) ?? initial; } catch (e) { return initial; }
  });
  return [v, (nv) => { setV(nv); try { localStorage.setItem(k, nv); } catch (e) {} }];
}

export function timeAgo(s) {
  if (!s) return "";
  const t = new Date(String(s).replace(" ", "T")).getTime();
  if (!t) return s;
  const m = Math.floor(Math.max(0, Date.now() - t) / 60000);
  if (m < 1) return "همین حالا";
  if (m < 60) return `${m} دقیقه پیش`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ساعت پیش`;
  return `${Math.floor(h / 24)} روز پیش`;
}

// comma-format an input's value live (digits only)
export function liveNum(e) {
  const raw = e.target.value.replace(/[^\d-]/g, "");
  const neg = raw.startsWith("-");
  const digits = raw.replace(/-/g, "");
  e.target.value = digits ? (neg ? "-" : "") + Number(digits).toLocaleString("en-US") : (neg ? "-" : "");
}
export function rawNum(v) { return parseInt(String(v ?? "").replace(/[^\d-]/g, "") || "0", 10) || 0; }
