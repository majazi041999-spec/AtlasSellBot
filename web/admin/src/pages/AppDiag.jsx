import React, { useEffect, useState } from "react";
import { api, fmtFa, BASE } from "../api.js";
import { Card, Loading, Stat, Empty, toast } from "../components/ui.jsx";

/**
 * Connection diagnostics from the Android app.
 *
 * ## What this page is for
 *
 * One question: which server, on which carrier, with which transport, is
 * actually failing — and is it the server, the network, or the core. Everything
 * shown is aggregated from events the app records around a connection attempt.
 *
 * ## What it deliberately cannot show
 *
 * No destination, no hostname, no IP, no user. The app strips those on the
 * device before anything is sent, so they are not withheld here — they were
 * never collected. That is not a limitation to work around; it is the reason
 * this feature is safe to ship in a VPN used where using one carries risk.
 */

const DAYS = [1, 7, 30];

/** Fraction of probes that succeeded, as a percentage, or null when untested. */
function successRate(row) {
  const total = (row.reachable || 0) + (row.unreachable || 0);
  if (!total) return null;
  return Math.round(((row.reachable || 0) / total) * 100);
}

function RateBadge({ value }) {
  if (value === null) return <span style={{ opacity: 0.5 }}>—</span>;
  const colour = value >= 80 ? "#2bd98a" : value >= 50 ? "#ffb020" : "#ff5c6e";
  return <b style={{ color: colour }}>{fmtFa(value)}٪</b>;
}

