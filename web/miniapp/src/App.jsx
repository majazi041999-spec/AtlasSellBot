import React, { useEffect, useState, useCallback } from "react";

const tg = window.Telegram?.WebApp;
const INIT = tg?.initData || "";

async function api(path, body) {
  const r = await fetch(`/app/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": INIT },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const gb = (bytes) => (Number(bytes || 0) / 1073741824);
function remainText(s) {
  const total = (s.traffic_gb || 0) * 1073741824;
  const remaining = total > 0 ? Math.max(0, total - (s.used_bytes || 0)) : -1;
  const volTxt = remaining < 0 ? "نامحدود" : `${gb(remaining).toFixed(1)} GB`;
  let days = -1;
  if (s.expire_ts > 0) days = Math.max(0, Math.ceil((s.expire_ts - Date.now()) / 86400000));
  const dayTxt = days < 0 ? "بدون انقضا" : `${days} روز`;
  return { volTxt, dayTxt, remaining, total };
}

function copy(text) {
  try { navigator.clipboard.writeText(text); } catch (e) {
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    document.execCommand("copy"); t.remove();
  }
  tg?.HapticFeedback?.notificationOccurred?.("success");
}

function Spinner() { return <div className="spinner" />; }

function Header({ brand, user, balance }) {
  return (
    <div className="hero">
      <div className="hero-top">
        <div className="brand">
          <span className="brand-logo">{brand?.logo || "🌐"}</span>
          <span className="brand-name">{brand?.title || "Atlas"}</span>
        </div>
        <div className="hello">سلام {user?.name || ""} 👋</div>
      </div>
      <div className="wallet-pill">
        <span>کیف پول</span>
        <b>{fmt(balance)} <small>تومان</small></b>
      </div>
    </div>
  );
}

function Home({ data, go }) {
  const tiles = [
    { k: "buy", icon: "🛒", label: "خرید سرویس", grad: "linear-gradient(135deg,#7c6fff,#a78bfa)" },
    { k: "services", icon: "📡", label: "سرویس‌های من", grad: "linear-gradient(135deg,#10b981,#34d399)" },
    { k: "wallet", icon: "💳", label: "کیف پول", grad: "linear-gradient(135deg,#0891b2,#22d3ee)" },
    { k: "referral", icon: "🎁", label: "دعوت دوستان", grad: "linear-gradient(135deg,#f43f5e,#fb7185)" },
  ];
  return (
    <div className="screen">
      <div className="stat-row">
        <div className="mini-stat">
          <div className="mini-val">{data.stats?.active_services ?? 0}</div>
          <div className="mini-lbl">سرویس فعال</div>
        </div>
        <div className="mini-stat">
          <div className="mini-val">{fmt(data.user?.balance)}</div>
          <div className="mini-lbl">موجودی (تومان)</div>
        </div>
      </div>
      <div className="tiles">
        {tiles.map((t) => (
          <button key={t.k} className="tile" onClick={() => go(t.k)}>
            <span className="tile-icon" style={{ background: t.grad }}>{t.icon}</span>
            <span className="tile-label">{t.label}</span>
          </button>
        ))}
      </div>
      {data.support && (
        <a className="support-card" href={`https://t.me/${data.support}`} target="_blank" rel="noreferrer">
          <span>☎️ پشتیبانی</span><span className="chev">›</span>
        </a>
      )}
    </div>
  );
}

