import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Stat, Modal, Loading, Empty } from "../components/ui.jsx";

const compact = (n) => {
  n = Number(n || 0);
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(Math.round(n));
};
const shortDate = (s) => (s || "").slice(5); // MM-DD

// Interactive chart: line (revenue + dashed forecast) or bars (users), with a
// hover crosshair + tooltip. Works on touch (tap) and mouse.
function Chart({ points, kind = "line", forecastFrom = -1, valueFmt = compact, height = 190 }) {
  const [hi, setHi] = useState(-1);
  const wrap = useRef();
  const W = 720, pad = { l: 46, r: 12, t: 14, b: 26 };
  const H = height;
  const n = points.length;
  const vals = points.map((p) => p.v);
  const max = Math.max(1, ...vals);
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const x = (i) => pad.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const gy = [0, 0.25, 0.5, 0.75, 1];

  const onMove = (e) => {
    const r = wrap.current.getBoundingClientRect();
    const cx = ((e.touches ? e.touches[0].clientX : e.clientX) - r.left) / r.width * W;
    let best = 0, bd = 1e9;
    for (let i = 0; i < n; i++) { const d = Math.abs(x(i) - cx); if (d < bd) { bd = d; best = i; } }
    setHi(best);
  };

  const solidPts = points.map((p, i) => [x(i), y(p.v)]);
  const line = (pts) => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const splitAt = forecastFrom >= 0 ? forecastFrom : n;
  const realPts = solidPts.slice(0, splitAt + 1);
  const fcPts = forecastFrom >= 0 ? solidPts.slice(splitAt) : [];
  const areaPath = realPts.length
    ? `${line(realPts)} L ${realPts[realPts.length - 1][0].toFixed(1)} ${(pad.t + ih).toFixed(1)} L ${realPts[0][0].toFixed(1)} ${(pad.t + ih).toFixed(1)} Z` : "";

  const tickEvery = Math.max(1, Math.ceil(n / 8));
  const hp = hi >= 0 ? points[hi] : null;

  return (
    <div ref={wrap} style={{ position: "relative", overflowX: "auto" }}
      onMouseMove={onMove} onMouseLeave={() => setHi(-1)} onTouchStart={onMove} onTouchMove={onMove}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 520, display: "block" }}>
        <defs>
          <linearGradient id="afill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--p2)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--p2)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {gy.map((f, i) => {
          const yy = pad.t + ih - f * ih;
          return (<g key={i}>
            <line x1={pad.l} y1={yy} x2={W - pad.r} y2={yy} stroke="var(--line)" strokeWidth="1" opacity="0.45" />
            <text x={pad.l - 6} y={yy + 3} textAnchor="end" fontSize="10" fill="var(--txt3)">{valueFmt(max * f)}</text>
          </g>);
        })}
        {kind === "bar" ? points.map((p, i) => {
          const bw = iw / n; const h = (p.v / max) * ih;
          return <rect key={i} x={pad.l + i * bw + 1} y={pad.t + ih - h} width={Math.max(1, bw - 2)} height={h}
            rx="2" fill="var(--p2)" opacity={hi === i ? 1 : 0.4 + 0.5 * (p.v / max)} />;
        }) : (<>
          {areaPath && <path d={areaPath} fill="url(#afill)" />}
          {realPts.length > 1 && <path d={line(realPts)} fill="none" stroke="var(--p2)" strokeWidth="2.5" strokeLinejoin="round" />}
          {fcPts.length > 1 && <path d={line(fcPts)} fill="none" stroke="var(--p2)" strokeWidth="2.2" strokeDasharray="5 4" opacity="0.7" />}
        </>)}
        {points.map((p, i) => i % tickEvery === 0 && (
          <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--txt3)">{shortDate(p.d)}</text>
        ))}
        {hp && (<g>
          <line x1={x(hi)} y1={pad.t} x2={x(hi)} y2={pad.t + ih} stroke="var(--p2)" strokeWidth="1" opacity="0.5" />
          <circle cx={x(hi)} cy={y(hp.v)} r="4" fill="var(--p2)" stroke="var(--bg,#0b0e14)" strokeWidth="1.5" />
        </g>)}
      </svg>
      {hp && (
        <div style={{ position: "absolute", top: 6, insetInlineStart: `clamp(8px, ${(x(hi) / W) * 100}%, calc(100% - 130px))`,
          background: "var(--card,#1a1d27)", border: "1px solid var(--line)", borderRadius: 8, padding: "6px 9px",
          pointerEvents: "none", fontSize: ".72rem", whiteSpace: "nowrap", boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}>
          <div className="muted" style={{ fontSize: ".68rem" }}>{hp.d}{hp.forecast ? " (پیش‌بینی)" : ""}</div>
          <div style={{ fontWeight: 700, color: "var(--p2)" }}>{fmt(hp.v)}</div>
        </div>
      )}
    </div>
  );
}

