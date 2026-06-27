import React, { useEffect, useState, useCallback, useRef } from "react";

const tg = window.Telegram?.WebApp;
const INIT = tg?.initData || "";

async function api(path, body) {
  const r = await fetch(`/app/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": INIT },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.error) { const e = new Error(data.error || `HTTP ${r.status}`); e.data = data; throw e; }
  return data;
}

async function uploadReceipt(file, kind, id, amount) {
  const fd = new FormData();
  fd.append("photo", file);
  fd.append("kind", kind);
  fd.append("id", id || 0);
  fd.append("amount", amount || 0);
  const r = await fetch("/app/api/receipt", { method: "POST", headers: { "X-Telegram-Init-Data": INIT }, body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.error) throw new Error(d.error || "upload_failed");
  return d;
}

const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const gb = (bytes) => Number(bytes || 0) / 1073741824;
const haptic = (t = "success") => { try { tg?.HapticFeedback?.notificationOccurred?.(t); } catch (e) {} };

function remainText(s) {
  const total = (s.traffic_gb || 0) * 1073741824;
  const remaining = total > 0 ? Math.max(0, total - (s.used_bytes || 0)) : -1;
  const volTxt = remaining < 0 ? "نامحدود" : `${gb(remaining).toFixed(1)} GB`;
  let days = -1;
  if (s.expire_ts > 0) days = Math.max(0, Math.ceil((s.expire_ts - Date.now()) / 86400000));
  const dayTxt = days < 0 ? "بدون انقضا" : `${days} روز`;
  const pct = total > 0 ? Math.min(100, Math.round(((s.used_bytes || 0) / total) * 100)) : 0;
  return { volTxt, dayTxt, remaining, total, pct };
}

function copy(text) {
  try { navigator.clipboard.writeText(text); } catch (e) {
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    document.execCommand("copy"); t.remove();
  }
  haptic("success");
}

function Spinner() { return <div className="spinner" />; }

const DISCOUNT_ERR = {
  not_found: "کد نامعتبر است", inactive: "کد غیرفعال است", expired: "کد منقضی شده",
  exhausted: "ظرفیت کد پر شده", wrong_package: "برای این پکیج معتبر نیست",
  min_amount: "حداقل مبلغ رعایت نشده", user_limit: "قبلاً استفاده کرده‌اید",
  zero_discount: "تخفیفی ندارد", not_eligible: "این کد مخصوص شما نیست",
};

/* ── Reusable: card-to-card payment + in-app receipt upload ── */
function PayCard({ title, payment, kind, id, amount, onDone }) {
  const [stage, setStage] = useState("pay"); // pay | sending | done
  const fileRef = useRef(null);
  const pick = () => fileRef.current?.click();
  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setStage("sending");
    try { await uploadReceipt(f, kind, id, amount); haptic("success"); setStage("done"); }
    catch (err) { haptic("error"); tg?.showAlert?.("ارسال رسید ناموفق بود. دوباره تلاش کنید."); setStage("pay"); }
  };
  if (stage === "done") return (
    <div className="card pay done">
      <div className="done-emoji">✅</div>
      <b>رسید شما ارسال شد</b>
      <p className="muted">پس از تأیید ادمین (معمولاً تا ۳۰ دقیقه) سرویس/شارژ شما فعال می‌شود.</p>
      <button className="btn-primary" onClick={onDone}>باشه</button>
    </div>
  );
  return (
    <div className="card pay">
      {title && <div className="pay-title">{title}</div>}
      <div className="pay-amount">{fmt(payment.amount ?? amount)} <small>تومان</small></div>
      <p className="muted tiny">لطفاً دقیقاً همین مبلغ را واریز کنید تا سریع شناسایی شود.</p>
      <div className="pay-row card-num" onClick={() => copy(payment.card)}>
        <span>شماره کارت (لمس=کپی)</span><b dir="ltr">{payment.card}</b>
      </div>
      <div className="pay-row"><span>به نام</span><b>{payment.holder || "-"}</b></div>
      <div className="pay-row"><span>بانک</span><b>{payment.bank || "-"}</b></div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />
      <button className="btn-primary" disabled={stage === "sending"} onClick={pick}>
        {stage === "sending" ? "در حال ارسال…" : "📎 آپلود رسید پرداخت"}
      </button>
      <button className="btn-ghost" onClick={onDone}>بعداً</button>
    </div>
  );
}

function Header({ brand, user }) {
  return (
    <div className="hero">
      <div className="hero-top">
        <div className="brand"><span className="brand-logo">{brand?.logo || "🌐"}</span><span className="brand-name">{brand?.title || "Atlas"}</span></div>
        <div className="hello">سلام {user?.name || ""} 👋</div>
      </div>
      <div className="wallet-pill">
        <span>موجودی کیف پول</span>
        <b>{fmt(user?.balance)} <small>تومان</small></b>
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
        <div className="mini-stat"><div className="mini-val">{data.stats?.active_services ?? 0}</div><div className="mini-lbl">سرویس فعال</div></div>
        <div className="mini-stat"><div className="mini-val">{fmt(data.user?.balance)}</div><div className="mini-lbl">موجودی (تومان)</div></div>
      </div>
      <div className="tiles">
        {tiles.map((t) => (
          <button key={t.k} className="tile" onClick={() => { haptic(); go(t.k); }}>
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
  const [renew, setRenew] = useState(null);   // {order_id, payment}
  const [editing, setEditing] = useState(null); // service id
  const [busy, setBusy] = useState(0);
  const reload = () => api("services").then((d) => setList(d.services || [])).catch(() => setList([]));
  useEffect(() => { reload(); }, []);

  const doRename = async (s) => {
    const name = (document.getElementById(`rn-${s.id}`)?.value || "").trim();
    setBusy(s.id);
    try { await api("services/rename", { profile_id: s.id, name }); haptic(); setEditing(null); reload(); }
    catch (e) { tg?.showAlert?.("تغییر نام ناموفق بود"); } finally { setBusy(0); }
  };
  const doRenew = async (s) => {
    setBusy(s.id);
    try { const d = await api("services/renew", { profile_id: s.id }); setRenew({ ...d, name: s.name }); }
    catch (e) { tg?.showAlert?.(e.message === "no_matching_package" ? "پکیج متناظر برای تمدید پیدا نشد" : "خطا در تمدید"); }
    finally { setBusy(0); }
  };

  if (renew) return (
    <div className="screen">
      <h2 className="screen-title">تمدید سرویس</h2>
      <PayCard title={renew.name} payment={renew.payment} kind="order" id={renew.order_id} onDone={() => { setRenew(null); reload(); }} />
    </div>
  );
  if (list === null) return <div className="screen center"><Spinner /></div>;
  if (!list.length) return (
    <div className="screen center empty">
      <div className="empty-emoji">📭</div><p>هنوز سرویسی نداری</p>
      <button className="btn-primary" onClick={() => go("buy")}>🛒 خرید سرویس</button>
    </div>
  );
  return (
    <div className="screen">
      <h2 className="screen-title">سرویس‌های من</h2>
      {list.map((s) => {
        const r = remainText(s);
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
            {r.total > 0 && <div className="bar"><div className="bar-fill" style={{ width: r.pct + "%", background: r.pct > 85 ? "#fb7185" : "#34d399" }} /></div>}
            {editing === s.id ? (
              <div className="rename-row">
                <input id={`rn-${s.id}`} className="inp" defaultValue={s.name || ""} placeholder="نام دلخواه" maxLength={40} />
                <button className="btn-primary sm" disabled={busy === s.id} onClick={() => doRename(s)}>ذخیره</button>
                <button className="btn-ghost sm" onClick={() => setEditing(null)}>لغو</button>
              </div>
            ) : (
              <div className="svc-actions">
                <button className="btn-soft sm" onClick={() => copy(s.sub_url)}>📋 کپی لینک</button>
                <button className="btn-soft sm" onClick={() => setEditing(s.id)}>✏️ نام</button>
                <button className="btn-primary sm" disabled={busy === s.id} onClick={() => doRenew(s)}>♻️ تمدید</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Buy() {
  const [pkgs, setPkgs] = useState(null);
  const [sel, setSel] = useState(null);   // selected package
  const [code, setCode] = useState("");
  const [codeErr, setCodeErr] = useState("");
  const [order, setOrder] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("packages").then((d) => setPkgs(d.packages || [])).catch(() => setPkgs([])); }, []);

  const confirm = async () => {
    setBusy(true); setCodeErr("");
    try { const d = await api("buy", { package_id: sel.id, discount_code: code }); setOrder(d); haptic(); }
    catch (e) {
      if (e.data?.code_error) { setCodeErr(DISCOUNT_ERR[e.data.error] || "کد نامعتبر است"); }
      else tg?.showAlert?.("خطا در ثبت سفارش");
    } finally { setBusy(false); }
  };

  if (order) return (
    <div className="screen">
      <h2 className="screen-title">پرداخت سفارش #{order.order_id}</h2>
      <PayCard payment={order.payment} kind="order" id={order.order_id} onDone={() => { setOrder(null); setSel(null); setCode(""); }} />
    </div>
  );
  if (sel) return (
    <div className="screen">
      <h2 className="screen-title">تأیید سفارش</h2>
      <div className="card confirm">
        <div className="confirm-name">{sel.name}</div>
        <div className="confirm-spec">{sel.traffic_gb} GB · {sel.duration_days} روز</div>
        <div className="confirm-price">{fmt(sel.price)} <small>تومان</small></div>
        <div className="code-row">
          <input className="inp" value={code} onChange={(e) => { setCode(e.target.value); setCodeErr(""); }} placeholder="کد تخفیف (اختیاری)" dir="ltr" />
        </div>
        {codeErr && <div className="code-err">❌ {codeErr}</div>}
        <button className="btn-primary" disabled={busy} onClick={confirm}>{busy ? "…" : "ادامه به پرداخت"}</button>
        <button className="btn-ghost" onClick={() => { setSel(null); setCode(""); setCodeErr(""); }}>برگشت</button>
      </div>
    </div>
  );
  if (pkgs === null) return <div className="screen center"><Spinner /></div>;
  return (
    <div className="screen">
      <h2 className="screen-title">خرید سرویس</h2>
      <div className="pkg-grid">
        {pkgs.map((p) => (
          <button className="card pkg" key={p.id} onClick={() => { haptic(); setSel(p); }}>
            <div className="pkg-name">{p.name}</div>
            <div className="pkg-spec">{p.traffic_gb} GB · {p.duration_days} روز</div>
            <div className="pkg-price">{fmt(p.price)} <small>تومان</small></div>
            <span className="pkg-cta">انتخاب</span>
          </button>
        ))}
        {!pkgs.length && <p className="muted">فعلاً پکیجی موجود نیست.</p>}
      </div>
    </div>
  );
}

function Wallet() {
  const [w, setW] = useState(null);
  const [amount, setAmount] = useState("");
  const [topup, setTopup] = useState(null);  // {amount, card...}
  const [busy, setBusy] = useState(false);
  const reload = () => api("wallet").then(setW).catch(() => setW({ balance: 0, transactions: [] }));
  useEffect(() => { reload(); }, []);

  const start = async () => {
    const a = parseInt(String(amount).replace(/[^\d]/g, ""), 10);
    if (!a || a < 10000) { tg?.showAlert?.("حداقل مبلغ ۱۰٬۰۰۰ تومان است"); return; }
    setBusy(true);
    try { const d = await api("wallet/topup", { amount: a }); setTopup(d); haptic(); }
    catch (e) { tg?.showAlert?.("خطا"); } finally { setBusy(false); }
  };
  if (!w) return <div className="screen center"><Spinner /></div>;
  if (topup) return (
    <div className="screen">
      <h2 className="screen-title">شارژ کیف پول</h2>
      <PayCard payment={topup} kind="topup" amount={topup.amount} onDone={() => { setTopup(null); setAmount(""); reload(); }} />
    </div>
  );
  const presets = [50000, 100000, 200000, 500000];
  return (
    <div className="screen">
      <h2 className="screen-title">کیف پول</h2>
      <div className="card balance-card">
        <div className="balance-lbl">موجودی</div>
        <div className="balance-val">{fmt(w.balance)} <small>تومان</small></div>
      </div>
      <div className="card">
        <div className="list-title">شارژ کیف پول</div>
        <div className="preset-row">
          {presets.map((p) => <button key={p} className={"chip-amt " + (String(p) === amount ? "on" : "")} onClick={() => setAmount(String(p))}>{fmt(p)}</button>)}
        </div>
        <input className="inp" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="مبلغ دلخواه (تومان)" inputMode="numeric" dir="ltr" />
        <button className="btn-primary" disabled={busy} onClick={start}>{busy ? "…" : "💳 شارژ"}</button>
      </div>
      <div className="card">
        <div className="list-title">تراکنش‌های اخیر</div>
        {(w.transactions || []).slice(0, 10).map((t, i) => (
          <div className="tx" key={i}><span>{t.note || t.kind}</span><b className={t.amount >= 0 ? "pos" : "neg"}>{t.amount >= 0 ? "+" : ""}{fmt(t.amount)}</b></div>
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
    const u = `https://t.me/share/url?url=${encodeURIComponent(d.link)}&text=${encodeURIComponent(d.caption_no_link || "")}`;
    tg?.openTelegramLink?.(u) || window.open(u);
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
            <div className="tier" key={i}><span>{t.reached ? "✅" : `⏳ ${d.converted}/${t.referrals_needed}`}</span><span>{t.referrals_needed} دعوت → {t.reward}</span></div>
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
  const load = useCallback(() => { api("bootstrap").then(setBoot).catch((e) => setErr(String(e.message || e))); }, []);
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
    <div className="fullscreen center"><div className="empty-emoji">🛠</div><p>{boot.brand?.title || "Atlas"} موقتاً در دسترس نیست.</p></div>
  );

  return (
    <div className="app">
      <Header brand={boot.brand} user={boot.user} />
      <main className="body">
        {tab === "home" && <Home data={boot} go={setTab} />}
        {tab === "services" && <Services go={setTab} />}
        {tab === "buy" && <Buy />}
        {tab === "wallet" && <Wallet />}
        {tab === "referral" && <Referral />}
      </main>
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t.k} className={"tab " + (tab === t.k ? "active" : "")} onClick={() => { haptic("selection"); setTab(t.k); }}>
            <span className="tab-icon">{t.icon}</span><span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
