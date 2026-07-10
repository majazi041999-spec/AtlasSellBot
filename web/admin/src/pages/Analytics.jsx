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
  return (
    <Modal title={title} onClose={onClose}>
      {!d ? <Loading /> : !(d.items || []).length ? <Empty emoji="🫧">موردی نیست</Empty> : (
        <div className="grid" style={{ gap: 8 }}>
          {kind === "online" && <div className="muted tiny">مجموع اتصال‌های آنلاین: {fmt(d.connections)} · کاربران: {fmt(d.count)}</div>}
          {d.items.map((it, i) => (
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
            <div style={{ fontWeight: 800, fontSize: "1.2rem", color: "var(--p2)" }}>{fmt(t.forecast_next7)} <span className="muted tiny">ت</span></div>
          </div>
          <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="muted tiny">پیش‌بینی ۳۰ روز آینده</div>
            <div style={{ fontWeight: 800, fontSize: "1.2rem", color: "#34d399" }}>{fmt(t.forecast_next30)} <span className="muted tiny">ت</span></div>
          </div>
        </div>
        <p className="muted tiny" style={{ margin: "10px 0 0" }}>پیش‌بینی با رگرسیون خطی روی ۳۰ روز اخیر (روی همین سرور، بدون هزینه). تخمین است نه تضمین.</p>
      </Card>

      <Card title="👥 کاربران جدید (۳۰ روز)" sub="نشانگر را روی نمودار نگه دار تا مقدار هر روز را ببینی">
        <Chart points={userPoints} kind="bar" valueFmt={(v) => String(Math.round(v))} height={150} />
      </Card>

      {seg && <SegmentModal kind={seg.kind} title={seg.title} onClose={() => setSeg(null)} />}
    </div>
  );
}
