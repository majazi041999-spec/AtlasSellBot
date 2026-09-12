import React, { useEffect, useState, useCallback, useRef } from "react";
import Icon from "./Icon";
import {
  MONTHS, WEEKDAYS, monthDays, firstWeekdayOfMonth, addMonths,
  format as jFormat, formatLong as jLong, parse as jParse, today as jToday,
} from "./jalali";

import { initData, getTelegram, closeOrReload } from "./telegram.js";

async function api(path, body) {
  const r = await fetch(`/app/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData() },
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
  const r = await fetch("/app/api/receipt", { method: "POST", headers: { "X-Telegram-Init-Data": initData() }, body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.error) throw new Error(d.error || "upload_failed");
  return d;
}

const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const gb = (bytes) => Number(bytes || 0) / 1073741824;
const haptic = (t = "success") => { try { getTelegram()?.HapticFeedback?.notificationOccurred?.(t); } catch (e) {} };

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

/* ── service sort & filter (client-side; the whole list is already loaded) ── */
const SVC_SORTS = [
  { k: "newest", label: "🕒 جدیدترین" },
  { k: "oldest", label: "🕒 قدیمی‌ترین" },
  { k: "name_az", label: "🔤 نام (الف → ی)" },
  { k: "name_za", label: "🔤 نام (ی → الف)" },
  { k: "expiry_soon", label: "⏳ نزدیک‌ترین انقضا" },
  { k: "expiry_late", label: "⏳ دورترین انقضا" },
  { k: "usage_desc", label: "📊 بیشترین مصرف" },
  { k: "traffic_desc", label: "💾 بیشترین حجم" },
];
const SVC_FILTERS = [
  { k: "all", label: "همه" },
  { k: "active", label: "فعال" },
  { k: "expiring", label: "رو به انقضا" },
  { k: "near_limit", label: "حجم کم" },
  { k: "off", label: "منقضی/غیرفعال" },
];

const svcName = (s) => String(s.name || s.email || "").trim();
// Persian alphabetical order — a plain `<` puts پ چ ژ ک گ ی after every other letter.
const byName = (a, b) => svcName(a).localeCompare(svcName(b), "fa");
const svcDays = (s) => (s.expire_ts > 0 ? (s.expire_ts - Date.now()) / 86400000 : null);
const svcLive = (s) => !!s.is_active && !(s.expire_ts > 0 && s.expire_ts <= Date.now());

function matchFilter(s, k) {
  if (k === "active") return svcLive(s);
  if (k === "off") return !svcLive(s);
  if (k === "expiring") return svcLive(s) && svcDays(s) !== null && svcDays(s) <= 3;
  if (k === "near_limit") { const r = remainText(s); return r.total > 0 && r.pct >= 85; }
  return true;
}

function sortServices(rows, k) {
  const INF = Infinity;
  // Services with no expiry sort last under "soonest", first under "latest".
  if (k === "name_az") return [...rows].sort(byName);
  if (k === "name_za") return [...rows].sort((a, b) => byName(b, a));
  const keys = {
    newest: [(s) => s.id, true],
    oldest: [(s) => s.id, false],
    expiry_soon: [(s) => (svcDays(s) === null ? INF : svcDays(s)), false],
    expiry_late: [(s) => (svcDays(s) === null ? INF : svcDays(s)), true],
    usage_desc: [(s) => remainText(s).pct, true],
    traffic_desc: [(s) => Number(s.traffic_gb || 0), true],
  };
  const [key, desc] = keys[k] || keys.newest;
  return [...rows].sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka < kb) return desc ? 1 : -1;
    if (ka > kb) return desc ? -1 : 1;
    return (b.id || 0) - (a.id || 0);   // stable tiebreak
  });
}

// A toast, addressed globally rather than through React state.
//
// Copying happens from a dozen places — a card number, a subscription link, a
// UUID, a per-server config — and threading a setter down to each of them would
// mean touching every component that ever wants to say something. A tiny event
// bus keeps `copy()` a plain function that anything can call.
let __toast = null;
export function setToastHandler(fn) { __toast = fn; }
export function toast(msg, kind = "ok") { if (__toast) __toast(msg, kind); }

function copy(text, label = "کپی شد") {
  let ok = true;
  try {
    navigator.clipboard.writeText(text);
  } catch (e) {
    try {
      const t = document.createElement("textarea");
      t.value = text; document.body.appendChild(t); t.select();
      document.execCommand("copy"); t.remove();
    } catch (e2) { ok = false; }
  }
  haptic(ok ? "success" : "error");
  // Say something either way. A copy that silently failed and a copy that
  // silently worked look identical, and the customer pastes nothing.
  toast(ok ? `✅ ${label}` : "کپی نشد — دستی انتخاب کن", ok ? "ok" : "err");
}

function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    setToastHandler((msg, kind) => {
      const id = Date.now() + Math.random();
      setItems((v) => [...v, { id, msg, kind }]);
      // Long enough to read a short line, short enough not to sit over the UI.
      setTimeout(() => setItems((v) => v.filter((t) => t.id !== id)), 2200);
    });
    return () => setToastHandler(null);
  }, []);
  return (
    <div className="toast-wrap" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind === "err" ? "toast-err" : ""}`}>{t.msg}</div>
      ))}
    </div>
  );
}

function Spinner() { return <div className="spinner" role="status" aria-label="در حال بارگذاری" />; }

function PlanSpec({ plan, className = "pkg-spec" }) {
  return <div className={className}>
    <bdi>{plan.traffic_gb > 0 ? `${plan.traffic_gb} GB` : "نامحدود"}</bdi>
    <span aria-hidden="true">·</span>
    <span>{plan.duration_days > 0 ? `${plan.duration_days} روز` : "نامحدود"}</span>
  </div>;
}

const DISCOUNT_ERR = {
  not_found: "کد نامعتبر است", inactive: "کد غیرفعال است", expired: "کد منقضی شده",
  exhausted: "ظرفیت کد پر شده", wrong_package: "برای این پکیج معتبر نیست",
  min_amount: "حداقل مبلغ رعایت نشده", user_limit: "قبلاً استفاده کرده‌اید",
  zero_discount: "تخفیفی ندارد", not_eligible: "این کد مخصوص شما نیست",
};

