import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Stat } from "../components/ui.jsx";

export default function Reports() {
  const [data, setData] = useState(null);

  // Loading this page also takes today's snapshot server-side, which is what
  // keeps the top row live instead of showing yesterday's stored numbers.
  useEffect(() => {
    api.get("/api/reports").then(setData).catch(() => setData({ today: null, reports: [] }));
  }, []);

  if (!data) return <Loading />;
  const t = data.today || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title={`📅 امروز — ${t.jalali_display || t.jalali_date || ""}`}
            sub="همین گزارش هر شب برای ادمین‌ها در تلگرام ارسال می‌شود">
        <div className="grid stat-grid">
          <Stat icon="💰" value={fmt(t.sales_amount)} label="فروش امروز (تومان)"
                grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
          <Stat icon="🧾" value={fmt(t.orders_approved)} label="سفارش تاییدشده"
                grad="linear-gradient(135deg,#34d399,#10b981)" foot={`تمدید: ${fmt(t.renewals)}`} />
          <Stat icon="👥" value={fmt(t.new_users)} label="کاربر جدید"
                grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
          <Stat icon="💳" value={fmt(t.wallet_topup_amount)} label="شارژ کیف پول (تومان)"
                grad="linear-gradient(135deg,#fbbf24,#f59e0b)" foot={`${fmt(t.wallet_topups)} شارژ`} />
          <Stat icon="⏳" value={fmt(t.pending_orders)} label="سفارش در انتظار"
                grad="linear-gradient(135deg,#fb7185,#f43f5e)" />
        </div>
      </Card>

      <Card title="📊 روزهای گذشته" sub="۶۰ روز اخیر">
        {!(data.reports || []).length ? <Empty emoji="📊">هنوز گزارشی ثبت نشده است.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>تاریخ</th><th>فروش</th><th>سفارش</th><th>تمدید</th>
                <th>کاربر جدید</th><th>شارژ کیف پول</th><th>ارسال شد</th>
              </tr></thead>
              <tbody>
                {data.reports.map((r) => (
                  <tr key={r.jalali_date || r.gregorian_date}>
                    <td className="mono">{r.jalali_date || r.gregorian_date}</td>
                    <td className="mono">{fmt(r.sales_amount)}</td>
                    <td>{fmt(r.orders_approved)}</td>
                    <td>{fmt(r.renewals)}</td>
                    <td>{fmt(r.new_users)}</td>
                    <td className="mono">{fmt(r.wallet_topup_amount)}</td>
                    <td>
                      {r.sent_to_admins
                        ? <span className="badge b-green">✓</span>
                        : <span className="badge b-gray">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
