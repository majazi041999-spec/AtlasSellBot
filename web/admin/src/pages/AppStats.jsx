import React, { useEffect, useState } from "react";
import { api, fmtFa } from "../api.js";
import { Card, Loading, Stat, Empty, toast } from "../components/ui.jsx";

// ui.jsx's timeAgo parses "YYYY-MM-DD HH:MM:SS" strings; these columns are
// epoch seconds, which it would fail to parse and echo back as a raw number.
function agoEpoch(sec) {
  if (!sec) return "";
  const m = Math.floor(Math.max(0, Date.now() / 1000 - sec) / 60);
  if (m < 1) return "همین حالا";
  if (m < 60) return `${m} دقیقه پیش`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ساعت پیش`;
  return `${Math.floor(h / 24)} روز پیش`;
}

function untilEpoch(sec) {
  if (!sec) return "";
  const days = Math.ceil((sec - Date.now() / 1000) / 86400);
  return days <= 0 ? "منقضی شده" : `${days} روز دیگر`;
}

/**
 * Install analytics and push notifications for the Android app.
 *
 * ## Why there is no "uninstalls" number
 *
 * There cannot be one. Play Console reports uninstalls because Google owns the
 * install; this APK is handed out on Telegram, so nothing tells the server when
 * it is removed. What the server does know is silence, and silence has three
 * causes it cannot tell apart: uninstalled, phone in a drawer, or the app
 * frozen by a battery optimiser. So the figure is labelled "dormant" and the
 * wording says what it means. Relabelling this as uninstalls would be inventing
 * a number.
 */

/** A horizontal bar list — enough for a breakdown, no chart library needed. */
function Breakdown({ title, rows, total, empty = "هنوز داده‌ای نیست" }) {
  if (!rows || rows.length === 0) {
    return <Card title={title}><Empty>{empty}</Empty></Card>;
  }
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <Card title={title}>
      <div className="grid" style={{ gap: 8 }}>
        {rows.map((r) => (
          <div key={r.key} style={{ display: "grid", gap: 4 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span dir="auto" style={{ opacity: 0.9 }}>{r.key}</span>
              <span style={{ opacity: 0.7 }}>
                {fmtFa(r.count)}
                {total > 0 && (
                  <span style={{ opacity: 0.55 }}> · {Math.round((r.count / total) * 100)}٪</span>
                )}
              </span>
            </div>
            <div style={{ height: 6, background: "rgba(255,255,255,.06)", borderRadius: 99 }}>
              <div style={{
                width: `${(r.count / max) * 100}%`, height: "100%", borderRadius: 99,
                background: "linear-gradient(90deg,#2e6bff,#35d2e8)",
              }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Thirty-day install sparkline, drawn as plain divs. */
function DailyChart({ daily }) {
  if (!daily || daily.length === 0) return null;
  const max = Math.max(...daily.map((d) => d.count), 1);
  return (
    <Card title="📈 نصب‌های جدید — ۳۰ روز گذشته"
          sub={`مجموع ${fmtFa(daily.reduce((a, d) => a + d.count, 0))} نصب تازه`}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }}>
        {daily.map((d) => (
          <div key={d.date} title={`${d.date} — ${d.count}`}
               style={{
                 flex: 1,
                 // A day with zero installs still gets a visible sliver, so the
                 // axis reads as "nothing happened" rather than "no data".
                 height: `${Math.max(2, (d.count / max) * 100)}%`,
                 background: d.count ? "linear-gradient(180deg,#35d2e8,#2e6bff)" : "rgba(255,255,255,.07)",
                 borderRadius: 3,
               }} />
        ))}
      </div>
    </Card>
  );
}

const EMPTY_DRAFT = {
  title: "", body: "", url: "",
  minVersionCode: "", maxVersionCode: "", minSdk: "", expiresDays: "",
};

function Compose({ onSent }) {
  const [d, setD] = useState(EMPTY_DRAFT);
  const [reach, setReach] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setD((s) => ({ ...s, [k]: e.target.value }));

  // Reach is recalculated server-side from the same filters the delivery query
  // uses, so the number shown cannot drift from what actually gets sent.
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      api.post("/api/client/push/audience", {
        minVersionCode: parseInt(d.minVersionCode || "0", 10) || 0,
        maxVersionCode: parseInt(d.maxVersionCode || "0", 10) || 0,
        minSdk: parseInt(d.minSdk || "0", 10) || 0,
      }).then((r) => { if (alive) setReach(r.count); }).catch(() => {});
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [d.minVersionCode, d.maxVersionCode, d.minSdk]);

  const send = async () => {
    if (!d.title.trim()) { toast("عنوان لازم است", "error"); return; }
    setBusy(true);
    try {
      await api.post("/api/client/push", {
        title: d.title, body: d.body, url: d.url,
        minVersionCode: parseInt(d.minVersionCode || "0", 10) || 0,
        maxVersionCode: parseInt(d.maxVersionCode || "0", 10) || 0,
        minSdk: parseInt(d.minSdk || "0", 10) || 0,
        expiresDays: parseInt(d.expiresDays || "0", 10) || 0,
      });
      setD(EMPTY_DRAFT);
      toast("اعلان ساخته شد ✅");
      onSent();
    } catch (e) {
      toast(e.message || "ارسال نشد", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="🔔 اعلان جدید"
          sub="اپ در هر تماس دوره‌ای اعلان‌های تحویل‌نشده را می‌گیرد و نشان می‌دهد. هر اعلان به هر دستگاه فقط یک بار می‌رسد.">
      <div className="grid" style={{ gap: 10 }}>
        <div className="field">
          <label>عنوان</label>
          <input className="inp" value={d.title} onChange={set("title")} placeholder="سرورهای جدید اضافه شد" />
        </div>
        <div className="field">
          <label>متن</label>
          <textarea className="inp" rows={2} value={d.body} onChange={set("body")}
                    placeholder="برای دیدن سرورهای تازه اپ را باز کنید" />
        </div>
        <div className="field">
          <label>لینک هنگام لمس اعلان — فقط https (اختیاری)</label>
          <input className="inp" dir="ltr" value={d.url} onChange={set("url")}
                 placeholder="https://t.me/atlas_account" />
        </div>

        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
          <div className="field">
            <label>حداقل versionCode</label>
            <input className="inp" type="number" dir="ltr" value={d.minVersionCode}
                   onChange={set("minVersionCode")} placeholder="۰ = بدون محدودیت" />
          </div>
          <div className="field">
            <label>حداکثر versionCode</label>
            <input className="inp" type="number" dir="ltr" value={d.maxVersionCode}
                   onChange={set("maxVersionCode")} placeholder="۰ = بدون محدودیت" />
          </div>
          <div className="field">
            <label>حداقل SDK اندروید</label>
            <input className="inp" type="number" dir="ltr" value={d.minSdk}
                   onChange={set("minSdk")} placeholder="۰ = همه" />
          </div>
          <div className="field">
            <label>انقضا (روز)</label>
            <input className="inp" type="number" dir="ltr" value={d.expiresDays}
                   onChange={set("expiresDays")} placeholder="۰ = بی‌انقضا" />
          </div>
        </div>

        <div style={{ opacity: 0.8, fontSize: 13, lineHeight: 1.9 }}>
          {reach === null
            ? "در حال محاسبهٔ مخاطب…"
            : <>به حدود <b>{fmtFa(reach)}</b> دستگاه می‌رسد (فقط آن‌هایی که در ۳۰ روز اخیر فعال بوده‌اند).</>}
          <br />
          <span style={{ opacity: 0.7 }}>
            تحویل آنی نیست: اگر اپ باز باشد چند ثانیه، وگرنه در تماس دورهٔ بعدی (پیش‌فرض ۳۰ دقیقه).
            گوشی‌های خاموش یا در حالت Doze ممکن است دیرتر بگیرند.
          </span>
        </div>

        <div>
          <button className="btn primary" disabled={busy} onClick={send}>
            {busy ? "در حال ساخت…" : "ساخت اعلان"}
          </button>
        </div>
      </div>
    </Card>
  );
}

function PushList({ rows, reload }) {
  if (!rows || rows.length === 0) {
    return <Card title="📜 اعلان‌های ساخته‌شده"><Empty>هنوز اعلانی نساخته‌ای</Empty></Card>;
  }
  const act = async (fn, ok) => {
    try { await fn(); toast(ok); reload(); }
    catch (e) { toast(e.message || "انجام نشد", "error"); }
  };
  return (
    <Card title="📜 اعلان‌های ساخته‌شده">
      <div className="grid" style={{ gap: 10 }}>
        {rows.map((p) => (
          <div key={p.id} style={{
            border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 12,
            opacity: p.active ? 1 : 0.55,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{p.title}</div>
                {p.body && <div style={{ opacity: 0.75, fontSize: 13, marginTop: 2 }}>{p.body}</div>}
                <div style={{ opacity: 0.6, fontSize: 12, marginTop: 6 }}>
                  #{p.id} · {agoEpoch(p.created_at)}
                  {p.min_sdk > 0 && <> · SDK ≥ {p.min_sdk}</>}
                  {p.min_version_code > 0 && <> · v ≥ {p.min_version_code}</>}
                  {p.max_version_code > 0 && <> · v ≤ {p.max_version_code}</>}
                  {p.expires_at > 0 && <> · انقضا {untilEpoch(p.expires_at)}</>}
                </div>
              </div>
              <div style={{ textAlign: "left", whiteSpace: "nowrap" }}>
                <div style={{ fontSize: 13 }}>📬 {fmtFa(p.delivered)} تحویل</div>
                <div style={{ fontSize: 13, opacity: 0.8 }}>👆 {fmtFa(p.opened)} باز شد</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button className="btn" onClick={() => act(
                () => api.post(`/api/client/push/${p.id}/active`, { active: !p.active }),
                p.active ? "متوقف شد" : "دوباره فعال شد")}>
                {p.active ? "توقف" : "فعال‌سازی"}
              </button>
              <button className="btn" onClick={() => act(
                () => api.post(`/api/client/push/${p.id}/delete`), "حذف شد")}>
                حذف
              </button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function AppStats() {
  const [s, setS] = useState(null);
  const [push, setPush] = useState(null);

  const load = () => {
    api.get("/api/client/stats").then(setS)
      .catch((e) => toast(e.message || "خطا در خواندن آمار", "error"));
    api.get("/api/client/push").then((d) => setPush(d.messages || []))
      .catch(() => setPush([]));
  };
  useEffect(load, []);

  if (!s) return <Loading />;
  const t = s.totals;

  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 12 }}>
        <Stat icon="📱" value={fmtFa(t.total)} label="کل نصب‌های یکتا" foot="از ابتدا" />
        <Stat icon="🟢" value={fmtFa(t.active_30d)} label="فعال (۳۰ روز)" foot={`${fmtFa(t.active_7d)} در ۷ روز`} />
        <Stat icon="⚡" value={fmtFa(t.active_1d)} label="فعال امروز" />
        <Stat icon="🆕" value={fmtFa(t.new_7d)} label="نصب جدید (۷ روز)" foot={`${fmtFa(t.new_1d)} امروز`} />
        <Stat icon="💤" value={fmtFa(t.dormant_30d)} label="خاموش (۳۰ روز)" foot="حذف‌شده یا بلااستفاده" />
      </div>

      <Card title="ℹ️ دربارهٔ این اعداد">
        <div style={{ opacity: 0.8, fontSize: 13, lineHeight: 2 }}>
          <b>«کل نصب‌های یکتا»</b> یعنی تعداد دستگاه‌هایی که تا حالا حداقل یک بار به سرور وصل شده‌اند.
          اگر کاربری اپ را پاک و دوباره نصب کند، یک نصب جدید شمرده می‌شود — چون شناسه فقط داخل خود اپ ذخیره
          می‌شود و با پاک شدن داده‌ها از بین می‌رود.
          <br />
          <b>«خاموش»</b> جای «حذف‌شده» است. برای اپی که از تلگرام پخش می‌شود هیچ سیگنال حذف نصب وجود ندارد
          (آن عدد را فقط گوگل‌پلی دارد). چیزی که می‌دانیم سکوت است، و سکوت سه دلیل دارد که از هم قابل تفکیک
          نیستند: حذف نصب، گوشی کنار گذاشته‌شده، یا اپ فریزشده توسط بهینه‌ساز باتری.
          <br />
          <span style={{ opacity: 0.7 }}>
            هیچ IP، شماره، شناسهٔ دستگاه یا موقعیت مکانی ذخیره نمی‌شود — فقط یک UUID تصادفی که خود اپ
            برای خودش می‌سازد، به‌علاوهٔ مدل گوشی و نسخهٔ اندروید.
          </span>
        </div>
      </Card>

      <DailyChart daily={s.daily} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(320px,1fr))", gap: 14 }}>
        <Breakdown title="🔢 نسخهٔ اپ" rows={s.versions} total={t.total} />
        <Breakdown title="🤖 نسخهٔ اندروید" rows={s.androids} total={t.total} />
        <Breakdown title="🏭 برند" rows={s.brands} total={t.total} />
        <Breakdown title="⚙️ معماری پردازنده" rows={s.abis} total={t.total} />
      </div>

      <Breakdown title="📱 مدل گوشی" rows={s.models} total={t.total} />

      <Compose onSent={load} />
      <PushList rows={push} reload={load} />

      <div>
        <button className="btn" onClick={load}>بازخوانی</button>
      </div>
    </div>
  );
}