/* ── Reusable: card-to-card payment + in-app receipt upload + wallet pay ── */
function PayCard({ title, payment, kind, id, amount, onDone, walletBalance, onWalletPaid }) {
  const [stage, setStage] = useState("pay"); // pay | sending | done
  const [doneKind, setDoneKind] = useState("receipt"); // receipt | wallet
  const fileRef = useRef(null);
  const pick = () => fileRef.current?.click();
  const payAmount = payment.amount ?? amount ?? 0;
  // Wallet payment is only offered for real orders (not wallet top-ups).
  const canWallet = kind === "order" && id && walletBalance != null;
  const enoughBalance = (walletBalance || 0) >= payAmount;

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setStage("sending");
    try { await uploadReceipt(f, kind, id, amount); haptic("success"); setDoneKind("receipt"); setStage("done"); }
    catch (err) { haptic("error"); getTelegram()?.showAlert?.("ارسال رسید ناموفق بود. دوباره تلاش کنید."); setStage("pay"); }
  };
  const payFromWallet = async () => {
    if (!enoughBalance) { getTelegram()?.showAlert?.("موجودی کیف پول کافی نیست. ابتدا شارژ کنید."); return; }
    setStage("sending");
    try {
      const d = await api("wallet/pay", { order_id: id });
      haptic("success");
      onWalletPaid?.(d.balance);
      setDoneKind("wallet"); setStage("done");
    } catch (err) {
      haptic("error");
      getTelegram()?.showAlert?.(err.data?.error === "insufficient_balance" ? "موجودی کافی نیست" : "پرداخت از کیف پول ناموفق بود.");
      setStage("pay");
    }
  };

  if (stage === "done") return (
    <div className="card pay done">
      <div className="done-emoji"><Icon name="check" /></div>
      {doneKind === "wallet" ? (
        <>
          <b>پرداخت از کیف پول انجام شد</b>
          <p className="muted">سرویس شما فعال/تمدید شد. از بخش «سرویس‌های من» لینک را دریافت کنید.</p>
        </>
      ) : (
        <>
          <b>رسید شما ارسال شد</b>
          <p className="muted">پس از تأیید ادمین (معمولاً تا ۳۰ دقیقه) سرویس/شارژ شما فعال می‌شود.</p>
        </>
      )}
      <button className="btn-primary" onClick={onDone}>باشه</button>
    </div>
  );
  return (
    <div className="card pay">
      {title && <div className="pay-title">{title}</div>}
      <div className="pay-amount">{fmt(payAmount)} <small>تومان</small></div>
      {canWallet && (
        <div className="wallet-pay-box">
          <button className="btn-primary" disabled={stage === "sending" || !enoughBalance} onClick={payFromWallet}>
            {stage === "sending" ? "در حال پرداخت…" : <><Icon name="wallet" />پرداخت از کیف پول (موجودی: {fmt(walletBalance)})</>}
          </button>
          {!enoughBalance && <p className="muted tiny">موجودی کیف پول برای این خرید کافی نیست — می‌توانید کارت‌به‌کارت پرداخت کنید.</p>}
          <div className="pay-or">یا پرداخت کارت‌به‌کارت</div>
        </div>
      )}
      <p className="muted tiny">لطفاً دقیقاً همین مبلغ را واریز کنید تا سریع شناسایی شود.</p>
      <div className="pay-row card-num" onClick={() => copy(payment.card, "شماره کارت کپی شد")}>
        <span>شماره کارت (لمس=کپی)</span><b dir="ltr">{payment.card}</b>
      </div>
      <div className="pay-row"><span>به نام</span><b>{payment.holder || "-"}</b></div>
      <div className="pay-row"><span>بانک</span><b>{payment.bank || "-"}</b></div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />
      <button className="btn-primary" disabled={stage === "sending"} onClick={pick}>
        {stage === "sending" ? "در حال ارسال…" : <><Icon name="upload" />آپلود رسید پرداخت</>}
      </button>
      <button className="btn-ghost" onClick={onDone}>بعداً</button>
    </div>
  );
}

function Header({ brand, user, isRep, go, compact }) {
  return (
    <header className={"hero" + (isRep ? " hero-rep" : "") + (compact ? " hero-compact" : "")}>
      <div className="hero-top">
        <div className="brand"><span className="brand-logo">{brand?.logo || <Icon name="globe" />}</span><div><span className="brand-name">{brand?.title || "Atlas"}</span><span className="brand-caption">دنیای تو، بدون مرز</span></div></div>
        <div className="account-mark">{isRep ? <span className="rep-badge">پنل نماینده</span> : <><span className="account-dot" />حساب کاربری</>}</div>
      </div>
      <div className="hero-greeting"><span className="hello">سلام {user?.name || "دوست عزیز"}</span><h1>{isRep ? "کسب‌وکارت، در یک نگاه" : "به دنیای اطلس خوش اومدی"}</h1></div>
      <div className="wallet-pill">
        <div className="wallet-summary"><span className="wallet-label"><Icon name="wallet" />موجودی کیف پول</span><b><span dir="ltr">{fmt(user?.balance)}</span> <small>تومان</small></b></div>
        <button className="wallet-add" onClick={() => { haptic(); go("wallet"); }} aria-label="شارژ کیف پول"><Icon name="plus" /><span>شارژ</span></button>
      </div>
    </header>
  );
}

function Home({ data, go }) {
  const isRep = data.is_rep;
  const f = data.rep?.financials || {};
  const tiles = isRep ? [
    { k: "buy", label: "ساخت سرویس" },
    { k: "services", label: "مشتریان من" },
    { k: "rep", label: "گزارش فروش" },
    { k: "wallet", label: "کیف پول" },
  ] : [
    { k: "buy", label: "خرید سرویس" },
    { k: "services", label: "سرویس‌های من" },
    { k: "wallet", label: "کیف پول" },
    { k: "referral", label: "دعوت دوستان" },
  ];
  return (
    <div className="screen home-screen">
      {isRep && (
        <div className="rep-hero">
          <div className="rep-hero-crown"><Icon name="chart" /></div>
          <div className="rep-hero-title">نمای کلی کسب‌وکار</div>
          <div className="rep-hero-sub">به پنل نمایندگی <b>{data.rep?.brand_name || data.brand?.title}</b> خوش اومدی</div>
          <div className="rep-hero-stats">
            <div><b>{f.active_services || 0}</b><span>سرویس فعال</span></div>
            <div><b>{fmt(f.total_spent)}</b><span>کل فروش (ت)</span></div>
            <div><b>{fmt(f.month_spent)}</b><span>این ماه (ت)</span></div>
          </div>
        </div>
      )}
      {!isRep && (
        <div className="stat-row">
          <div className="mini-stat"><span className="stat-icon mint"><Icon name="services" /></span><div><div className="mini-val">{data.stats?.active_services ?? 0}<span className="status-dot" /></div><div className="mini-lbl">سرویس فعال</div></div></div>
          <div className="mini-stat"><span className="stat-icon blue"><Icon name="wallet" /></span><div><div className="mini-val">{fmt(data.user?.balance)}</div><div className="mini-lbl">اعتبار شما · تومان</div></div></div>
        </div>
      )}
      <button className="discover-card" onClick={() => { haptic(); go("buy"); }}>
        <div className="discover-copy"><span className="eyebrow">{isRep ? "یک قدم تا سرویس جدید" : "وقت یک اتصال تازه‌ست"}</span><h2>{isRep ? "سرویس بعدی مشتری‌ات" : "دنیای بزرگ‌تر،\nفقط با یک اتصال."}</h2><span className="discover-cta">مشاهده سرویس‌ها <Icon name="arrow" /></span></div>
        <div className="orbit-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="planet"><Icon name="globe" /></div><span className="satellite satellite-one" /><span className="satellite satellite-two" /><span className="orbit-spark">+</span></div>
      </button>
      <div className="section-heading"><h2>دسترسی سریع</h2><span>همه‌چیز، همین‌جاست</span></div>
      <div className="tiles">
        {tiles.map((t) => (
          <button key={t.k} className={`tile tile-${t.k}`} onClick={() => { haptic(); go(t.k); }}>
            <span className="tile-icon"><Icon name={t.k} /></span>
            <span className="tile-label">{t.label}</span><span className="tile-desc">{{ buy: "انتخاب پلن دلخواه", services: isRep ? "مدیریت سرویس مشتریان" : "مدیریت و تمدید", wallet: "موجودی و تراکنش‌ها", referral: "با هم، با پاداش", rep: "آمار و جزئیات خرید" }[t.k]}</span><Icon name="arrow" className="tile-arrow" />
          </button>
        ))}
      </div>
      {data.support && (
        <a className="support-card" href={`https://t.me/${data.support}`} target="_blank" rel="noreferrer">
          <span className="support-icon"><Icon name="support" /></span><span className="support-copy"><b>کنارت هستیم</b><small>گفت‌وگو با پشتیبانی{isRep ? " نمایندگان" : ""}</small></span><Icon name="arrow" className="chev" />
        </a>
      )}
    </div>
  );
}

