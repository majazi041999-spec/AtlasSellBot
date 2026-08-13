import React, { useEffect, useMemo, useState } from "react";
import { api, fmt, BASE } from "../api.js";
import { Card, Chips, Empty, Spinner, Stat } from "./ui.jsx";
import JalaliDateField from "./JalaliDateField.jsx";
import * as J from "../jalali.js";
import "./rep-report.css";

/* Date-filtered purchase report for one representative (نماینده).

   The server owns the range logic: we send either `preset` or `from`/`to`
   (Jalali `YYYY/MM/DD`) and render what comes back. Every date string in `rows`
   is already Jalali and formatted — it is printed verbatim, never re-parsed. */

// Only used for the very first paint; the response's `presets` replaces it.
// Mirrors core/rep_report.PRESETS — keep the keys in sync if that dict changes.
const FALLBACK_PRESETS = [
  { key: "week", label: "۷ روز اخیر" },
  { key: "month", label: "۱ ماه اخیر" },
  { key: "3months", label: "۳ ماه اخیر" },
  { key: "6months", label: "۶ ماه اخیر" },
  { key: "year", label: "۱ سال اخیر" },
  { key: "all", label: "همه" },
];
const CUSTOM = "__custom";

const num = (n) => Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 2 });
const statusClass = (s) => (s === "فعال" ? "b-green" : s === "منقضی" ? "b-red" : "b-gray");

