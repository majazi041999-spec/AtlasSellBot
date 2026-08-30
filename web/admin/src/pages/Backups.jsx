import React, { useEffect, useRef, useState } from "react";
import { BASE, api } from "../api.js";
import { Card, Loading, Empty, toast, timeAgo } from "../components/ui.jsx";

const mb = (b) => (Number(b || 0) / (1024 * 1024)).toFixed(2) + " MB";

export default function Backups() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");
  const [restore, setRestore] = useState({ env: false, ssl: false });
  const file = useRef();

  const load = () => api.get("/api/backups").then(setData).catch(() => setData({ backups: [], settings: {} }));
  useEffect(() => { load(); }, []);

  // Downloads are browser navigations, not fetches — the response is a file
  // stream with a Content-Disposition, which fetch() would only buffer.
  const dl = (path) => { window.location.href = `${BASE}${path}`; };

  const saveSchedule = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    setBusy("schedule");
    try {
      await api.form("/backups/servers/settings", {
        server_backup_enabled: f.get("enabled") ? "1" : "0",
        server_backup_interval_hours: f.get("hours") || "6",
      });
      toast("زمان‌بندی ذخیره شد ✅");
      load();
    } catch (err) { toast(err.message || "خطا", "error"); } finally { setBusy(""); }
  };

  const sendNow = async () => {
    setBusy("send");
    try {
      const r = await api.post("/backups/servers/send");
      toast(`بکاپ برای ${r.sent} ادمین ارسال شد ✅`);
    } catch (err) { toast(err.message || "ارسال ناموفق بود", "error"); } finally { setBusy(""); }
  };

  const doRestore = async () => {
    const f = file.current?.files?.[0];
    if (!f) { toast("اول فایل بکاپ را انتخاب کن", "error"); return; }
    if (!confirm(
      "دیتابیس فعلی با محتویات این فایل جایگزین می‌شود.\n\n" +
      "قبل از جایگزینی، از وضعیت فعلی یک نسخه‌ی پشتیبان گرفته می‌شود.\nادامه می‌دهی؟"
    )) return;
    setBusy("restore");
    try {
      const r = await api.form("/backups/restore", {
        backup_file: f,
        restore_env: restore.env ? "1" : "0",
        restore_ssl: restore.ssl ? "1" : "0",
      });
      toast("بازیابی انجام شد ✅ پنل را رفرش کن");
      if (r.pre_restore_backup) {
        alert(
          "بازیابی انجام شد.\n\n" +
          `نسخه‌ی پشتیبان وضعیت قبلی با این نام ذخیره شد:\n${r.pre_restore_backup}\n\n` +
          "اگر نتیجه درست نبود، همان را از لیست «نسخه‌های اضطراری» دانلود کن."
        );
      }
      load();
    } catch (err) { toast(err.message || "بازیابی ناموفق بود", "error"); } finally { setBusy(""); }
  };

  if (!data) return <Loading />;
  const s = data.settings || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="💾 دانلود نسخه پشتیبان" sub="فایل zip شامل دیتابیس، فایل .env و گواهی‌های SSL">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn primary" onClick={() => dl("/backups/download")}>⬇️ بکاپ کامل سیستم</button>
          <button className="btn" onClick={() => dl("/backups/servers/download")}>🗄 بکاپ پنل‌های x-ui</button>
        </div>
        <p className="muted tiny" style={{ marginTop: 10 }}>
          «بکاپ کامل سیستم» همه‌چیزِ این نصب است. «بکاپ پنل‌های x-ui» فقط اینباندها و کلاینت‌های سرورهاست.
        </p>
      </Card>

      <Card title="⏱ بکاپ خودکار پنل‌ها" sub="ارسال دوره‌ای به ادمین‌های کل در تلگرام">
        <form onSubmit={saveSchedule} className="grid" style={{ gap: 12 }}>
          <div className="row between" style={{ gap: 12, flexWrap: "wrap" }}>
            <label className="row" style={{ gap: 8, cursor: "pointer" }}>
              <input type="checkbox" name="enabled" defaultChecked={String(s.server_backup_enabled) === "1"} />
              <span>ارسال خودکار فعال باشد</span>
            </label>
            <div className="field" style={{ margin: 0 }}>
              <label>هر چند ساعت یک‌بار</label>
              <input className="inp" name="hours" type="number" min="1" max="168" dir="ltr"
                     defaultValue={s.server_backup_interval_hours || 6} style={{ width: 120 }} />
            </div>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button className="btn primary" disabled={busy === "schedule"}>{busy === "schedule" ? "…" : "💾 ذخیره"}</button>
            <button type="button" className="btn" disabled={busy === "send"} onClick={sendNow}>
              {busy === "send" ? "…" : "📤 همین حالا بفرست"}
            </button>
          </div>
        </form>
        <p className="muted tiny" style={{ marginTop: 10 }}>
          بکاپ فقط برای ادمین‌های کل ارسال می‌شود — رمز پنل‌ها داخلش هست.
        </p>
      </Card>

      <Card title="♻️ بازیابی از فایل" sub="جایگزینی دیتابیس فعلی با یک نسخه پشتیبان">
        <div style={{ background: "rgba(251,113,133,.1)", border: "1px solid rgba(251,113,133,.35)",
                      borderRadius: 12, padding: 12, marginBottom: 12 }}>
          <b>⚠️ این کار دیتابیس فعلی را جایگزین می‌کند.</b>
          <p className="muted tiny" style={{ margin: "6px 0 0" }}>
            درست قبل از جایگزینی، از وضعیت فعلی یک نسخه‌ی پشتیبان گرفته و در لیست پایین ذخیره می‌شود؛
            پس اگر اشتباه شد راه برگشت داری.
          </p>
        </div>
        <div className="grid" style={{ gap: 10 }}>
          <div className="field"><label>فایل بکاپ (zip یا db)</label>
            <input className="inp" type="file" ref={file} accept=".zip,.db,.sqlite,.sqlite3" /></div>
          <label className="row" style={{ gap: 8, cursor: "pointer" }}>
            <input type="checkbox" checked={restore.env}
                   onChange={(e) => setRestore((v) => ({ ...v, env: e.target.checked }))} />
            <span>فایل <code>.env</code> هم بازیابی شود <span className="muted tiny">(توکن ربات و رمز پنل عوض می‌شود)</span></span>
          </label>
          <label className="row" style={{ gap: 8, cursor: "pointer" }}>
            <input type="checkbox" checked={restore.ssl}
                   onChange={(e) => setRestore((v) => ({ ...v, ssl: e.target.checked }))} />
            <span>گواهی‌های SSL و تنظیمات nginx هم بازیابی شوند</span>
          </label>
          <button className="btn danger" disabled={busy === "restore"} onClick={doRestore}>
            {busy === "restore" ? "در حال بازیابی…" : "♻️ بازیابی کن"}
          </button>
        </div>
      </Card>

      <Card title="🗂 نسخه‌های اضطراری روی سرور" sub="پشتیبان‌هایی که پیش از هر بازیابی خودکار ساخته شده‌اند">
        {!(data.backups || []).length ? <Empty emoji="🗂">هنوز نسخه‌ی اضطراری‌ای ساخته نشده است.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>نام فایل</th><th>حجم</th><th>ساخته شده</th><th></th></tr></thead>
              <tbody>
                {data.backups.map((b) => (
                  <tr key={b.name}>
                    <td className="mono" style={{ direction: "ltr", textAlign: "left" }}>{b.name}</td>
                    <td>{mb(b.size)}</td>
                    <td className="muted tiny">{timeAgo(b.created)}</td>
                    <td><button className="btn xs" onClick={() => dl(`/backups/emergency/${encodeURIComponent(b.name)}`)}>⬇️ دانلود</button></td>
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
