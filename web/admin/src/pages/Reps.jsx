import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Stat, Loading, Empty, Toolbar, Search, Select, usePref } from "../components/ui.jsx";

/* The whole rep list arrives in one payload, so sorting stays client-side. */
const SORTS = [
  { k: "spent_desc", label: "💰 بیشترین خرید" },
  { k: "month_desc", label: "📅 بیشترین خرید این ماه" },
  { k: "services_desc", label: "🔑 بیشترین سرویس فعال" },
  { k: "balance_desc", label: "💳 بیشترین موجودی" },
  { k: "balance_asc", label: "💳 کمترین موجودی" },
  { k: "name_az", label: "🔤 نام (الف → ی)" },
  { k: "newest", label: "🕒 جدیدترین نماینده" },
  { k: "oldest", label: "🕒 قدیمی‌ترین نماینده" },
];

const repName = (r) => String(r.full_name || r.username || "").trim();

function sortReps(rows, k) {
  // Persian alphabetical order — a plain `<` puts پ چ ژ ک گ ی after every other letter.
  if (k === "name_az") return [...rows].sort((a, b) => repName(a).localeCompare(repName(b), "fa"));
  const keys = {
    spent_desc: [(r) => r.fin?.total_spent || 0, true],
    month_desc: [(r) => r.fin?.month_spent || 0, true],
    services_desc: [(r) => r.fin?.active_services || 0, true],
    balance_desc: [(r) => r.balance_toman || 0, true],
    balance_asc: [(r) => r.balance_toman || 0, false],
    newest: [(r) => r.id, true],
    oldest: [(r) => r.id, false],
  };
  const [key, desc] = keys[k] || keys.spent_desc;
  return [...rows].sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka < kb) return desc ? 1 : -1;
    if (ka > kb) return desc ? -1 : 1;
    return (b.id || 0) - (a.id || 0);
  });
}

export default function Reps({ go }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = usePref("reps.sort", "spent_desc");
  useEffect(() => { api.get("/api/reps").then(setD).catch(() => setD({ reps: [] })); }, []);
  if (!d) return <Loading />;
  const reps = d.reps || [];
  const k = d.kpi || {};
  const needle = q.trim().toLowerCase();
  const match = (r) => !needle || [r.full_name, r.username, r.rep_brand_name, r.telegram_id]
    .filter(Boolean).join(" ").toLowerCase().includes(needle);
  const approved = sortReps(reps.filter((r) => r.is_wholesale && match(r)), sort);
  const pending = reps.filter((r) => !r.is_wholesale && r.wholesale_request_pending && match(r));

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

      <Toolbar right={`${fmt(approved.length)} نماینده`}>
        <Search value={q} onChange={setQ} placeholder="نام، یوزرنیم، برند یا آیدی تلگرام…" />
        <Select label="مرتب‌سازی" value={sort} options={SORTS} onChange={setSort} />
      </Toolbar>

      {pending.length > 0 && (
        <Card title="⏳ درخواست‌های نمایندگی" sub={`${pending.length} در انتظار — روی هرکدام بزن تا تایید/رد کنی`}>
          <div className="grid" style={{ gap: 8 }}>{pending.map(Row)}</div>
        </Card>
      )}

      <Card title="🏢 نمایندگان" sub="روی هرکدام بزن برای جزئیات و آمار کامل">
        {!approved.length ? (
          <Empty emoji="🏢">{q ? "نماینده‌ای با این جستجو پیدا نشد" : "هنوز نماینده‌ای نیست"}</Empty>
        ) : (
          <div className="grid" style={{ gap: 8 }}>{approved.map(Row)}</div>
        )}
      </Card>
    </div>
  );
}
