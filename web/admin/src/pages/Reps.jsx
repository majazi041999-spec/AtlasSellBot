import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Stat, Loading, Empty } from "../components/ui.jsx";

export default function Reps({ go }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/api/reps").then(setD).catch(() => setD({ reps: [] })); }, []);
  if (!d) return <Loading />;
  const reps = d.reps || [];
  const k = d.kpi || {};
  const approved = reps.filter((r) => r.is_wholesale);
  const pending = reps.filter((r) => !r.is_wholesale && r.wholesale_request_pending);

  const Row = (r) => (
    <div key={r.id} className="between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: "10px 13px", gap: 10, flexWrap: "wrap", cursor: "pointer" }} onClick={() => go(`/users/${r.id}`)}>
      <div style={{ minWidth: 0 }}>
        <b>{r.full_name || "—"}</b> {r.rep_brand_name ? <span className="badge b-blue">🏷️ {r.rep_brand_name}</span> : null}
        <div className="muted tiny">{r.username ? `@${r.username} · ` : ""}<span className="mono">{r.telegram_id}</span></div>
        {r.is_wholesale && (
          <div className="muted tiny" style={{ marginTop: 3 }}>
            💸 خرید کل: {fmt(r.fin.total_spent)} · 📅 این ماه: {fmt(r.fin.month_spent)} · 🔑 فعال: {r.fin.active_services}/{r.fin.total_services}
          </div>
        )}
      </div>
      <div style={{ textAlign: "end" }}>
        <b style={{ color: "var(--p2)" }}>{fmt(r.balance_toman)} ت</b>
        <div className="muted tiny">کیف پول</div>
      </div>
    </div>
  );

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="grid stat-grid">
        <Stat icon="🏢" value={fmt(k.count)} label="نماینده فعال" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
        <Stat icon="⏳" value={fmt(k.pending)} label="درخواست در انتظار" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
        <Stat icon="💰" value={fmt(k.total_spent)} label="مجموع خرید نمایندگان (ت)" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="🔑" value={fmt(k.active_services)} label="سرویس فعال نمایندگان" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
      </div>

      {pending.length > 0 && (
        <Card title="⏳ درخواست‌های نمایندگی" sub={`${pending.length} در انتظار — روی هرکدام بزن تا تایید/رد کنی`}>
          <div className="grid" style={{ gap: 8 }}>{pending.map(Row)}</div>
        </Card>
      )}

      <Card title="🏢 نمایندگان" sub="بر اساس بیشترین خرید — روی هرکدام بزن برای جزئیات و آمار کامل">
        {!approved.length ? <Empty emoji="🏢">هنوز نماینده‌ای نیست</Empty> : (
          <div className="grid" style={{ gap: 8 }}>{approved.map(Row)}</div>
        )}
      </Card>
    </div>
  );
}
