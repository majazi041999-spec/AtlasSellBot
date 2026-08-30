import React, { useState, useEffect } from "react";
import { api } from "../api.js";

const NAV = [
  { k: "/dashboard", icon: "📊", label: "داشبورد" },
  { k: "/users", icon: "👥", label: "کاربران" },
  { k: "/reps", icon: "🏢", label: "نمایندگان" },
  { k: "/orders", icon: "🧾", label: "سفارش‌ها", badgeKey: "pending_orders" },
  { k: "/subs", icon: "🧬", label: "نودهای ساب" },
  { k: "/subprofiles", icon: "📄", label: "ساب‌های کاربران" },
  { k: "/servers", icon: "🖥", label: "سرورها" },
  { k: "/packages", icon: "📦", label: "پکیج‌ها" },
  { k: "/proxy", icon: "🛰", label: "پروکسی تلگرام" },
  { k: "/discounts", icon: "🎟", label: "تخفیف‌ها" },
  { k: "/campaigns", icon: "📣", label: "کمپین‌ها" },
  { k: "/referrals", icon: "🎁", label: "رفرال" },
  { k: "/clientapp", icon: "📱", label: "اپ اندروید" },
  { k: "/appstats", icon: "📈", label: "آمار و اعلان اپ" },
  { k: "/appdiag", icon: "🩺", label: "تشخیص سرورها" },
  { k: "/transactions", icon: "🧾", label: "رسیدها" },
];

// Second group: setup, records and maintenance. Everything the retired
// server-rendered panel used to own lives here now — there is no second panel
// to deep-link into any more.
const TOOLS = [
  { k: "/miniapp", icon: "📱", label: "مینی‌اپ" },
  { k: "/reports", icon: "📅", label: "گزارش روزانه" },
  { k: "/configs", icon: "🔑", label: "کانفیگ‌های قدیمی" },
  { k: "/legacy-claims", icon: "📥", label: "درخواست انتقال" },
  { k: "/backups", icon: "💾", label: "پشتیبان‌گیری" },
  { k: "/settings", icon: "⚙️", label: "تنظیمات" },
  { k: "/update", icon: "🔄", label: "به‌روزرسانی" },
];

const TITLES = { "/dashboard": "داشبورد", "/users": "کاربران", "/reps": "نمایندگان", "/orders": "سفارش‌ها", "/subs": "نودهای ساب", "/subprofiles": "ساب‌های کاربران", "/servers": "سرورها", "/packages": "پکیج‌ها", "/proxy": "پروکسی تلگرام", "/discounts": "تخفیف‌ها", "/campaigns": "کمپین‌ها", "/referrals": "رفرال", "/clientapp": "اپ اندروید", "/appstats": "آمار و اعلان اپ", "/appdiag": "تشخیص سرورها", "/transactions": "رسیدها", "/miniapp": "مینی‌اپ", "/reports": "گزارش روزانه", "/configs": "کانفیگ‌های قدیمی", "/legacy-claims": "درخواست انتقال", "/backups": "پشتیبان‌گیری", "/settings": "تنظیمات", "/update": "به‌روزرسانی" };

export default function Shell({ path, go, badges = {}, children, onLogout }) {
  const [open, setOpen] = useState(false);
  const [brand, setBrand] = useState({ brand_name: "Atlas Panel", logo: "" });
  useEffect(() => { api.get("/api/branding").then(setBrand).catch(() => {}); }, []);
  const base = "/" + path.split("/").filter(Boolean)[0];
  const nav = (p) => { go(p); setOpen(false); };
  const title = TITLES[base] || "پنل اطلس";

  return (
    <div className="shell">
      <div className={"scrim" + (open ? " show" : "")} onClick={() => setOpen(false)} />
      <aside className={"sidebar" + (open ? " open" : "")}>
        <div className="brand">
          <div className="brand-logo" style={brand.logo ? { padding: 0, overflow: "hidden" } : undefined}>
            {brand.logo ? <img src={brand.logo} alt="logo" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 13 }} /> : "🛡️"}
          </div>
          <div>
            <div className="brand-name">{brand.brand_name || "Atlas Panel"}</div>
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

        <div className="nav-group-label">تنظیمات و ابزارها</div>
        {TOOLS.map((n) => (
          <div key={n.k} className={"nav-item" + (base === n.k ? " active" : "")} onClick={() => nav(n.k)}>
            <span className="nav-ico">{n.icon}</span><span>{n.label}</span>
          </div>
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
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