export default function RepPurchases({ uid }) {
  const [presets, setPresets] = useState(FALLBACK_PRESETS);
  const [preset, setPreset] = useState("month");
  const [custom, setCustom] = useState(false);
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const fromKey = from ? J.format(from) : "";
  const toKey = to ? J.format(to) : "";

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    // from/to override the preset server-side; only send them once one is set,
    // otherwise "custom" with empty fields would silently mean "everything".
    if (custom && (fromKey || toKey)) {
      if (fromKey) p.set("from", fromKey);
      if (toKey) p.set("to", toKey);
    } else {
      p.set("preset", preset);
    }
    return p.toString();
  }, [custom, preset, fromKey, toKey]);

  useEffect(() => {
    let dead = false;
    setLoading(true);
    // Small debounce so typing a date doesn't fire a request per keystroke.
    const t = setTimeout(() => {
      api.get(`/api/reps/${uid}/purchases?${qs}`)
        .then((r) => { if (!dead) { setData(r); setErr(""); } })
        .catch((e) => { if (!dead) setErr(e.message || "خطا در دریافت گزارش"); })
        .finally(() => { if (!dead) setLoading(false); });
    }, 250);
    return () => { dead = true; clearTimeout(t); };
  }, [uid, qs]);

  useEffect(() => {
    if (data && Array.isArray(data.presets) && data.presets.length) setPresets(data.presets);
  }, [data]);

  const pickPeriod = (k) => {
    if (k !== CUSTOM) { setCustom(false); setPreset(k); return; }
    if (!custom) {
      // Seed the custom fields with the window already on screen so switching
      // modes doesn't jump to an unrelated range.
      const r = (data && data.range) || {};
      setFrom(J.parse(r.from_jalali || "") || J.addMonths(J.today(), -1));
      setTo(J.parse(r.to_jalali || "") || J.today());
    }
    setCustom(true);
  };

  const rows = (data && data.rows) || [];
  const s = (data && data.summary) || {};
  const range = (data && data.range) || {};
  const unlimited = Number(s.unlimited_count || 0);
  const xlsx = `${BASE}/api/reps/${uid}/purchases.xlsx?${qs}`;

  // An unlimited plan has no gigabytes to add up — showing it as 0 GB would be a
  // lie, so it is counted separately and never folded into the number.
  const gbValue = (Number(s.total_gb || 0) > 0 || !unlimited)
    ? <span>{num(s.total_gb)} GB{unlimited ? <em className="rep-unl">+{fmt(unlimited)} نامحدود</em> : null}</span>
    : <span>{fmt(unlimited)} نامحدود</span>;

  return (
    <Card
      title="🧾 گزارش خرید نماینده"
      right={<a className="btn sm success" href={xlsx} target="_blank" rel="noopener noreferrer">📥 دریافت اکسل</a>}
    >
      <Chips
        options={[...presets.map((p) => ({ k: p.key, label: p.label })), { k: CUSTOM, label: "📅 بازه دلخواه" }]}
        value={custom ? CUSTOM : preset}
        onChange={pickPeriod}
      />

      {custom && (
        <div className="rep-range">
          <JalaliDateField label="از تاریخ" value={from} onChange={setFrom} />
          <JalaliDateField label="تا تاریخ" value={to} onChange={setTo} />
          <button className="btn sm rep-range-clear" onClick={() => { setFrom(null); setTo(null); }}>پاک کردن</button>
        </div>
      )}

      {data ? (
        <div className="rep-note rep-window">
          📆 بازه: از <b>{range.from_label}</b> تا <b>{range.to_label}</b>
        </div>
      ) : null}

      {!data && loading ? <div className="rep-loading"><Spinner /></div> : null}
      {err && !loading ? <Empty emoji="⚠️">{err}</Empty> : null}

      {data && (
        <div className={"rep-body" + (loading ? " busy" : "")}>
          <div className="grid stat-grid rep-stats">
            <Stat icon="🧬" value={fmt(s.services)} label="سرویس خریداری‌شده" grad="linear-gradient(135deg,#7c6fff,#a78bfa)" />
            <Stat icon="🔄" value={fmt(s.renewals)} label="تمدید" grad="linear-gradient(135deg,#22d3ee,#38bdf8)" />
            <Stat icon="📦" value={gbValue} label="مجموع حجم" grad="linear-gradient(135deg,#34d399,#10b981)" />
            <Stat icon="✅" value={fmt(s.orders)} label="سفارش تاییدشده" grad="linear-gradient(135deg,#fbbf24,#f59e0b)" />
            <Stat icon="💰" value={<span>{fmt(s.total_spent)}<em className="rep-cur">تومان</em></span>} label="مجموع خرید" grad="linear-gradient(135deg,#f43f5e,#fb7185)" />
          </div>

          {Number(s.legacy_configs || 0) > 0 && (
            <div className="rep-note">
              ℹ️ {fmt(s.legacy_configs)} کانفیگ تکی قدیمی هم برای این نماینده ثبت شده که در این جدول نمی‌آید.
            </div>
          )}

          {!rows.length ? (
            <Empty emoji="🧾">در این بازه خریدی ثبت نشده است</Empty>
          ) : (
            <div className="table-wrap rep-tbl-wrap">
              <table className="rep-tbl">
                <thead>
                  <tr>
                    <th>ردیف</th><th>نوع</th><th>نام انتخابی سرویس</th><th>حجم</th><th>مدت</th>
                    <th>تاریخ خرید</th><th>تاریخ شروع</th><th>تاریخ انقضا</th><th>مبلغ</th><th>وضعیت</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.kind}-${r.profile_id}-${r.order_id}-${r.row}`}>
                      <td className="muted">{r.row}</td>
                      <td><span className={"badge " + (r.kind === "renewal" ? "b-yellow" : "b-blue")}>{r.kind_label}</span></td>
                      <td className="rep-name">{r.name}</td>
                      <td>{r.is_unlimited ? "نامحدود" : `${r.traffic_label} GB`}</td>
                      <td>{r.duration_days ? `${r.duration_days} روز` : "—"}</td>
                      {/* Already Jalali & formatted by the server — printed as-is.
                          <bdi> isolates them: "1405/05/20 12:00" is two numeric
                          runs around a space, which an RTL context would other-
                          wise reorder to "12:00 1405/05/20". */}
                      <td className="muted tiny"><bdi>{r.purchased_at}</bdi></td>
                      <td className="muted tiny"><bdi>{r.started_at}</bdi></td>
                      <td className="muted tiny"><bdi>{r.expires_at}</bdi></td>
                      <td>{fmt(r.price)}</td>
                      <td><span className={"badge " + statusClass(r.status)}>{r.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="rep-note rep-foot">
            {rows.length ? `${fmt(rows.length)} ردیف` : ""}{rows.length && data.generated_at ? " · " : ""}
            {data.generated_at ? <>تهیه گزارش: <bdi>{data.generated_at}</bdi></> : ""}
          </div>
        </div>
      )}
    </Card>
  );
}