function Services({ go, balance, onBalance, isRep }) {
  // "how many devices are on my service right now". Kept next to the service
  // card rather than on its own screen: the question is always about ONE
  // service, and it is asked in the same breath as "why is it slow".
  const [conns, setConns] = useState({});      // profile_id -> payload | "loading"
  const loadConns = async (id) => {
    setConns((p) => ({ ...p, [id]: "loading" }));
    try {
      const r = await api("services/connections", { profile_id: id });
      setConns((p) => ({ ...p, [id]: r }));
    } catch (e) {
      setConns((p) => ({ ...p, [id]: { ok: false } }));
    }
  };
  const [list, setList] = useState(null);
  const [renew, setRenew] = useState(null);   // {order_id, payment, name}
  const [planFor, setPlanFor] = useState(null); // service awaiting plan choice
  const [pkgs, setPkgs] = useState(null);       // packages for renewal
  const [editing, setEditing] = useState(null); // service id
  const [expanded, setExpanded] = useState(null); // service id whose servers are shown
  // Delete and relink both destroy something the customer cannot get back — a
  // service, or every device's current connection. Neither happens on one tap.
  const [confirmAct, setConfirmAct] = useState(null);  // {kind, s}
  const [q, setQ] = useState("");               // search query
  const [sort, setSort] = useState("newest");   // see SVC_SORTS
  const [filt, setFilt] = useState("all");      // see SVC_FILTERS
  const [busy, setBusy] = useState(0);
  const reload = () => api("services").then((d) => setList(d.services || [])).catch(() => setList([]));
  useEffect(() => { reload(); }, []);

  const doRename = async (s) => {
    const name = (document.getElementById(`rn-${s.id}`)?.value || "").trim();
    setBusy(s.id);
    try { await api("services/rename", { profile_id: s.id, name }); haptic(); setEditing(null); reload(); }
    catch (e) { getTelegram()?.showAlert?.("تغییر نام ناموفق بود"); } finally { setBusy(0); }
  };
  const runConfirmed = async () => {
    if (!confirmAct) return;
    const { kind, s } = confirmAct;
    setBusy(s.id);
    try {
      if (kind === "delete") {
        await api("services/delete", { profile_id: s.id, confirm: true });
        toast("🗑️ سرویس حذف شد");
      } else {
        await api("services/relink", { profile_id: s.id, confirm: true });
        toast("🔄 لینک تازه ساخته شد — لینک قبلی از کار افتاد");
      }
      haptic("success");
      setConfirmAct(null);
      reload();
    } catch (e) {
      haptic("error");
      toast(kind === "delete" ? "حذف انجام نشد" : "تغییر لینک انجام نشد", "err");
    } finally { setBusy(0); }
  };

  // Renewal is plan-based: open a package picker for this service.
  const openRenew = async (s) => {
    setPlanFor(s); haptic();
    if (pkgs === null) {
      try { const d = await api("packages"); setPkgs(d.packages || []); }
      catch (e) { setPkgs([]); }
    }
  };
  const pickPlan = async (p) => {
    setBusy(p.id);
    try { const d = await api("services/renew", { profile_id: planFor.id, package_id: p.id }); setRenew({ ...d, name: planFor.name }); setPlanFor(null); }
    catch (e) { getTelegram()?.showAlert?.("خطا در تمدید"); }
    finally { setBusy(0); }
  };

  if (renew) return (
    <div className="screen">
      <h2 className="screen-title">تمدید سرویس</h2>
      <PayCard title={renew.name} payment={renew.payment} kind="order" id={renew.order_id}
               walletBalance={balance} onWalletPaid={onBalance}
               onDone={() => { setRenew(null); reload(); }} />
    </div>
  );
  if (planFor) return (
    <div className="screen">
      <h2 className="screen-title">تمدید «{planFor.name || "سرویس"}»</h2>
      <p className="muted" style={{ margin: "0 0 10px" }}>با کدام پلن تمدید می‌کنید؟</p>
      {pkgs === null ? <div className="center"><Spinner /></div> : (
        <div className="pkg-grid">
          {pkgs.map((p) => (
            <button className="card pkg" key={p.id} disabled={busy === p.id} onClick={() => pickPlan(p)}>
              <div className="pkg-name">{p.name}</div>
              <PlanSpec plan={p} />
              <div className="pkg-price">{fmt(p.price)} <small>تومان</small></div>
              <span className="pkg-cta">{busy === p.id ? "…" : "تمدید"}</span>
            </button>
          ))}
          {!pkgs.length && <p className="muted">فعلاً پلنی برای تمدید موجود نیست.</p>}
        </div>
      )}
      <button className="btn-ghost" onClick={() => setPlanFor(null)}>برگشت</button>
    </div>
  );
  if (list === null) return <div className="screen center"><Spinner /></div>;
  if (!list.length) return (
    <div className="screen center empty">
      <div className="empty-emoji"><Icon name="services" /></div><p>هنوز سرویسی نداری</p>
      <button className="btn-primary" onClick={() => go("buy")}><Icon name="buy" />خرید سرویس</button>
    </div>
  );
  const needle = q.trim().toLowerCase();
  const searched = !needle ? list : list.filter((s) => {
    const hay = [s.name, s.email, s.sub_url, ...(s.nodes || []).flatMap((n) => [n.label, n.uuid, n.link])]
      .filter(Boolean).join(" ").toLowerCase();
    return hay.includes(needle);
  });
  const filtered = sortServices(searched.filter((s) => matchFilter(s, filt)), sort);
  return (
    <div className="screen">
      <h2 className="screen-title">{isRep ? "مشتریان من" : "سرویس‌های من"}</h2>
      <div className="search-box">
        <span className="search-ico"><Icon name="search" /></span>
        <input aria-label="جستجوی سرویس‌ها" className="inp search-inp" value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو: نام، UUID، لینک کامل یا سرور…" />
        {q && <button aria-label="پاک کردن جستجو" className="search-clear" onClick={() => setQ("")}>✕</button>}
      </div>
      <div className="sortbar">
        <select aria-label="مرتب‌سازی سرویس‌ها" className="inp sort-sel" value={sort} onChange={(e) => { haptic("selection"); setSort(e.target.value); }}>
          {SVC_SORTS.map((o) => <option key={o.k} value={o.k}>{o.label}</option>)}
        </select>
      </div>
      <div className="filter-chips">
        {SVC_FILTERS.map((o) => {
          const n = searched.filter((s) => matchFilter(s, o.k)).length;
          return (
            <button key={o.k} className={"fchip" + (filt === o.k ? " on" : "")}
                    onClick={() => { haptic("selection"); setFilt(o.k); }}>
              {o.label}<em>{n}</em>
            </button>
          );
        })}
      </div>
      <div className="muted tiny" style={{ margin: "0 0 8px" }}>{filtered.length} از {list.length} سرویس</div>
      {!filtered.length && (
        <div className="card center" style={{ padding: 24 }}>
          <p className="muted">موردی با این جستجو و فیلتر پیدا نشد.</p>
          <button className="btn-ghost sm" onClick={() => { setQ(""); setFilt("all"); }}>پاک کردن فیلترها</button>
        </div>
      )}
      {filtered.map((s) => {
        const r = remainText(s);
        return (
          <div className="card svc" key={s.id}>
            <div className="svc-head">
              <b className="service-name"><span className="service-icon"><Icon name="services" /></span>{s.name || "سرویس"}</b>
              <span className={"badge " + (s.is_active ? "ok" : "off")}>{s.is_active ? "فعال" : "غیرفعال"}</span>
            </div>
            <div className="svc-meta">
              <span><Icon name="chart" /> <bdi>{r.volTxt}</bdi></span><span><Icon name="clock" /> {r.dayTxt}</span>
              <span><Icon name="services" /> {(s.nodes || []).filter((n) => n.is_active).length} سرور</span>
            </div>
            {r.total > 0 && <div className="bar"><div className="bar-fill" style={{ width: r.pct + "%", background: r.pct > 85 ? "#fb7185" : "#34d399" }} /></div>}
            {editing === s.id ? (
              <div className="rename-row">
                <input id={`rn-${s.id}`} aria-label="نام سرویس" className="inp" defaultValue={s.name || ""} placeholder="نام دلخواه" maxLength={40} />
                <button className="btn-primary sm" disabled={busy === s.id} onClick={() => doRename(s)}>ذخیره</button>
                <button className="btn-ghost sm" onClick={() => setEditing(null)}>لغو</button>
              </div>
            ) : (
              <div className="svc-actions">
                <button className="btn-soft sm" onClick={() => copy(s.sub_url, "لینک اشتراک کپی شد")}><Icon name="copy" />کپی لینک</button>
                <button className="btn-soft sm" onClick={() => setEditing(s.id)}><Icon name="edit" />نام</button>
                <button className="btn-soft sm" onClick={() => { haptic("selection"); setExpanded(expanded === s.id ? null : s.id); }}><Icon name="services" />سرورها</button>
                <button className="btn-soft sm" onClick={() => { haptic("selection"); loadConns(s.id); }}>
                  <Icon name="devices" />دستگاه‌های متصل
                </button>
                <button className="btn-primary sm" disabled={busy === s.id} onClick={() => openRenew(s)}><Icon name="refresh" />تمدید</button>
                <button className="btn-soft sm" disabled={busy === s.id} onClick={() => setConfirmAct({ kind: "relink", s })}>
                  <Icon name="refresh" />تغییر لینک
                </button>
                <button className="btn-danger sm" disabled={busy === s.id} onClick={() => setConfirmAct({ kind: "delete", s })}>
                  <Icon name="trash" />حذف
                </button>
              </div>
            )}
            {conns[s.id] && (
              <div className="node-list">
                {conns[s.id] === "loading" && <p className="muted tiny" style={{ margin: 0 }}>در حال بررسی…</p>}
                {conns[s.id] !== "loading" && !conns[s.id].ok && (
                  <p className="muted tiny" style={{ margin: 0 }}>الان نمی‌شود وضعیت اتصال را خواند.</p>
                )}
                {conns[s.id] !== "loading" && conns[s.id].ok && (
                  <>
                    <div className="node-top" style={{ marginBottom: 6 }}>
                      <span className="node-dot" style={{ background: conns[s.id].limit && conns[s.id].count > conns[s.id].limit ? "#fb7185" : "#34d399" }} />
                      <span className="node-lbl">
                        {conns[s.id].count === 0
                          ? "هیچ دستگاهی الان متصل نیست"
                          : `${conns[s.id].count} مکان متصل است${conns[s.id].limit ? ` (سقف: ${conns[s.id].limit})` : ""}`}
                      </span>
                    </div>
                    {(conns[s.id].places || []).map((pl, i) => (
                      <div className="node-card" key={i}>
                        <div className="node-uuid" dir="ltr">{pl.ip}</div>
                        <div className="muted tiny">
                          {pl.server ? pl.server + " · " : ""}
                          {pl.seconds_ago < 30 ? "همین الان"
                            : pl.seconds_ago < 90 ? `${pl.seconds_ago} ثانیه پیش`
                            : `${Math.round(pl.seconds_ago / 60)} دقیقه پیش`}
                        </div>
                      </div>
                    ))}
                    {conns[s.id].floor && (
                      <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 1.9 }}>
                        🔗 {conns[s.id].gateway_addresses} آدرس از یک شبکه‌ی مشترک
                        (NAT اپراتور) می‌آمد و روی هم یک مکان شمرده شد — اپراتورهای
                        موبایل برای هر اتصال یک آی‌پی متفاوت می‌دهند. پس این عدد
                        «حداقل» است.
                      </p>
                    )}
                    {conns[s.id].partial && (
                      <p className="muted tiny" style={{ margin: "6px 0 0" }}>
                        ⚠️ فقط {conns[s.id].answered} سرور از {conns[s.id].servers} جواب داد؛ این عدد کمینه است.
                      </p>
                    )}
                    <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 1.9 }}>
                      ملاک، اتصال هم‌زمان است. با اینترنت همراه، تغییر آی‌پی اتصال جدید حساب نمی‌شود.
                    </p>
                  </>
                )}
              </div>
            )}
            {expanded === s.id && (
              <div className="node-list">
                {(s.nodes || []).filter((n) => n.is_active && n.link).map((n, i) => (
                  <div className="node-card" key={i}>
                    <div className="node-top"><span className="node-dot" /><span className="node-lbl">{n.label}</span></div>
                    {n.uuid && <div className="node-uuid" onClick={() => copy(n.uuid, "UUID کپی شد")} title="کپی UUID">UUID: <span dir="ltr">{n.uuid}</span></div>}
                    <div className="node-btns">
                      <button className="btn-soft xs" onClick={() => copy(n.link, "کانفیگ کپی شد")}><Icon name="copy" />کپی کانفیگ</button>
                      {n.uuid && <button className="btn-soft xs" onClick={() => copy(n.uuid, "UUID کپی شد")}><Icon name="copy" />کپی UUID</button>}
                    </div>
                  </div>
                ))}
                {!(s.nodes || []).some((n) => n.is_active && n.link) && <p className="muted tiny" style={{ margin: 0 }}>سرور فعالی برای این سرویس نیست.</p>}
              </div>
            )}
          </div>
        );
      })}

      {confirmAct && (
        <div className="sheet-back" onClick={() => setConfirmAct(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <div className={"sheet-icon " + (confirmAct.kind === "delete" ? "danger" : "warn")}>
              <Icon name={confirmAct.kind === "delete" ? "trash" : "refresh"} />
            </div>
            <h3 className="sheet-title">
              {confirmAct.kind === "delete" ? "حذف سرویس؟" : "تغییر لینک اشتراک؟"}
            </h3>
            <p className="sheet-body">
              {confirmAct.kind === "delete" ? (
                <>سرویس <b>{svcName(confirmAct.s) || "بدون نام"}</b> از سرورها و از حساب تو پاک می‌شود.
                   حجم و روزهای باقی‌مانده از بین می‌رود و <b>برگشتی ندارد</b>.</>
              ) : (
                <>لینک فعلی <b>بلافاصله از کار می‌افتد</b> و هر دستگاهی که با آن وصل است قطع می‌شود.
                   حجم و روزهای باقی‌مانده دقیقاً حفظ و به لینک تازه منتقل می‌شود.</>
              )}
            </p>
            <button
              className={confirmAct.kind === "delete" ? "btn-danger" : "btn-primary"}
              disabled={busy === confirmAct.s.id}
              onClick={runConfirmed}>
              {busy === confirmAct.s.id ? "…" : (confirmAct.kind === "delete" ? "بله، حذف کن" : "بله، لینک تازه بده")}
            </button>
            <button className="btn-ghost" onClick={() => setConfirmAct(null)}>منصرف شدم</button>
          </div>
        </div>
      )}
    </div>
  );
}