function Table({ title, sub, rows, columns, empty = "هنوز داده‌ای نرسیده" }) {
  if (!rows || rows.length === 0) {
    return <Card title={title} sub={sub}><Empty>{empty}</Empty></Card>;
  }
  return (
    <Card title={title} sub={sub}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ opacity: 0.6, textAlign: "right" }}>
              {columns.map((c) => (
                <th key={c.key} style={{ padding: "6px 8px", fontWeight: 500, whiteSpace: "nowrap" }}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.key + i} style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
                {columns.map((c) => (
                  <td key={c.key} style={{ padding: "8px", whiteSpace: "nowrap" }} dir="auto">
                    {c.render ? c.render(r) : (r[c.key] ?? 0) === -1 ? "—" : fmtFa(r[c.key] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function AppDiag() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = (d = days) => {
    setData(null);
    api.get(`/api/client/diag/summary?days=${d}`)
      .then(setData)
      .catch((e) => toast(e.message || "خطا در خواندن گزارش‌ها", "error"));
  };
  useEffect(() => { load(days); /* eslint-disable-next-line */ }, [days]);

  const purge = async () => {
    if (!window.confirm("همهٔ گزارش‌های ذخیره‌شده پاک شوند؟ این کار برگشت‌پذیر نیست.")) return;
    setBusy(true);
    try {
      await api.post("/api/client/diag/purge");
      toast("پاک شد");
      load(days);
    } catch (e) {
      toast(e.message || "پاک نشد", "error");
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Loading />;

  return (
    <div className="grid" style={{ gap: 14 }}>
      <Card
        title="🩺 تشخیص مشکلات کاربران"
        sub="از رویدادهایی که اپ هنگام اتصال ثبت می‌کند. هیچ مقصد، دامنه، آی‌پی یا اطلاعات کاربری در این داده‌ها نیست."
        right={
          <div style={{ display: "flex", gap: 6 }}>
            {DAYS.map((d) => (
              <button
                key={d}
                className={"btn" + (days === d ? " primary" : "")}
                onClick={() => setDays(d)}
              >
                {fmtFa(d)} روز
              </button>
            ))}
          </div>
        }
      >
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 12 }}>
          <Stat icon="📊" value={fmtFa(data.events)} label="رویداد ثبت‌شده" />
          <Stat icon="📱" value={fmtFa(data.devices)} label="دستگاه گزارش‌دهنده" />
          <Stat icon="🗓" value={fmtFa(data.retentionDays)} label="روز نگهداری" foot="بعدش خودکار پاک می‌شود" />
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          {/* Plain links: these are authenticated GETs on the same origin, so the
              browser's own download handling is simpler and more reliable than
              fetching a blob and revoking it afterwards. */}
          <a className="btn primary" href={`${BASE}/api/client/diag/export?days=${days}&format=csv`}>
            ⬇️ دانلود CSV
          </a>
          <a className="btn" href={`${BASE}/api/client/diag/export?days=${days}&format=json`}>
            ⬇️ دانلود JSON
          </a>
          <button className="btn" disabled={busy} onClick={purge}>پاک کردن همه</button>
        </div>
      </Card>

      <Table
        title="🖥 سرورها"
        sub="نرخ موفقیت پینگ، میانگین تأخیر، و اینکه چند بار اتصال واقعاً برقرار یا ناموفق شده"
        rows={data.servers}
        columns={[
          { key: "key", label: "سرور", render: (r) => r.key },
          { key: "rate", label: "نرخ موفقیت", render: (r) => <RateBadge value={successRate(r)} /> },
          { key: "avg_ms", label: "میانگین پینگ", render: (r) => r.avg_ms ? `${fmtFa(r.avg_ms)} ms` : "—" },
          { key: "reachable", label: "پینگ موفق" },
          { key: "unreachable", label: "پینگ ناموفق" },
          { key: "connects", label: "اتصال موفق" },
          { key: "failures", label: "اتصال ناموفق" },
        ]}
      />

      <Table
        title="📶 اپراتورها"
        sub="اگر یک سرور فقط روی یک اپراتور خراب است، مشکل شبکه است نه سرور"
        rows={data.carriers}
        columns={[
          { key: "key", label: "اپراتور", render: (r) => r.key },
          { key: "installs", label: "دستگاه" },
          { key: "rate", label: "نرخ موفقیت", render: (r) => <RateBadge value={successRate(r)} /> },
          { key: "avg_ms", label: "میانگین پینگ", render: (r) => r.avg_ms ? `${fmtFa(r.avg_ms)} ms` : "—" },
        ]}
      />

      <Table
        title="🔀 ترنسپورت‌ها"
        sub="کدام ترکیب (ws+tls، tcp+reality و…) روی شبکهٔ کاربران بهتر رد می‌شود"
        rows={data.transports}
        columns={[
          { key: "key", label: "ترنسپورت", render: (r) => r.key },
          { key: "rate", label: "نرخ موفقیت", render: (r) => <RateBadge value={successRate(r)} /> },
          { key: "avg_ms", label: "میانگین پینگ", render: (r) => r.avg_ms ? `${fmtFa(r.avg_ms)} ms` : "—" },
          { key: "reachable", label: "موفق" },
          { key: "unreachable", label: "ناموفق" },
        ]}
      />

      <Table
        title="⚙️ پریست‌ها"
        sub="آیا پریست گیمینگ واقعاً سریع‌تر وصل می‌شود یا فقط قوانین مسیریابی را خراب می‌کند"
        rows={data.presets}
        columns={[
          { key: "key", label: "پریست", render: (r) => r.key },
          { key: "connects", label: "اتصال موفق" },
          { key: "failures", label: "ناموفق" },
          {
            key: "avg_connect_ms",
            label: "میانگین زمان اتصال",
            render: (r) => (r.avg_connect_ms > 0 ? `${fmtFa((r.avg_connect_ms / 1000).toFixed(1))} ثانیه` : "—"),
          },
          {
            key: "avg_peak_down",
            label: "اوج سرعت دانلود",
            render: (r) =>
              r.avg_peak_down > 0
                ? `${fmtFa((r.avg_peak_down / 125000).toFixed(1))} Mbps`
                : "—",
          },
        ]}
      />

      <Table
        title="❗ دلایل خطا"
        sub="متن خطا روی خود گوشی از هر دامنه، آی‌پی و شناسه‌ای پاک شده و بعد فرستاده شده"
        rows={data.reasons}
        columns={[
          { key: "key", label: "خطا", render: (r) => <span dir="ltr">{r.key}</span> },
          { key: "count", label: "دفعات" },
        ]}
      />

      <Table
        title="🌐 نوع شبکه"
        rows={data.networks}
        columns={[
          { key: "key", label: "شبکه", render: (r) => r.key },
          { key: "count", label: "رویداد" },
          { key: "failures", label: "خطا" },
        ]}
      />

      <div>
        <button className="btn" onClick={() => load(days)}>بازخوانی</button>
      </div>
    </div>
  );
}
