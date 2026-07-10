import React, { useState } from "react";
import { BASE } from "../api.js";

const NAV = [
  { k: "/dashboard", icon: "📊", label: "داشبورد" },
  { k: "/users", icon: "👥", label: "کاربران" },
  { k: "/orders", icon: "🧾", label: "سفارش‌ها", badgeKey: "pending_orders" },
  { k: "/subs", icon: "🧬", label: "نودهای ساب" },
  { k: "/subprofiles", icon: "📄", label: "ساب‌های کاربران" },
  { k: "/servers", icon: "🖥", label: "سرورها" },
  { k: "/packages", icon: "📦", label: "پکیج‌ها" },
  { k: "/proxy", icon: "🛰", label: "پروکسی تلگرام" },
  { k: "/discounts", icon: "🎟", label: "تخفیف‌ها" },
  { k: "/campaigns", icon: "📣", label: "کمپین‌ها" },
  { k: "/settings", icon: "⚙️", label: "تنظیمات" },
];

// Pages not migrated yet → deep-link into the existing (legacy) panel so the
// admin keeps full access during the parallel rollout.
const LEGACY = [
  { path: "/configs", icon: "🔑", label: "کانفیگ‌ها" },
  { path: "/referrals", icon: "🎁", label: "رفرال" },
  { path: "/miniapp", icon: "📱", label: "مینی‌اپ" },
];

const TITLES = { "/dashboard": "داشبورد", "/users": "کاربران", "/orders": "سفارش‌ها", "/subs": "نودهای ساب", "/subprofiles": "ساب‌های کاربران", "/servers": "سرورها", "/packages": "پکیج‌ها", "/proxy": "پروکسی تلگرام", "/discounts": "تخفیف‌ها", "/campaigns": "کمپین‌ها", "/settings": "تنظیمات" };

export default function Shell({ path, go, badges = {}, children, onLogout }) {
  const [open, setOpen] = useState(false);
  const base = "/" + path.split("/").filter(Boolean)[0];
  const nav = (p) => { go(p); setOpen(false); };
  const title = TITLES[base] || "پنل اطلس";

  return (
    <div className="shell">
      <div className={"scrim" + (open ? " show" : "")} onClick={() => setOpen(false)} />
      <aside className={"sidebar" + (open ? " open" : "")}>
        <div className="brand">
          <div className="brand-logo">🛡️</div>
          <div>
            <div className="brand-name">Atlas Panel</div>
            <div className="brand-sub">پنل مدیریت</div>
          </div>
        </div>

        <div className="nav-group-label">اصلی</div>
        {NAV.map((n) => (
          <div key={n.k} className={"nav-item" + (base === n.k ? " active" : "")} onClick={() => nav(n.k)}>
            <span className="nav-ico">{n.icon}</span><span>{n.label}</span>
            {n.badgeKey && badges[n.badgeKey] > 0 && <span className="nav-badge">{badges[n.badgeKey]}</span>}
          </div>
        ))}

        <div className="nav-group-label">هنوز در پنل قدیم</div>
        {LEGACY.map((n) => (
          <a key={n.path} className="nav-item" href={`${BASE}${n.path}`}>
            <span className="nav-ico">{n.icon}</span><span>{n.label}</span>
            <span className="nav-badge" style={{ background: "rgba(255,255,255,.08)", color: "var(--txt3)" }}>↗</span>
          </a>
        ))}

        <div className="sidebar-foot">
          <div className="nav-item" onClick={onLogout}>
            <span className="nav-ico">🚪</span><span>خروج</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="hamburger" onClick={() => setOpen(true)}>☰</button>
          <div>
            <h1>{title}</h1>
            <div className="crumb">Atlas · مدیریت</div>
          </div>
          <div className="topbar-spacer" />
          <a className="btn sm ghost" href={`${BASE}/dashboard`}>پنل قدیم</a>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