// A number that counts to its new value instead of jumping.
//
// Used for the price when a discount lands: watching it fall is what makes the
// discount feel real, and a total that silently changes is one people re-read
// to check they were not overcharged.
function CountUp({ to, ms = 550 }) {
  const [v, setV] = useState(to);
  const from = useRef(to);
  useEffect(() => {
    const start = performance.now(), a = from.current, b = to;
    if (a === b) return;
    let raf;
    const step = (now) => {
      const t = Math.min(1, (now - start) / ms);
      // Ease-out: fast at first, settling at the end.
      setV(Math.round(a + (b - a) * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(step);
      else from.current = b;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, ms]);
  return <>{fmt(v)}</>;
}

function Buy({ balance, onBalance }) {
  const [pkgs, setPkgs] = useState(null);
  const [sel, setSel] = useState(null);   // selected package
  const [code, setCode] = useState("");
  const [codeErr, setCodeErr] = useState("");
  const [applied, setApplied] = useState(null);   // priced result from the server
  const [checking, setChecking] = useState(false);
  const [order, setOrder] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("packages").then((d) => setPkgs(d.packages || [])).catch(() => setPkgs([])); }, []);

  // Price the code before committing to anything. The server answers with the
  // SAME function the purchase uses, so the preview and the till cannot
  // disagree — a preview that did its own arithmetic would eventually lie.
  const checkCode = async () => {
    const c = code.trim();
    if (!c) return;
    setChecking(true); setCodeErr(""); setApplied(null);
    try {
      const d = await api("discount/check", { package_id: sel.id, discount_code: c });
      if (d.code_amount > 0) {
        setApplied(d);
        haptic("success");
        toast(`🎟️ ${fmt(d.code_amount)} تومان تخفیف گرفتی`);
      } else {
        setCodeErr("این کد برای این پکیج تخفیفی ندارد");
        haptic("error");
      }
    } catch (e) {
      setCodeErr(DISCOUNT_ERR[e.data?.error] || "کد نامعتبر است");
      haptic("error");
    } finally { setChecking(false); }
  };

  const confirm = async () => {
    setBusy(true); setCodeErr("");
    try { const d = await api("buy", { package_id: sel.id, discount_code: code }); setOrder(d); haptic(); }
    catch (e) {
      if (e.data?.code_error) { setCodeErr(DISCOUNT_ERR[e.data.error] || "کد نامعتبر است"); }
      else getTelegram()?.showAlert?.("خطا در ثبت سفارش");
    } finally { setBusy(false); }
  };

  if (order) return (
    <div className="screen">
      <h2 className="screen-title">پرداخت سفارش <bdi>#{order.order_id}</bdi></h2>
      <PayCard payment={order.payment} kind="order" id={order.order_id}
               walletBalance={balance} onWalletPaid={onBalance}
               onDone={() => { setOrder(null); setSel(null); setCode(""); setApplied(null); }} />
    </div>
  );
  if (sel) return (
    <div className="screen">
      <h2 className="screen-title">تأیید سفارش</h2>
      <div className="card confirm">
        <div className="confirm-name">{sel.name}</div>
        <PlanSpec plan={sel} className="confirm-spec" />
        <div className={"confirm-price" + (applied ? " price-cut" : "")}>
          {/* Once a code lands, the old total is struck through beside the new
              one. Showing only the new number leaves the customer with no idea
              what the code was worth. */}
          {applied ? <s className="price-base">{fmt(applied.base)}</s>
                   : (sel.base > 0 && <s className="price-base">{fmt(sel.base)}</s>)}{" "}
          <CountUp to={applied ? applied.net : sel.price} /> <small>تومان</small>
        </div>
        {applied && (
          <div className="code-ok">
            🎟️ کد <b dir="ltr">{applied.code}</b> اعمال شد — <b>{fmt(applied.code_amount)}</b> تومان کمتر
          </div>
        )}
        <div className="code-row">
          <input aria-label="کد تخفیف (اختیاری)" className="inp" value={code}
            onChange={(e) => { setCode(e.target.value); setCodeErr(""); setApplied(null); }}
            placeholder="کد تخفیف (اختیاری)" dir="ltr" disabled={checking} />
          <button className="btn-soft sm" disabled={!code.trim() || checking}
            onClick={checkCode}>{checking ? "…" : (applied ? "تغییر" : "اعمال")}</button>
        </div>
        {codeErr && <div className="code-err shake">❌ {codeErr}</div>}
        <button className="btn-primary" disabled={busy} onClick={confirm}>{busy ? "…" : "ادامه به پرداخت"}</button>
        <button className="btn-ghost" onClick={() => { setSel(null); setCode(""); setCodeErr(""); setApplied(null); }}>برگشت</button>
      </div>
    </div>
  );
  if (pkgs === null) return <div className="screen center"><Spinner /></div>;
  return (
    <div className="screen">
      <h2 className="screen-title">خرید سرویس</h2>
      <p className="screen-description">پلنی که با دنیای تو هماهنگه، انتخاب کن.</p>
      <div className="pkg-grid">
        {pkgs.map((p) => (
          <button className="card pkg" key={p.id} onClick={() => { haptic(); setSel(p); }}>
            <span className="package-icon"><Icon name="buy" /></span>
            <div className="pkg-name">{p.name}</div>
            <PlanSpec plan={p} />
            <div className="pkg-price">{p.base > 0 && <s className="price-base">{fmt(p.base)}</s>} {fmt(p.price)} <small>تومان</small></div>
            <span className="pkg-cta">انتخاب سرویس <Icon name="arrow" /></span>
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
    if (!a || a < 10000) { getTelegram()?.showAlert?.("حداقل مبلغ ۱۰٬۰۰۰ تومان است"); return; }
    setBusy(true);
    try { const d = await api("wallet/topup", { amount: a }); setTopup(d); haptic(); }
    catch (e) { getTelegram()?.showAlert?.("خطا"); } finally { setBusy(false); }
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
      <p className="screen-description">اعتبار و تراکنش‌ها، شفاف و یک‌جا.</p>
      <div className="card balance-card">
        <span className="balance-icon"><Icon name="wallet" /></span>
        <div className="balance-lbl">موجودی</div>
        <div className="balance-val">{fmt(w.balance)} <small>تومان</small></div>
      </div>
      <div className="card">
        <div className="list-title">شارژ کیف پول</div>
        <div className="preset-row">
          {presets.map((p) => <button key={p} className={"chip-amt " + (String(p) === amount ? "on" : "")} onClick={() => setAmount(String(p))}>{fmt(p)}</button>)}
        </div>
        <input aria-label="مبلغ شارژ به تومان" className="inp" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="مبلغ دلخواه (تومان)" inputMode="numeric" dir="ltr" />
        <button className="btn-primary" disabled={busy} onClick={start}>{busy ? "…" : <><Icon name="plus" />شارژ کیف پول</>}</button>
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
    getTelegram()?.openTelegramLink?.(u) || window.open(u);
  };
  return (
    <div className="screen">
      <h2 className="screen-title">دعوت دوستان</h2>
      <p className="screen-description">تجربه‌ات رو به اشتراک بذار، پاداش بگیر.</p>
      <div className="card earn-card">
        <span className="reward-icon"><Icon name="referral" /></span>
        <div className="earn-val">{fmt(d.earned)} <small>تومان</small></div>
        <div className="earn-lbl">جایزهٔ دریافتی شما</div>
        <div className="earn-sub">👥 {d.invited || 0} دعوت · 🛒 {d.converted || 0} خرید</div>
      </div>
      <div className="card link-card" onClick={() => copy(d.link, "لینک دعوت کپی شد")}>
        <div className="muted">لینک اختصاصی (لمس=کپی)</div>
        <div className="link-text" dir="ltr">{d.link}</div>
      </div>
      <button className="btn-primary" onClick={share}><Icon name="upload" />ارسال برای دوستان</button>
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

/* ── Representative purchase report (date filtered) ─────────────────────────
   The server owns the preset list; this copy only keeps the picker from being
   empty on first paint, and is replaced by `presets[]` on the first response. */
const REP_PRESETS = [
  { key: "week", label: "۷ روز اخیر" },
  { key: "month", label: "۱ ماه اخیر" },
  { key: "3months", label: "۳ ماه اخیر" },
  { key: "6months", label: "۶ ماه اخیر" },
  { key: "year", label: "۱ سال اخیر" },
  { key: "all", label: "همه" },
];
const WD_SHORT = WEEKDAYS.map((d) => d[0]);
const sameDay = (a, b) => !!a && !!b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

/* Dates arrive already formatted (and sometimes as words like «شروع نشده»), so
   they're printed verbatim. <bdi> only isolates them: without it RTL bidi would
   swap the two numeric runs of "1405/06/21 15:34" around the space. */
const D = ({ v }) => <bdi>{v || "—"}</bdi>;
const repStatusCls = (s) => (s === "فعال" ? "ok" : s === "منقضی" ? "warn" : "off");

/** Compact Jalali month grid — everything comes from jalali.js. */
function MonthGrid({ value, onPick }) {
  const now = jToday();
  const [view, setView] = useState(value || now);
  const [jy, jm] = view;
  const lead = firstWeekdayOfMonth(jy, jm);
  const total = monthDays(jy, jm);
  const cells = [...Array(lead).fill(0), ...Array.from({ length: total }, (_, i) => i + 1)];
  const jump = (delta) => { haptic("selection"); setView(addMonths(view, delta)); };
  return (
    <div className="rp-cal">
      <div className="rp-cal-head">
        <button type="button" className="rp-nav" onClick={() => jump(-1)}>ماه قبل</button>
        <b>{MONTHS[jm - 1]} {jy}</b>
        <button type="button" className="rp-nav" onClick={() => jump(1)}>ماه بعد</button>
      </div>
      <div className="rp-cal-head sub">
        <button type="button" className="rp-nav" onClick={() => jump(-12)}>سال قبل</button>
        <button type="button" className="rp-nav" onClick={() => { haptic("selection"); setView(now); onPick(now); }}>امروز</button>
        <button type="button" className="rp-nav" onClick={() => jump(12)}>سال بعد</button>
      </div>
      <div className="rp-cal-grid rp-cal-wd">{WD_SHORT.map((d, i) => <span key={i}>{d}</span>)}</div>
      <div className="rp-cal-grid">
        {cells.map((d, i) => (d === 0 ? <span className="rp-day empty" key={`b${i}`} /> : (
          <button type="button" key={d}
                  className={"rp-day" + (sameDay([jy, jm, d], value) ? " on" : "") + (sameDay([jy, jm, d], now) ? " today" : "")}
                  onClick={() => { haptic("selection"); onPick([jy, jm, d]); }}>{d}</button>
        )))}
      </div>
    </div>
  );
}

const PAGE = 20;

function RepSalePrice({ row, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputId = `sale-${row.kind}-${row.order_id}-${row.profile_id}`;
  const save = async (e) => {
    e.preventDefault();
    const normalized = value.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
      .replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).replace(/[,٬\s]/g, "");
    const price = normalized === "" ? null : Number(normalized);
    if (price !== null && (!/^\d+$/.test(normalized) || !Number.isSafeInteger(price) || price > 1000000000000)) {
      setError("مبلغ را به تومان و بدون اعشار وارد کن."); return;
    }
    setBusy(true); setError("");
    try {
      await api("rep/purchases/sale-price", { kind: row.kind, order_id: row.order_id, profile_id: row.profile_id, sale_price: price });
      haptic("success"); setEditing(false); onSaved();
    } catch (e) { setError(e.data?.message || "ذخیره نشد؛ دوباره تلاش کن."); }
    finally { setBusy(false); }
  };
  return <div className="rep-sale">
    <div className="rp-fact"><span>قیمت خرید همان زمان</span><b>{row.price == null ? "نامشخص" : <>{fmt(row.price)} <small>تومان</small></>}</b></div>
    <div className="rp-fact"><span>قیمت فروش شما</span><b>{row.sale_price == null ? "ثبت نشده" : <>{fmt(row.sale_price)} <small>تومان</small></>}</b></div>
    <div className="rp-fact"><span>سود این {row.kind === "renewal" ? "تمدید" : "خرید"}</span><b className={row.profit < 0 ? "neg" : "pos"}>{row.profit == null ? "—" : <><bdi>{fmt(row.profit)}</bdi> <small>تومان</small></>}</b></div>
    {editing ? <form onSubmit={save} className="sale-form">
      <label htmlFor={inputId}>قیمت فروش شما (تومان)</label>
      <input id={inputId} className="inp" inputMode="numeric" dir="ltr" autoFocus value={value} maxLength={20} disabled={busy} onChange={e => setValue(e.target.value)} placeholder="مثلاً ۱۵۰٬۰۰۰" />
      <p className="muted tiny">خالی = حذف قیمت فروش · صفر = فروش رایگان</p>
      <div className="sale-actions"><button type="submit" className="btn-primary sm" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره قیمت فروش"}</button><button type="button" className="btn-ghost sm" disabled={busy} onClick={() => { setEditing(false); setError(""); }}>لغو</button></div>
    </form> : row.order_id > 0 && <button className="btn-soft sale-edit" onClick={() => { setValue(row.sale_price == null ? "" : String(row.sale_price)); setEditing(true); }}><Icon name="edit" />{row.sale_price == null ? "ثبت قیمت فروش" : "ویرایش قیمت فروش"}</button>}
    {error && <p className="code-err" role="alert">{error}</p>}
  </div>;
}

function RepReport() {
  const [presets, setPresets] = useState(REP_PRESETS);
  const [preset, setPreset] = useState("month");
  const [custom, setCustom] = useState(false);
  const [from, setFrom] = useState(null);      // [jy,jm,jd]
  const [to, setTo] = useState(null);
  const [pick, setPick] = useState("");        // "" | "from" | "to"
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState(null);      // {ok, text}
  const [tick, setTick] = useState(0);         // bump = refetch the same range
  const reqRef = useRef(0);

  const fromStr = custom ? jFormat(from) : "";
  const toStr = custom ? jFormat(to) : "";

  useEffect(() => { setShown(PAGE); }, [preset, custom, fromStr, toStr]);
  useEffect(() => {
    if (custom && !fromStr && !toStr) return;   // custom mode with nothing chosen
    const id = ++reqRef.current;                // last request in wins
    setLoading(true); setErr(""); setNote(null);
    api("rep/purchases", { preset, from: fromStr, to: toStr })
      .then((d) => {
        if (id !== reqRef.current) return;
        setData(d);
        if (d.presets?.length) setPresets(d.presets);
      })
      .catch((e) => {
        if (id !== reqRef.current) return;
        setErr(e.data?.error === "not_a_representative"
          ? "این بخش فقط برای نمایندگان است."
          : "دریافت گزارش ناموفق بود. اتصال خود را بررسی کنید.");
      })
      .finally(() => { if (id === reqRef.current) setLoading(false); });
  }, [preset, custom, fromStr, toStr, tick]);

  const choosePreset = (k) => { haptic("selection"); setPick(""); setCustom(false); setPreset(k); };
  const openCustom = () => {
    haptic("selection");
    const r = data?.range || {};
    setFrom(jParse(r.from_jalali) || addMonths(jToday(), -1));
    setTo(jParse(r.to_jalali) || jToday());
    setCustom(true); setPick("from");
  };

  const getExcel = async () => {
    setSending(true); setNote(null);
    try {
      const d = await api("rep/purchases/excel", { preset, from: fromStr, to: toStr });
      haptic("success");
      setNote({ ok: true, text: `✅ فایل اکسل به چت شما ارسال شد${d.rows ? ` — ${fmt(d.rows)} ردیف` : ""}` });
    } catch (e) {
      haptic("error");
      setNote({ ok: false, text: `❌ ${e.data?.message || "ارسال فایل ناموفق بود. دوباره تلاش کنید."}`});
    } finally { setSending(false); }
  };

  const s = data?.summary || {};
  const rows = data?.rows || [];
  const rng = data?.range || {};

  return (
    <div className="rep-report">
      <div className="card rp-filter">
        <div className="list-title"><Icon name="clock" /> گزارش خرید بر اساس تاریخ</div>
        <div className="filter-chips">
          {presets.map((p) => (
            <button key={p.key} className={"fchip" + (!custom && preset === p.key ? " on" : "")}
                    onClick={() => choosePreset(p.key)}>{p.label}</button>
          ))}
          <button className={"fchip" + (custom ? " on" : "")} onClick={openCustom}>بازه دلخواه</button>
        </div>

        {custom && (
          <div className="rp-range">
            <button className={"rp-datebtn" + (pick === "from" ? " on" : "")}
                    onClick={() => { haptic("selection"); setPick(pick === "from" ? "" : "from"); }}>
              <span>از تاریخ</span>{jLong(from) || "انتخاب کنید"}
            </button>
            <button className={"rp-datebtn" + (pick === "to" ? " on" : "")}
                    onClick={() => { haptic("selection"); setPick(pick === "to" ? "" : "to"); }}>
              <span>تا تاریخ</span>{jLong(to) || "انتخاب کنید"}
            </button>
          </div>
        )}
        {custom && pick && (
          /* keyed so the grid re-opens on the month of whichever field is being edited */
          <MonthGrid key={pick} value={pick === "from" ? from : to}
                     onPick={(parts) => {
                       if (pick === "from") { setFrom(parts); setPick("to"); }
                       else { setTo(parts); setPick(""); }
                     }} />
        )}
        {rng.from_label && <div className="muted tiny">بازهٔ نمایش‌داده‌شده: از {rng.from_label} تا {rng.to_label}</div>}
      </div>

      {loading && <div className="card center" style={{ padding: 28 }}><Spinner /></div>}

      {!loading && err && (
        <div className="card center" style={{ padding: 22, gap: 10, display: "flex", flexDirection: "column" }}>
          <p className="muted" style={{ margin: 0 }}>{err}</p>
          <button className="btn-ghost sm" onClick={() => setTick((t) => t + 1)}>تلاش دوباره</button>
        </div>
      )}

      {!loading && !err && data && (
        <>
          <div className="card balance-card">
            <div className="balance-lbl">مجموع خرید ثبت‌شده در این بازه</div>
            <div className="balance-val">{fmt(s.total_spent)} <small>تومان</small></div>
          </div>
          <div className="rep-money-grid">
            <div className="card"><span className="muted">جمع فروش ثبت‌شده</span><b>{fmt(s.total_revenue)} <small>تومان</small></b></div>
            <div className="card"><span className="muted">سود قابل محاسبه</span><b className={s.total_profit < 0 ? "neg" : "pos"}><bdi>{fmt(s.total_profit)}</bdi> <small>تومان</small></b></div>
          </div>
          <p className="muted tiny">قیمت فروش فقط برای حساب‌وکتاب خودت است و تعرفه، کیف پول یا سرویس را تغییر نمی‌دهد. سود = فروش منهای قیمت خرید همان مورد.</p>
          <div className="rp-note accounting-note">{fmt(s.sales_count)} مورد قیمت فروش دارد؛ {fmt(s.unpriced_count)} مورد هنوز ثبت نشده. سود برای {fmt(s.profit_count)} مورد با قیمت خرید و فروش مشخص محاسبه شده است.</div>
          {(s.unknown_cost_orders > 0 || s.unknown_sale_cost_count > 0) && <p className="muted tiny">قیمت تاریخی {fmt(s.unknown_cost_orders)} سفارش قابل بازیابی نیست و در مجموع خرید نیامده؛ سود {fmt(s.unknown_sale_cost_count)} فروش هم هنوز قابل محاسبه نیست.</p>}

          <div className="rep-stat-grid">
            <div className="card rep-stat">
              <div className="rep-stat-ico mint"><Icon name="buy" /></div>
              <div className="rep-stat-val">{fmt(s.services)}</div><div className="rep-stat-lbl">سرویس جدید</div>
            </div>
            <div className="card rep-stat">
              <div className="rep-stat-ico blue"><Icon name="refresh" /></div>
              <div className="rep-stat-val">{fmt(s.renewals)}</div><div className="rep-stat-lbl">تمدید</div>
            </div>
            <div className="card rep-stat">
              <div className="rep-stat-ico mint"><Icon name="chart" /></div>
              {/* An unlimited plan has no GB to add up — it's counted separately, never as 0. */}
              <div className="rep-stat-val">{fmt(s.total_gb)} <small>GB</small></div>
              <div className="rep-stat-lbl">مجموع حجم{s.unlimited_count > 0 ? ` +${fmt(s.unlimited_count)} نامحدود` : ""}</div>
            </div>
            <div className="card rep-stat">
              <div className="rep-stat-ico amber"><Icon name="chart" /></div>
              <div className="rep-stat-val">{fmt(s.orders)}</div><div className="rep-stat-lbl">سفارش</div>
            </div>
          </div>

          <button className="btn-primary" disabled={sending} onClick={getExcel}>
            {sending ? "در حال ارسال به چت…" : <><Icon name="upload" />دریافت فایل اکسل</>}
          </button>
          {note && <div className={"rp-note " + (note.ok ? "ok" : "err")}>{note.text}</div>}
          {!note && <p className="muted tiny" style={{ margin: 0 }}>فایل اکسل به‌صورت سند در چت شما با ربات ارسال می‌شود.</p>}

          {s.legacy_configs > 0 && (
            <p className="muted tiny" style={{ margin: 0 }}>
              {fmt(s.legacy_configs)} کانفیگ قدیمی هم در این بازه ثبت شده که در فهرست زیر نمی‌آید.
            </p>
          )}

          {!rows.length ? (
            <div className="card center empty" style={{ padding: 26 }}>
              <div className="empty-emoji"><Icon name="chart" /></div>
              <p>در این بازه خریدی ثبت نشده</p>
            </div>
          ) : (
            <>
              <div className="muted tiny">{fmt(Math.min(shown, rows.length))} از {fmt(rows.length)} مورد</div>
              {rows.slice(0, shown).map((r) => (
                <div className="card svc rp-row" key={`${r.kind}-${r.order_id}-${r.profile_id}-${r.row}`}>
                  <div className="svc-head">
                    <b className="rp-name">{r.name}</b>
                    <span className={"badge " + repStatusCls(r.status)}>{r.status}</span>
                  </div>
                  <div className="rp-badges">
                    <span className={"badge " + (r.kind === "renewal" ? "cy" : "info")}>{r.kind_label}</span>
                    <span className="badge soft">📊 {r.is_unlimited ? r.traffic_label : `${r.traffic_label} GB`}</span>
                    <span className="badge soft">⏱ {r.duration_days > 0 ? `${r.duration_days} روز` : "نامحدود"}</span>
                  </div>
                  <div className="rp-facts">
                    <div className="rp-fact"><span>تاریخ خرید</span><b><D v={r.purchased_at} /></b></div>
                    <div className="rp-fact"><span>تاریخ شروع</span><b><D v={r.started_at} /></b></div>
                    <div className="rp-fact"><span>تاریخ انقضا</span><b><D v={r.expires_at} /></b></div>
                  </div>
                  <RepSalePrice row={r} onSaved={() => setTick(t => t + 1)} />
                </div>
              ))}
              {shown < rows.length && (
                <button className="btn-soft" style={{ width: "100%" }}
                        onClick={() => { haptic("selection"); setShown(shown + PAGE); }}>
                  نمایش بیشتر ({fmt(rows.length - shown)} مورد دیگر)
                </button>
              )}
            </>
          )}
          {data.generated_at && <p className="muted tiny" style={{ margin: 0 }}>تهیه گزارش: <D v={data.generated_at} /></p>}
          {s.report_row_count > rows.length && <p className="muted tiny">فهرست به {fmt(rows.length)} مورد محدود شده؛ جمع‌ها مربوط به کل بازه است. برای مشاهدهٔ باقی موارد، بازه را کوتاه‌تر کن.</p>}
        </>
      )}
    </div>
  );
}

function RepPanel({ data, support }) {
  const rep = data.rep || {};
  const f = rep.financials || {};
  const avg = f.orders ? Math.round((f.total_spent || 0) / f.orders) : 0;
  return (
    <div className="screen">
      <h2 className="screen-title">پنل نمایندگی</h2>
      <div className="card rep-brandcard">
        <div className="rep-brand-row">
          <div className="rep-brand-logo"><Icon name="rep" /></div>
          <div>
            <div className="rep-brand-name">{rep.brand_name || "— برند تنظیم نشده —"}</div>
            <div className="muted tiny">{rep.has_logo ? "لوگو تنظیم شده ✅" : "لوگو تنظیم نشده"}</div>
          </div>
        </div>
        <p className="muted tiny" style={{ margin: "8px 0 0" }}>برند و لوگوی خودت روی لینک مشتری‌هایت نمایش داده می‌شود. تنظیم برند/لوگو از داخل ربات، بخش «🏢 پنل نمایندگی».</p>
      </div>

      <div className="rep-stat-grid">
        <div className="card rep-stat"><div className="rep-stat-ico mint"><Icon name="buy" /></div><div className="rep-stat-val">{fmt(f.total_spent)}</div><div className="rep-stat-lbl">کل خرید (ت)</div></div>
        <div className="card rep-stat"><div className="rep-stat-ico mint"><Icon name="clock" /></div><div className="rep-stat-val">{fmt(f.month_spent)}</div><div className="rep-stat-lbl">خرید این ماه</div></div>
        <div className="card rep-stat"><div className="rep-stat-ico blue"><Icon name="services" /></div><div className="rep-stat-val">{f.active_services || 0}/{f.total_services || 0}</div><div className="rep-stat-lbl">سرویس فعال/کل</div></div>
        <div className="card rep-stat"><div className="rep-stat-ico amber"><Icon name="chart" /></div><div className="rep-stat-val">{fmt(f.orders)}</div><div className="rep-stat-lbl">سفارش‌ها</div></div>
      </div>

      {/* Same gate as the tab itself — the endpoint 403s for non-reps anyway. */}
      {data.is_rep && <RepReport />}

      <div className="card">
        <div className="list-title">راهنما</div>
        <p className="muted tiny" style={{ lineHeight: 2, margin: 0 }}>
          • «سرویس‌ها» = مشتریان تو. هر سرویس را با اسم مشتری نام‌گذاری کن و لینکش را بده.<br />
          • میانگین هزینه‌ی هر سرویس: <b>{fmt(avg)}</b> تومان — قیمت فروش به مشتری منهای این = سود تو.<br />
          • برای ساخت سرویس جدید از تب «خرید» استفاده کن.
        </p>
      </div>

      {support && <a className="support-card" href={`https://t.me/${support}`} target="_blank" rel="noreferrer"><span className="support-icon"><Icon name="support" /></span><span className="support-copy"><b>پشتیبانی نمایندگان</b><small>برای پاسخ به سوال‌هایت کنارت هستیم</small></span><Icon name="arrow" className="chev" /></a>}
    </div>
  );
}

const TABS = [
  { k: "home", label: "خانه" },
  { k: "services", label: "سرویس‌ها" },
  { k: "buy", label: "خرید" },
  { k: "wallet", label: "کیف پول" },
  { k: "referral", label: "دعوت" },
];
const REP_TAB = { k: "rep", label: "نمایندگی" };

export default function App() {
  const [tab, setTab] = useState("home");
  const [boot, setBoot] = useState(null);
  const [err, setErr] = useState("");
  const [reason, setReason] = useState("");
  const load = useCallback(() => {
    setErr(""); setReason("");
    api("bootstrap").then(setBoot).catch((e) => {
      setReason(e?.data?.reason || "");
      setErr(String(e.message || e));
    });
  }, []);
  useEffect(() => { load(); }, [load]);
  const balance = boot?.user?.balance ?? 0;
  const setBalance = useCallback((newBal) => {
    if (newBal == null) return;
    setBoot((b) => (b ? { ...b, user: { ...b.user, balance: newBal } } : b));
  }, []);

  if (err) {
    // Missing launch data (including an unavailable SDK) is different from a
    // correctly signed but expired session. Recovery must not promise renewal.
    const expired = reason === "expired";
    const missing = reason === "no_data";
    return (
      <div className="fullscreen center">
        <div className="empty-emoji"><Icon name={expired ? "refresh" : "lock"} /></div>
        {expired ? (
          <>
            <p>این صفحه قدیمی شده است.</p>
            <small className="muted" style={{ lineHeight: 2 }}>
              نشست ورود منقضی شده است. مینی‌اپ را ببند و از دکمهٔ داخل ربات دوباره باز کن.
            </small>
          </>
        ) : missing ? (
          <>
            <p>اطلاعات ورود تلگرام دریافت نشد.</p>
            <small className="muted" style={{ lineHeight: 2 }}>از دکمهٔ مینی‌اپ داخل ربات وارد شو. اگر همین‌جا باز کرده‌ای، اتصال را بررسی کن و دوباره تلاش کن.</small>
          </>
        ) : (
          <>
            <p>دسترسی نامعتبر است. لطفاً از داخل ربات تلگرام باز کنید.</p>
            <small className="muted">{err}</small>
          </>
        )}
        <button className="btn-primary sm" style={{ marginTop: 14 }}
                onClick={() => expired ? closeOrReload() : load()}>
          {expired ? "بستن مینی‌اپ" : "تلاش دوباره"}
        </button>
      </div>
    );
  }
  if (!boot) return <div className="fullscreen center"><Spinner /></div>;
  if (boot.enabled === false) return (
    <div className="fullscreen center"><div className="empty-emoji"><Icon name="services" /></div><p>{boot.brand?.title || "Atlas"} موقتاً در دسترس نیست.</p></div>
  );

  const tabs = boot.is_rep ? [TABS[0], TABS[1], TABS[2], REP_TAB, TABS[3]] : TABS;

  return (
    <div className="app">
      <Header brand={boot.brand} user={boot.user} isRep={boot.is_rep} go={setTab} compact={tab !== "home"} />
      <main className="body">
        {tab === "home" && <Home data={boot} go={setTab} />}
        {tab === "services" && <Services go={setTab} balance={balance} onBalance={setBalance} isRep={boot.is_rep} />}
        {tab === "buy" && <Buy balance={balance} onBalance={setBalance} />}
        {tab === "rep" && <RepPanel data={boot} support={boot.support} />}
        {tab === "wallet" && <Wallet />}
        {tab === "referral" && <Referral />}
      </main>
      <nav className="tabbar" aria-label="ناوبری اصلی">
        {tabs.map((t) => (
          <button key={t.k} aria-current={tab === t.k ? "page" : undefined} className={"tab " + (tab === t.k ? "active" : "")} onClick={() => { haptic("selection"); setTab(t.k); }}>
            <span className="tab-icon"><Icon name={t.k} /></span><span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>
      {/* Outside <main> so a toast is never clipped by a scrolling panel. */}
      <Toaster />
    </div>
  );
}