function Services({ go }) {
  const [list, setList] = useState(null);
  useEffect(() => { api("services").then((d) => setList(d.services || [])).catch(() => setList([])); }, []);
  if (list === null) return <div className="screen center"><Spinner /></div>;
  if (!list.length) return (
    <div className="screen center empty">
      <div className="empty-emoji">📭</div>
      <p>هنوز سرویسی نداری</p>
      <button className="btn-primary" onClick={() => go("buy")}>🛒 خرید سرویس</button>
    </div>
  );
  return (
    <div className="screen">
      <h2 className="screen-title">سرویس‌های من</h2>
      {list.map((s) => {
        const r = remainText(s);
        const pct = r.total > 0 ? Math.min(100, Math.round(((s.used_bytes || 0) / r.total) * 100)) : 0;
        return (
          <div className="card svc" key={s.id}>
            <div className="svc-head">
              <b>{s.name || "سرویس"}</b>
              <span className={"badge " + (s.is_active ? "ok" : "off")}>{s.is_active ? "فعال" : "غیرفعال"}</span>
            </div>
            <div className="svc-meta">
              <span>📊 {r.volTxt}</span><span>📅 {r.dayTxt}</span>
              <span>🖥 {(s.nodes || []).filter((n) => n.is_active).length} سرور</span>
            </div>
            {r.total > 0 && (
              <div className="bar"><div className="bar-fill" style={{ width: pct + "%", background: pct > 85 ? "#fb7185" : "#34d399" }} /></div>
            )}
            <div className="svc-actions">
              <button className="btn-primary sm" onClick={() => copy(s.sub_url)}>📋 کپی لینک</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Buy() {
  const [pkgs, setPkgs] = useState(null);
  const [order, setOrder] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("packages").then((d) => setPkgs(d.packages || [])).catch(() => setPkgs([])); }, []);
  const buy = async (id) => {
    setBusy(true);
    try { const d = await api("buy", { package_id: id }); setOrder(d); tg?.HapticFeedback?.notificationOccurred?.("success"); }
    catch (e) { tg?.showAlert?.("خطا در ثبت سفارش"); } finally { setBusy(false); }
  };
  if (order) return (
    <div className="screen">
      <h2 className="screen-title">پرداخت سفارش #{order.order_id}</h2>
      <div className="card pay">
        <div className="pay-amount">{fmt(order.payment?.amount)} <small>تومان</small></div>
        <div className="pay-row"><span>بانک</span><b>{order.payment?.bank || "-"}</b></div>
        <div className="pay-row card-num" onClick={() => copy(order.payment?.card)}>
          <span>شماره کارت (لمس=کپی)</span><b dir="ltr">{order.payment?.card}</b>
        </div>
        <div className="pay-row"><span>به نام</span><b>{order.payment?.holder || "-"}</b></div>
        <p className="muted">پس از واریز، رسید را در ربات بفرست تا سرویس فعال شود.</p>
        <button className="btn-primary" onClick={() => tg?.close?.()}>ارسال رسید در ربات</button>
      </div>
    </div>
  );
  if (pkgs === null) return <div className="screen center"><Spinner /></div>;
  return (
    <div className="screen">
      <h2 className="screen-title">خرید سرویس</h2>
      <div className="pkg-grid">
        {pkgs.map((p) => (
          <div className="card pkg" key={p.id}>
            <div className="pkg-name">{p.name}</div>
            <div className="pkg-spec">{p.traffic_gb} GB · {p.duration_days} روز</div>
            <div className="pkg-price">{fmt(p.price)} <small>تومان</small></div>
            <button className="btn-primary sm" disabled={busy} onClick={() => buy(p.id)}>خرید</button>
          </div>
        ))}
        {!pkgs.length && <p className="muted">فعلاً پکیجی موجود نیست.</p>}
      </div>
    </div>
  );
}

function Wallet() {
  const [w, setW] = useState(null);
  useEffect(() => { api("wallet").then(setW).catch(() => setW({ balance: 0, transactions: [] })); }, []);
  if (!w) return <div className="screen center"><Spinner /></div>;
  return (
    <div className="screen">
      <h2 className="screen-title">کیف پول</h2>
      <div className="card balance-card">
        <div className="balance-lbl">موجودی</div>
        <div className="balance-val">{fmt(w.balance)} <small>تومان</small></div>
      </div>
      <div className="card">
        <div className="list-title">تراکنش‌های اخیر</div>
        {(w.transactions || []).slice(0, 10).map((t, i) => (
          <div className="tx" key={i}>
            <span>{t.note || t.kind}</span>
            <b className={t.amount >= 0 ? "pos" : "neg"}>{t.amount >= 0 ? "+" : ""}{fmt(t.amount)}</b>
          </div>
        ))}
        {!(w.transactions || []).length && <p className="muted">تراکنشی ثبت نشده.</p>}
      </div>
    </div>
  );
}

function Referral() {
  const [d, setD] = useState(null);
  useEffect(() => { api("referral").then(setD).catch(() => setD(null)); }, []);
  if (!d) return <div className="screen center"><Spinner /></div>;
  const share = () => {
    const text = (d.caption || "به ما بپیوند!").replace("{link}", d.link);
    tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(d.link)}&text=${encodeURIComponent(d.caption_no_link || "")}`)
      || window.open(`https://t.me/share/url?url=${encodeURIComponent(d.link)}`);
  };
  return (
    <div className="screen">
      <h2 className="screen-title">دعوت دوستان</h2>
      <div className="card earn-card">
        <div className="earn-val">{fmt(d.earned)} <small>تومان</small></div>
        <div className="earn-lbl">جایزهٔ دریافتی شما</div>
        <div className="earn-sub">👥 {d.invited || 0} دعوت · 🛒 {d.converted || 0} خرید</div>
      </div>
      <div className="card link-card" onClick={() => copy(d.link)}>
        <div className="muted">لینک اختصاصی (لمس=کپی)</div>
        <div className="link-text" dir="ltr">{d.link}</div>
      </div>
      <button className="btn-primary" onClick={share}>📤 ارسال برای دوستان</button>
      {(d.tiers || []).length > 0 && (
        <div className="card">
          <div className="list-title">پله‌های جایزه</div>
          {d.tiers.map((t, i) => (
            <div className="tier" key={i}>
              <span>{t.reached ? "✅" : `⏳ ${d.converted}/${t.referrals_needed}`}</span>
              <span>{t.referrals_needed} دعوت → {t.reward}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TABS = [
  { k: "home", icon: "🏠", label: "خانه" },
  { k: "services", icon: "📡", label: "سرویس‌ها" },
  { k: "buy", icon: "🛒", label: "خرید" },
  { k: "wallet", icon: "💳", label: "کیف پول" },
  { k: "referral", icon: "🎁", label: "دعوت" },
];

export default function App() {
  const [tab, setTab] = useState("home");
  const [boot, setBoot] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api("bootstrap").then(setBoot).catch((e) => setErr(String(e.message || e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (err) return (
    <div className="fullscreen center">
      <div className="empty-emoji">🔒</div>
      <p>دسترسی نامعتبر است. لطفاً از داخل ربات تلگرام باز کنید.</p>
      <small className="muted">{err}</small>
    </div>
  );
  if (!boot) return <div className="fullscreen center"><Spinner /></div>;
  if (boot.enabled === false) return (
    <div className="fullscreen center">
      <div className="empty-emoji">🛠</div>
      <p>{boot.brand?.title || "Atlas"} موقتاً در دسترس نیست.</p>
    </div>
  );

  return (
    <div className="app">
      <Header brand={boot.brand} user={boot.user} balance={boot.user?.balance} />
      <main className="body">
        {tab === "home" && <Home data={boot} go={setTab} />}
        {tab === "services" && <Services go={setTab} />}
        {tab === "buy" && <Buy />}
        {tab === "wallet" && <Wallet />}
        {tab === "referral" && <Referral />}
      </main>
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t.k} className={"tab " + (tab === t.k ? "active" : "")} onClick={() => setTab(t.k)}>
            <span className="tab-icon">{t.icon}</span>
            <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
