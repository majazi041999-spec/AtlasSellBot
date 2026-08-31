import React, { useEffect, useState } from "react";
import { api, fmt, BASE } from "../api.js";
import { Stat, Card, Loading, Empty, toast, timeAgo } from "../components/ui.jsx";
import Analytics from "./Analytics.jsx";

/** Live connected users, read from each x-ui panel.
 *
 *  A server whose panel did not answer reports `online: null`. That is NOT
 *  zero — showing it as zero would turn "the panel is unreachable" into
 *  "nobody is connected", which reads as a quiet business collapse. Unknown
 *  servers are rendered as «؟» and counted separately, and the headline number
 *  says how many panels it actually covers.
 */
function OnlineNow({ data, onRefresh }) {
  const o = data || {};
  const servers = o.servers || [];
  const partial = o.servers_known < o.servers_total;
  const ageMin = o.checked_at ? Math.floor((Date.now() - o.checked_at) / 60000) : null;
  const max = Math.max(1, ...servers.map((s) => s.online || 0));

  return (
    <Card
      title="🟢 آنلاین‌های همین لحظه"
      sub={
        o.servers_total
          ? (partial
              ? `${o.servers_known} پنل از ${o.servers_total} پاسخ داد`
              : `روی ${o.servers_total} سرور`)
          : "سروری تنظیم نشده"
      }
      right={<button className="btn xs" onClick={onRefresh}>↻ تازه‌سازی</button>}
    >
      {!servers.length ? (
        <Empty emoji="🖥">هنوز از سرورها آماری نگرفته‌ایم.</Empty>
      ) : (
        <>
          <div className="row" style={{ gap: 12, alignItems: "baseline", marginBottom: 14, flexWrap: "wrap" }}>
            <span style={{ fontSize: "2.4rem", fontWeight: 800, lineHeight: 1 }}>{fmt(o.total)}</span>
            <span className="muted">کاربر متصل</span>
            {partial && (
              <span className="badge b-yellow">
                {o.servers_total - o.servers_known} پنل پاسخ نداد — عدد ناقص است
              </span>
            )}
            {ageMin !== null && ageMin > 10 && (
              <span className="badge b-gray">آخرین بررسی: {ageMin} دقیقه پیش</span>
            )}
          </div>

          <div className="grid" style={{ gap: 8 }}>
            {servers.map((s) => {
              const unknown = s.online === null || s.online === undefined;
              return (
                <div key={s.id} className="row" style={{ gap: 10 }}>
                  <span style={{ minWidth: 130, flexShrink: 0 }}>{s.name}</span>
                  <div style={{ flex: 1, height: 8, borderRadius: 6, background: "rgba(255,255,255,.06)", overflow: "hidden" }}>
                    {!unknown && (
                      <div style={{
                        width: `${Math.round((s.online / max) * 100)}%`, height: "100%",
                        background: "linear-gradient(90deg,#34d399,#10b981)", borderRadius: 6,
                      }} />
                    )}
                  </div>
                  {unknown ? (
                    <span className="badge b-yellow" style={{ minWidth: 74, justifyContent: "center" }}
                          title={s.stale ? "آخرین پاسخ پنل قدیمی شده است" : "پنل به درخواست پاسخ نداد"}>
                      ؟ نامعلوم
                    </span>
                  ) : (
                    <b className="mono" style={{ minWidth: 74, textAlign: "left", color: "var(--txt1)" }}>{fmt(s.online)}</b>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
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

      <OnlineNow data={d.online} onRefresh={load} />

      <Analytics />

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
