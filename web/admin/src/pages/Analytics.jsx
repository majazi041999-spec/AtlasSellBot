import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Stat } from "../components/ui.jsx";

const compact = (n) => {
  n = Number(n || 0);
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return String(Math.round(n));
};

// Revenue line: 30d actual (solid) + 7d forecast (dashed), with an area fill.
function RevenueChart({ actual, forecast }) {
  const W = 720, H = 200, pad = { l: 44, r: 12, t: 14, b: 22 };
  const all = [...actual.map((d) => d.revenue), ...forecast.map((d) => d.revenue)];
  const max = Math.max(1, ...all);
  const n = all.length;
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const x = (i) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * iw);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const aPts = actual.map((d, i) => [x(i), y(d.revenue)]);
  const fStart = actual.length - 1;
  const fPts = forecast.map((d, i) => [x(fStart + 1 + i), y(d.revenue)]);
  const line = (pts) => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const areaPath = aPts.length
    ? `${line(aPts)} L ${aPts[aPts.length - 1][0].toFixed(1)} ${(pad.t + ih).toFixed(1)} L ${aPts[0][0].toFixed(1)} ${(pad.t + ih).toFixed(1)} Z`
    : "";
  const bridge = aPts.length && fPts.length ? [aPts[aPts.length - 1], ...fPts] : fPts;
  const gy = [0, 0.5, 1].map((f) => pad.t + ih - f * ih);
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 460, display: "block" }}>
        <defs>
          <linearGradient id="revfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--p2)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--p2)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {gy.map((gyy, i) => (
          <g key={i}>
            <line x1={pad.l} y1={gyy} x2={W - pad.r} y2={gyy} stroke="var(--line)" strokeWidth="1" opacity="0.5" />
            <text x={pad.l - 6} y={gyy + 3} textAnchor="end" fontSize="10" fill="var(--txt3)">{compact(max * (1 - i * 0.5))}</text>
          </g>
        ))}
        {areaPath && <path d={areaPath} fill="url(#revfill)" />}
        {aPts.length > 1 && <path d={line(aPts)} fill="none" stroke="var(--p2)" strokeWidth="2.5" strokeLinejoin="round" />}
        {bridge.length > 1 && <path d={line(bridge)} fill="none" stroke="var(--p2)" strokeWidth="2.2" strokeDasharray="5 4" opacity="0.75" />}
        {fPts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2.6" fill="var(--p2)" opacity="0.8" />)}
      </svg>
    </div>
  );
}

function UsersChart({ series }) {
  const W = 720, H = 130, pad = { l: 30, r: 8, t: 8, b: 18 };
  const max = Math.max(1, ...series.map((d) => d.new_users));
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const bw = iw / series.length;
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 460, display: "block" }}>
        {series.map((d, i) => {
          const h = (d.new_users / max) * ih;
          return <rect key={i} x={pad.l + i * bw + 1} y={pad.t + ih - h} width={Math.max(1, bw - 2)} height={h}
            rx="2" fill="var(--p2)" opacity={0.35 + 0.65 * (d.new_users / max)} />;
        })}
        <text x={pad.l - 4} y={pad.t + 8} textAnchor="end" fontSize="10" fill="var(--txt3)">{max}</text>
      </svg>
    </div>
  );
}

export default function Analytics() {
  const [a, setA] = useState(null);
  useEffect(() => { api.get("/api/analytics").then(setA).catch(() => setA({ error: true })); }, []);
  if (!a) return <Card title="📈 آنالیتیکس"><div className="muted tiny">در حال محاسبه…</div></Card>;
  if (a.error) return null;
  const t = a.totals || {};
  const up = (t.momentum_pct || 0) >= 0;

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid stat-grid">
        <Stat icon="👥" value={fmt(t.total_users)} label="کل کاربران" grad="linear-gradient(135deg,#22d3ee,#38bdf8)"
          foot={`۳۰ روز اخیر: +${fmt(t.new_users_30d)}`} />
        <Stat icon="🧬" value={fmt(t.active_subs)} label="ساب‌های فعال" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="💰" value={compact(t.revenue_30d)} label="درآمد ۳۰ روز (تومان)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)"
          foot={`میانگین روزانه: ${compact(t.avg_daily_revenue)}`} />
        <Stat icon={up ? "📈" : "📉"} value={`${up ? "+" : ""}${t.momentum_pct}%`} label="روند ۷ روزه"
          grad={up ? "linear-gradient(135deg,#34d399,#10b981)" : "linear-gradient(135deg,#fb7185,#f43f5e)"}
          foot="نسبت به هفته قبل" />
      </div>

      <Card title="📈 روند درآمد و پیش‌بینی هوشمند"
        sub="خط پیوسته: ۳۰ روز گذشته · خط‌چین: پیش‌بینی ۷ روز آینده">
        <RevenueChart actual={a.revenue || []} forecast={a.forecast || []} />
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          <div style={{ background: "rgba(124,111,255,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="muted tiny">پیش‌بینی درآمد ۷ روز آینده</div>
            <div style={{ fontWeight: 800, fontSize: "1.25rem", color: "var(--p2)" }}>{fmt(t.forecast_next7)} <span className="muted tiny">تومان</span></div>
          </div>
          <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="muted tiny">پیش‌بینی درآمد ۳۰ روز آینده</div>
            <div style={{ fontWeight: 800, fontSize: "1.25rem", color: "var(--green,#34d399)" }}>{fmt(t.forecast_next30)} <span className="muted tiny">تومان</span></div>
          </div>
        </div>
        <p className="muted tiny" style={{ margin: "10px 0 0" }}>
          پیش‌بینی با یک مدل رگرسیون خطی روی داده‌های ۳۰ روز اخیر محاسبه می‌شود (روی همین سرور، بدون هزینه). یک تخمین است، نه تضمین.
        </p>
      </Card>

      <Card title="👥 کاربران جدید (۳۰ روز)">
        <UsersChart series={a.users || []} />
      </Card>
    </div>
  );
}