function SegmentModal({ kind, title, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/api/analytics/segment/${kind}`).then(setD).catch(() => setD({ items: [] })); }, [kind]);
  const empty = d && !(d.items || []).length;
  return (
    <Modal title={title} onClose={onClose}>
      {!d ? <Loading /> : (
        <div className="grid" style={{ gap: 8 }}>
          {kind === "online" && (
            <div className="muted tiny">مجموع اتصال‌های آنلاین: {fmt(d.connections || 0)} · کاربران map‌شده: {fmt(d.count || 0)}</div>
          )}
          {empty && kind === "online" && (d.connections || 0) > 0 && (
            <div style={{ background: "rgba(251,191,36,.08)", border: "1px solid rgba(251,191,36,.3)", borderRadius: 10, padding: 10, fontSize: ".82rem" }}>
              {fmt(d.connections)} اتصال آنلاین هست ولی به کاربری نگاشت نشد (ایمیل کلاینت‌ها با دیتابیس مطابقت نداشت).
            </div>
          )}
          {empty && !(kind === "online" && (d.connections || 0) > 0) && <Empty emoji="🫧">موردی نیست</Empty>}
          {(d.items || []).map((it, i) => (
            <div key={i} className="between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 10, padding: "9px 12px", gap: 10, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0 }}>
                <b>{it.full_name || "—"}</b>
                <span className="muted tiny"> {it.username ? `@${it.username}` : ""} <span className="mono">{it.telegram_id}</span></span>
                {it.title ? <div className="muted tiny">{it.title}</div> : null}
              </div>
              <b style={{ color: "var(--p2)", whiteSpace: "nowrap" }}>{it.value}</b>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function SegTile({ icon, label, count, hint, onClick }) {
  return (
    <button onClick={onClick} className="seg-tile" style={{ textAlign: "start", cursor: "pointer",
      background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 16, padding: 14 }}>
      <div className="row between">
        <span style={{ fontSize: "1.5rem" }}>{icon}</span>
        {count != null && <span className="badge b-purple">{fmt(count)}</span>}
      </div>
      <div style={{ fontWeight: 700, marginTop: 8 }}>{label}</div>
      <div className="muted tiny">{hint || "مشاهده لیست ›"}</div>
    </button>
  );
}

/** Forecast quality is measured on later, unseen dates, including model selection. */
function ForecastNotes({ meta }) {
  if (!meta) return null;
  if (meta.ok === false) return (
    <div className="forecast-notice">
      <b>{meta.reason === "incomplete_revenue" ? "مبالغ تاریخی کامل نیستند." : "هنوز سابقهٔ کافی برای پیش‌بینی نداریم."}</b>
      <p className="muted tiny">{meta.reason === "incomplete_revenue"
        ? `مبلغ ${fmt(meta.unknown_revenue_orders)} سفارش قدیمی مشخص نیست. پس از آخرین روز ناقص، ${fmt(meta.history_days)} روز کامل داریم؛ برای پیش‌بینی حداقل ۱۴ روز پیوسته لازم است.`
        : `${fmt(meta.history_days)} روز کامل از آغاز فروش داریم؛ حداقل ۱۴ روز لازم است. روز جاری و روزهای قبل از شروع فروش در آموزش نمی‌آیند.`}</p>
    </div>
  );
  const d = meta.drivers || {};
  const horizons = [
    { label: "۷ روز", method: meta.method_label, accuracy: meta.accuracy, band: meta.band7, comparison: meta.versus_baseline },
    { label: "۳۰ روز", method: meta.method30_label, accuracy: meta.accuracy30, band: meta.band30, comparison: meta.versus_baseline30 },
  ];
  return (
    <div className="forecast-notes">
      {meta.excluded_history_days > 0 && <div className="forecast-notice tiny">
        مبلغ تاریخی {fmt(meta.unknown_revenue_orders)} سفارش مشخص نیست؛ {fmt(meta.excluded_history_days)} روز ابتدایی کنار گذاشته شد. پیش‌بینی از سابقهٔ کاملِ <bdi>{meta.training_start}</bdi> به بعد استفاده می‌کند.
      </div>}
      <p className="muted tiny">آموزش با {fmt(meta.history_days)} روز کامل، تا <bdi>{meta.trained_through}</bdi>؛ پیش‌بینی از فردا شروع می‌شود. روش هر افق جداگانه با آزمون روی گذشته انتخاب می‌شود.</p>
      <div className="forecast-quality-grid">
        {horizons.map(h => <div className="forecast-quality" key={h.label}>
          <b>ارزیابی پیش‌بینی {h.label} آینده</b>
          <div className="muted tiny">روش: {h.method || "سطح پایدار سفارش‌ها"}</div>
          {h.accuracy ? <>
            <div className="forecast-error"><b>{h.accuracy.smape}٪</b><span>خطای میانگین sMAPE · کمتر بهتر</span></div>
            <div className="muted tiny">روی {fmt(h.accuracy.folds)} بازهٔ گذشته؛ میانگین خطای مبلغ: {fmt(h.accuracy.mae)} تومان</div>
            {h.comparison && <div className={"badge " + (h.comparison.error_reduction_pct >= 0 ? "b-green" : "b-yellow")}>
              {Math.abs(h.comparison.error_reduction_pct)}٪ خطای {h.comparison.error_reduction_pct >= 0 ? "کمتر" : "بیشتر"} از مدل قبلی
            </div>}
          </> : <p className="muted tiny">هنوز بازهٔ کافی برای اندازه‌گیری دقت نداریم.</p>}
          {h.band && <div className="forecast-range">
            <span className="muted tiny">بازهٔ معمول بر اساس خطاهای گذشته</span>
            <b>{fmt(h.band.low)} تا {fmt(h.band.high)} تومان</b>
            <span className="muted tiny">{h.band.observed_coverage != null
              ? `پوشش آزموده‌شده: ${h.band.observed_coverage}٪ در ${fmt(h.band.coverage_folds)} بازه؛ تضمین نتیجهٔ آینده نیست.`
              : "سابقهٔ کافی برای سنجش پوشش این بازه نداریم."}</span>
          </div>}
        </div>)}
      </div>
      <p className="muted tiny">اطلاعات بازهٔ اخیر: {d.orders_per_day} سفارش در روز و متوسط مبلغ خرید {fmt(d.avg_basket)} تومان. همهٔ محاسبات روی همین سرور انجام می‌شود.</p>
      {(meta.backtest || []).length > 0 && <details className="forecast-history">
        <summary>پیش‌بینی در برابر درآمد واقعی در آزمون‌های گذشته</summary>
        <div className="table-wrap"><table><thead><tr><th>آخرین روز آموزش</th><th>پیش‌بینی ۷ روز</th><th>درآمد واقعی همان بازه</th></tr></thead><tbody>
          {meta.backtest.slice(-6).reverse().map(r => <tr key={r.origin}><td><bdi>{r.origin}</bdi></td><td>{fmt(r.predicted)}</td><td>{fmt(r.actual)}</td></tr>)}
        </tbody></table></div>
        <p className="muted tiny">ارقام به تومان است. انتخاب روش و محاسبهٔ هر ردیف فقط با دادهٔ قبل از آن انجام شده؛ بازه‌ها با هم هم‌پوشانی دارند.</p>
      </details>}
    </div>
  );
}

function RevenueMix({ mix, totals }) {
  if (!mix) return null;
  const rep = mix.reseller_share_pct, ren = mix.renewal_share_pct;
  return (
    <Card title="🧭 ترکیب درآمد" sub="۹۰ روز گذشته — از کجا می‌آید و چقدرش قابل‌پیش‌بینی است">
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
        {rep != null && (
          <div style={{ background: "rgba(124,111,255,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div style={{ fontWeight: 800, fontSize: "1.3rem", color: "var(--p2)" }}>{rep}٪</div>
            <div className="muted tiny">سهم نمایندگان از درآمد</div>
          </div>
        )}
        {ren != null && (
          <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div style={{ fontWeight: 800, fontSize: "1.3rem", color: "#34d399" }}>{ren}٪</div>
            <div className="muted tiny">سهم تمدیدها — قابل‌پیش‌بینی‌ترین بخش</div>
          </div>
        )}
        <div style={{ background: "rgba(251,191,36,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
          <div style={{ fontWeight: 800, fontSize: "1.3rem", color: "#fbbf24" }}>{fmt(totals.expiring_30d)}</div>
          <div className="muted tiny">منقضی‌شونده در ۳۰ روز — فرصت تمدید</div>
        </div>
      </div>
      {(mix.top_packages || []).length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>پکیج</th><th>سفارش</th><th>درآمد</th></tr></thead>
            <tbody>
              {mix.top_packages.slice(0, 6).map((p, i) => (
                <tr key={i}>
                  <td>{p.name || "—"}</td>
                  <td className="mono">{fmt(p.orders)}</td>
                  <td className="mono">{fmt(p.revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const SEV = { good: ["b-green", "✅"], watch: ["b-yellow", "👀"], risk: ["b-red", "⚠️"] };
const EFFORT = { low: "کم", medium: "متوسط", high: "زیاد" };

/** The model reads the numbers this panel computed. It never produces one —
 *  see core/ai_analyst.py for why that split is the whole design. */
function AiAnalysis() {
  const [status, setStatus] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/api/analytics/ai/status").then(setStatus).catch(() => setStatus({ enabled: false }));
  }, []);

  const run = async () => {
    setBusy(true); setRes(null);
    try { setRes(await api.get("/api/analytics/ai")); }
    catch (e) { setRes({ ok: false, message: e.message || "خطا" }); }
    finally { setBusy(false); }
  };

  if (!status) return null;
  if (!status.enabled || !status.configured) {
    return (
      <Card title="🤖 تحلیل هوش مصنوعی" sub="خاموش است">
        <p className="muted tiny" style={{ margin: 0, lineHeight: 2 }}>
          می‌توانی یک مدل هوش مصنوعی وصل کنی تا همین اعداد را تحلیل کند و بگوید این هفته
          چه کار کنی. <b>اعداد را مدل نمی‌سازد</b> — پیش‌بینی و آمار روی همین سرور محاسبه
          می‌شود و مدل فقط تفسیرشان می‌کند.
          <br />
          از «تنظیمات ← تحلیل هوش مصنوعی» روشنش کن. Gemini با مدل Flash رایگان است و
          کارت اعتباری نمی‌خواهد.
        </p>
      </Card>
    );
  }

  const a = res?.analysis;
  return (
    <Card title="🤖 تحلیل هوش مصنوعی" sub={`${status.provider} · ${status.model}`}
          right={<button className="btn sm primary" disabled={busy} onClick={run}>
                   {busy ? "در حال تحلیل…" : res ? "↻ دوباره" : "▶ تحلیل کن"}
                 </button>}>
      {!res && !busy && (
        <p className="muted tiny" style={{ margin: 0 }}>
          دکمه را بزن تا مدل، آمار و پیش‌بینی همین صفحه را تحلیل کند.
        </p>
      )}
      {res && !res.ok && (
        <div style={{ background: "rgba(251,113,133,.1)", border: "1px solid rgba(251,113,133,.3)",
                      borderRadius: 12, padding: 12, lineHeight: 2 }}>{res.message}</div>
      )}
      {a && (
        <div className="grid" style={{ gap: 12 }}>
          <div>
            <div style={{ fontWeight: 800, fontSize: "1.05rem" }}>{a.headline}</div>
            <p className="muted" style={{ margin: "6px 0 0", fontSize: ".88rem", lineHeight: 2 }}>{a.summary}</p>
          </div>
          {(a.findings || []).length > 0 && (
            <div className="grid" style={{ gap: 8 }}>
              {a.findings.map((f, i) => {
                const sev = SEV[f.severity] || SEV.watch;
                return (
                  <div key={i} style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)",
                                        borderRadius: 12, padding: "10px 12px" }}>
                    <div className="row" style={{ gap: 8 }}>
                      <span className={"badge " + sev[0]}>{sev[1]}</span>
                      <b style={{ fontSize: ".9rem" }}>{f.title}</b>
                    </div>
                    <p className="muted tiny" style={{ margin: "5px 0 0", lineHeight: 1.9 }}>{f.detail}</p>
                    {f.based_on ? <div className="muted tiny" style={{ marginTop: 4, opacity: .75 }}>مبنا: {f.based_on}</div> : null}
                  </div>
                );
              })}
            </div>
          )}
          {(a.actions || []).length > 0 && (
            <div>
              <div className="muted tiny" style={{ marginBottom: 6 }}>پیشنهاد اقدام</div>
              <div className="grid" style={{ gap: 8 }}>
                {a.actions.map((ac, i) => (
                  <div key={i} className="row between" style={{ background: "rgba(124,111,255,.07)",
                        border: "1px solid var(--line)", borderRadius: 12, padding: "10px 12px", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ minWidth: 0 }}>
                      <b style={{ fontSize: ".9rem" }}>{ac.title}</b>
                      <p className="muted tiny" style={{ margin: "4px 0 0", lineHeight: 1.9 }}>{ac.why}</p>
                    </div>
                    <span className="badge b-gray">زحمت: {EFFORT[ac.effort] || ac.effort}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="muted tiny" style={{ opacity: .8, lineHeight: 1.9 }}>
            اطمینان مدل: {a.confidence === "high" ? "بالا" : a.confidence === "low" ? "پایین" : "متوسط"}
            {a.confidence_reason ? ` — ${a.confidence_reason}` : ""}
            <br />همه‌ی اعداد از محاسبات همین پنل است؛ مدل عددی نساخته.
          </div>
        </div>
      )}
    </Card>
  );
}


// The acquisition funnel: who arrived, who tried, who bought, who left.
//
// Every stage except "blocked" is counted against the day the person JOINED,
// which is what makes a day's conversion rate mean something — the server does
// that; this only draws it.
function Funnel() {
  const [d, setD] = useState(null);
  const [days, setDays] = useState(30);
  useEffect(() => {
    setD(null);
    api.get(`/api/analytics/funnel?days=${days}`).then(setD).catch(() => setD({ error: true }));
  }, [days]);

  if (!d) return <Card title="🫙 قیف جذب"><div className="muted tiny">در حال محاسبه…</div></Card>;
  if (d.error) return null;
  const t = d.totals || {};

  // Widths are relative to the widest stage, not to the total, so a small
  // stage stays visible instead of collapsing into a line nobody can read.
  const stages = [
    { k: "users", label: "وارد شدند", v: t.users, c: "#38bdf8" },
    { k: "trials", label: "تست گرفتند", v: t.trials, c: "#34d399", sub: `${t.trial_rate}٪ از واردشده‌ها` },
    { k: "buyers", label: "خرید کردند", v: t.buyers, c: "#a78bfa", sub: `${t.buy_rate}٪ از واردشده‌ها` },
  ];
  const widest = Math.max(1, ...stages.map((s) => s.v || 0));

  const cell = { padding: "7px 9px", borderBottom: "1px solid var(--line)", whiteSpace: "nowrap" };

  return (
    <Card
      title="🫙 قیف جذب — از ورود تا خرید"
      sub="هر مرحله به روزی نسبت داده می‌شود که کاربر وارد شده، نه روزی که آن کار را کرده"
      right={
        <select className="inp" value={days} onChange={(e) => setDays(Number(e.target.value))}
          style={{ width: 110 }}>
          <option value={7}>۷ روز</option>
          <option value={30}>۳۰ روز</option>
          <option value={90}>۹۰ روز</option>
          <option value={180}>۱۸۰ روز</option>
        </select>
      }
    >
      <div className="grid" style={{ gap: 8, marginBottom: 14 }}>
        {stages.map((s) => (
          <div key={s.k}>
            <div className="between" style={{ marginBottom: 4 }}>
              <b>{s.label}</b>
              <span style={{ color: s.c, fontWeight: 800 }}>{fmt(s.v)}</span>
            </div>
            <div style={{ height: 10, background: "rgba(255,255,255,.05)", borderRadius: 6, overflow: "hidden" }}>
              <div style={{ width: `${Math.max(2, (100 * (s.v || 0)) / widest)}%`, height: "100%", background: s.c }} />
            </div>
            {s.sub ? <div className="muted tiny" style={{ marginTop: 3 }}>{s.sub}</div> : null}
          </div>
        ))}
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 14 }}>
        <Stat icon="🎯" value={`${t.trial_to_buy_rate}%`} label="تست ← خرید"
          grad="linear-gradient(135deg,#34d399,#10b981)" foot={`${fmt(t.trial_then_bought)} از ${fmt(t.trials)} نفر`} />
        <Stat icon="🕳" value={fmt(t.never_tried)} label="هرگز تست نگرفتند"
          grad="linear-gradient(135deg,#fbbf24,#f59e0b)" foot="بزرگ‌ترین فرصت رشد" />
        <Stat icon="💔" value={fmt(t.trial_no_buy)} label="تست گرفتند، نخریدند"
          grad="linear-gradient(135deg,#fb7185,#f43f5e)" />
        <Stat icon="🚫" value={fmt(t.blocked_now)} label="ربات را بلاک کرده‌اند"
          grad="linear-gradient(135deg,#94a3b8,#64748b)" foot={`${t.block_rate}٪ از کاربران`} />
      </div>

      {!d.block_tracking_since && (
        <div className="note" style={{ marginBottom: 12 }}>
          ⓘ <b>ردیابی بلاک تازه شروع شده.</b> عدد صفر یعنی از زمان فعال‌شدنِ ردیابی
          کسی بلاک نکرده — نه اینکه هیچ‌وقت کسی بلاک نکرده باشد. کسانی که قبلاً
          رفته‌اند شمرده نمی‌شوند.
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".86rem" }}>
          <thead>
            <tr className="muted tiny">
              <th style={{ ...cell, textAlign: "start" }}>تاریخ</th>
              <th style={cell}>وارد</th>
              <th style={cell}>تست</th>
              <th style={cell}>خرید</th>
              <th style={cell}>تست→خرید</th>
              <th style={cell}>تست بدون خرید</th>
              <th style={cell}>بلاک</th>
            </tr>
          </thead>
          <tbody>
            {(d.daily || []).slice().reverse().map((r) => (
              <tr key={r.date}>
                <td style={{ ...cell, textAlign: "start" }} className="mono tiny">{r.date}</td>
                <td style={{ ...cell, textAlign: "center", fontWeight: 700 }}>{r.joined || "—"}</td>
                <td style={{ ...cell, textAlign: "center", color: "#34d399" }}>{r.trials || "—"}</td>
                <td style={{ ...cell, textAlign: "center", color: "#a78bfa" }}>{r.buyers || "—"}</td>
                <td style={{ ...cell, textAlign: "center" }}>{r.trial_then_bought || "—"}</td>
                <td style={{ ...cell, textAlign: "center", color: "#fb7185" }}>{r.trial_no_buy || "—"}</td>
                <td style={{ ...cell, textAlign: "center", color: "#94a3b8" }}>{r.blocked_today || "—"}</td>
              </tr>
            ))}
            {!(d.daily || []).length && (
              <tr><td colSpan={7} className="muted tiny" style={{ padding: 14, textAlign: "center" }}>
                در این بازه کاربری وارد نشده است.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function Analytics() {
  const [a, setA] = useState(null);
  const [seg, setSeg] = useState(null);
  useEffect(() => { api.get("/api/analytics").then(setA).catch(() => setA({ error: true })); }, []);
  if (!a) return <Card title="📈 آنالیتیکس"><div className="muted tiny">در حال محاسبه…</div></Card>;
  if (a.error) return null;
  const t = a.totals || {};
  const up = (t.momentum_pct || 0) >= 0;

  const revPoints = [
    ...(a.revenue || []).map((r) => ({ d: r.date, v: r.revenue })),
    ...(a.forecast || []).map((r) => ({ d: r.date, v: r.revenue, forecast: true })),
  ];
  const forecastFrom = (a.revenue || []).length - 1;
  const userPoints = (a.users || []).map((u) => ({ d: u.date, v: u.new_users }));

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid stat-grid">
        <Stat icon="👥" value={fmt(t.total_users)} label="کل کاربران" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" foot={`۳۰ روز: +${fmt(t.new_users_30d)}`} />
        <Stat icon="🧬" value={fmt(t.active_subs)} label="ساب‌های فعال" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="💰" value={compact(t.revenue_30d)} label="درآمد ۳۰ روز" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" foot={`میانگین: ${compact(t.avg_daily_revenue)}/روز`} />
        <Stat icon={up ? "📈" : "📉"} value={`${up ? "+" : ""}${t.momentum_pct}%`} label="روند ۷ روزه"
          grad={up ? "linear-gradient(135deg,#34d399,#10b981)" : "linear-gradient(135deg,#fb7185,#f43f5e)"} foot="نسبت به هفته قبل" />
      </div>

      {/* Drill-down segments */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
        <SegTile icon="🟢" label="کاربران آنلاین" hint="بررسی زنده ›" onClick={() => setSeg({ kind: "online", title: "🟢 کاربران آنلاین" })} />
        <SegTile icon="⏳" label="نزدیک انقضا" count={t.near_expiry} hint="۳ روز آینده ›" onClick={() => setSeg({ kind: "expiring", title: "⏳ سرویس‌های نزدیک انقضا" })} />
        <SegTile icon="🏆" label="بیشترین خرید" onClick={() => setSeg({ kind: "top_buyers", title: "🏆 بیشترین خرید" })} />
        <SegTile icon="🔑" label="بیشترین سرویس فعال" onClick={() => setSeg({ kind: "top_services", title: "🔑 بیشترین سرویس فعال" })} />
      </div>

      <Card title="📈 روند درآمد و پیش‌بینی هوشمند" sub="خط پیوسته: ۳۰ روز گذشته · خط‌چین: پیش‌بینی ۷ روز · نشانگر را نگه دار">
        <Chart points={revPoints} kind="line" forecastFrom={forecastFrom} valueFmt={compact} />
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          <div style={{ background: "rgba(124,111,255,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="muted tiny">پیش‌بینی ۷ روز آینده</div>
            <div style={{ fontWeight: 800, fontSize: "1.2rem", color: "var(--p2)" }}>{t.forecast_next7 == null ? "—" : fmt(t.forecast_next7)} <span className="muted tiny">ت</span></div>
          </div>
          <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="muted tiny">پیش‌بینی ۳۰ روز آینده</div>
            <div style={{ fontWeight: 800, fontSize: "1.2rem", color: "#34d399" }}>{t.forecast_next30 == null ? "—" : fmt(t.forecast_next30)} <span className="muted tiny">ت</span></div>
          </div>
        </div>
        <ForecastNotes meta={a.forecast_meta} />
      </Card>

      <Funnel />

      <RevenueMix mix={a.mix} totals={t} />

      <AiAnalysis />

      <Card title="👥 کاربران جدید (۳۰ روز)" sub="نشانگر را روی نمودار نگه دار تا مقدار هر روز را ببینی">
        <Chart points={userPoints} kind="bar" valueFmt={(v) => String(Math.round(v))} height={150} />
      </Card>

      {seg && <SegmentModal kind={seg.kind} title={seg.title} onClose={() => setSeg(null)} />}
    </div>
  );
}
