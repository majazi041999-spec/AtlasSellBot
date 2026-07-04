import React, { useEffect, useState } from "react";
import { api, fmt, BASE } from "../api.js";
import { Stat, Card, Loading, Empty, toast } from "../components/ui.jsx";

function timeAgo(s) {
  if (!s) return "";
  const t = new Date((s || "").replace(" ", "T")).getTime();
  if (!t) return s;
  const diff = Math.max(0, Date.now() - t);
  const m = Math.floor(diff / 60000);
  if (m < 1) return "همین حالا";
  if (m < 60) return `${m} دقیقه پیش`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ساعت پیش`;
  return `${Math.floor(h / 24)} روز پیش`;
}

export default function Dashboard({ onBadges, go }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(0);

  const load = () => api.get("/api/dashboard").then((r) => {
    setD(r);
    onBadges?.({ pending_orders: r.pending_total });
  }).catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);

  const act = async (oid, kind) => {
    setBusy(oid);
    try {
      await api.post(`/api/orders/${oid}/${kind}`);
      toast(kind === "approve" ? "سفارش تایید و فعال شد ✅" : "سفارش رد شد");
      load();
    } catch (e) {
      toast(kind === "approve" ? "تایید/ساخت ناموفق بود" : "خطا", "error");
    } finally { setBusy(0); }
  };

  if (!d) return <Loading />;
  const s = d.stats || {};
  const rep = d.report || {};

  return (
    <div className="screen grid" style={{ gap: 22 }}>
      <div className="grid stat-grid">
        <Stat icon="💰" value={fmt(s.total_revenue)} label="درآمد کل (تومان)" grad="linear-gradient(135deg,#7c6fff,#a78bfa)"
              foot={`امروز: ${fmt(rep.sales_amount)} ت`} />
        <Stat icon="👥" value={fmt(s.total_users)} label="کاربران" grad="linear-gradient(135deg,#22d3ee,#38bdf8)"
              foot={`جدید امروز: ${fmt(rep.new_users)}`} />
        <Stat icon="🔑" value={fmt(s.active_configs)} label="سرویس‌های فعال" grad="linear-gradient(135deg,#34d399,#10b981)" />
        <Stat icon="🧾" value={fmt(s.pending_orders)} label="سفارش در انتظار" grad="linear-gradient(135deg,#fb7185,#f43f5e)"
              foot={s.pending_orders > 0 ? "نیازمند بررسی" : "تسویه‌شده"} />
        <Stat icon="✅" value={fmt(s.today_orders)} label="فروش امروز" grad="linear-gradient(135deg,#fbbf24,#f59e0b)"
              foot={`تمدید: ${fmt(rep.renewals)}`} />
        <Stat icon="🖥" value={`${fmt(s.active_servers)}/${fmt(s.total_servers)}`} label="سرورهای فعال" grad="linear-gradient(135deg,#818cf8,#6366f1)" />
        <Stat icon="📦" value={fmt(s.total_orders)} label="کل فروش موفق" grad="linear-gradient(135deg,#2dd4bf,#14b8a6)" />
        <Stat icon="💳" value={fmt(rep.wallet_topup_amount)} label="شارژ کیف پول امروز" grad="linear-gradient(135deg,#c084fc,#a855f7)" />
      </div>

      <Card title="سفارش‌های در انتظار تایید" sub={rep.jalali_display}
            right={<button className="btn sm" onClick={() => go("/orders")}>همه سفارش‌ها ›</button>}>
        {!(d.pending || []).length ? (
          <Empty emoji="✅">سفارش در انتظاری نیست</Empty>
        ) : (
          <div className="grid" style={{ gap: 10 }}>
            {d.pending.map((o) => (
              <div key={o.id} className="between" style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--bd)", borderRadius: 14, padding: "12px 14px", gap: 12, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <b>#{o.id}</b>
                    <span>{o.pkg_name || "—"}</span>
                    {o.is_renew && <span className="badge b-purple">تمدید</span>}
                  </div>
                  <div className="muted tiny" style={{ marginTop: 3 }}>
                    {o.full_name || "—"} {o.username ? `· @${o.username}` : ""} · {timeAgo(o.created_at)}
                  </div>
                </div>
                <div className="row" style={{ gap: 8 }}>
                  <b style={{ color: "var(--p2)" }}>{fmt(o.price)} ت</b>
                  <button className="btn xs success" disabled={busy === o.id} onClick={() => act(o.id, "approve")}>تایید</button>
                  <button className="btn xs danger" disabled={busy === o.id} onClick={() => act(o.id, "reject")}>رد</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
