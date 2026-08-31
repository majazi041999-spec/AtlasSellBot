import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Pager, Search, Toolbar, toast, timeAgo, Avatar } from "../components/ui.jsx";

/** Bulk-disable every legacy config, across every panel.
 *
 *  The preview is deliberately shown before the button does anything: this
 *  touches live servers, and the admin needs to see how many clients are
 *  protected (they belong to subscriptions) and how many sit on a server that
 *  no longer exists before committing.
 */
function BulkDisable({ onDone }) {
  const [scope, setScope] = useState("expired");
  const [prev, setPrev] = useState(null);
  const [log, setLog] = useState({ lines: [], running: false, status: "idle" });
  const [busy, setBusy] = useState(false);
  const box = useRef();
  const tmr = useRef();

  const loadPreview = (sc = scope) => {
    setPrev(null);
    api.get(`/api/configs/disable/preview?scope=${sc}`).then(setPrev).catch(() => setPrev({ error: true }));
  };
  useEffect(() => { loadPreview(); return () => clearTimeout(tmr.current); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [log]);

  const poll = () => {
    api.get("/api/configs/disable/log").then((l) => {
      setLog(l);
      if (l.running) tmr.current = setTimeout(poll, 1500);
      else {
        setBusy(false);
        toast(l.status === "ok" ? "عملیات تمام شد ✅" : "عملیات با خطا تمام شد", l.status === "ok" ? "success" : "error");
        loadPreview();
        onDone?.();
      }
    }).catch(() => { tmr.current = setTimeout(poll, 2500); });
  };

  const run = async () => {
    const n = (prev?.on_panels || 0) + (prev?.orphaned || 0);
    if (!n) { toast("چیزی برای غیرفعال‌کردن نیست", "error"); return; }
    if (!confirm(
      `${n} کانفیگ تکی غیرفعال می‌شود.\n\n` +
      (scope === "all"
        ? "⚠️ دامنه «همه» انتخاب شده — کانفیگ‌هایی که هنوز منقضی نشده‌اند هم قطع می‌شوند.\n\n"
        : "") +
      "این کار روی خود پنل‌ها اعمال می‌شود و برگشت آن ساده نیست.\n" +
      "سابسکریپشن‌ها دست نمی‌خورند.\n\nادامه می‌دهی؟"
    )) return;
    setBusy(true);
    try {
      await api.post("/api/configs/disable", { scope });
      setLog({ lines: [], running: true, status: "running" });
      poll();
    } catch (e) { toast(e.message || "خطا", "error"); setBusy(false); }
  };

  const total = (prev?.on_panels || 0) + (prev?.orphaned || 0);

  return (
    <Card title="⛔ غیرفعال‌کردن گروهی کانفیگ‌های تکی"
          sub="روی همه‌ی پنل‌ها اعمال می‌شود — سابسکریپشن‌ها دست نمی‌خورند">
      <div className="row" style={{ gap: 7, marginBottom: 12 }}>
        {[["expired", "فقط منقضی‌شده‌ها"], ["all", "همه‌ی کانفیگ‌های فعال"]].map(([k, label]) => (
          <button key={k} className={"btn sm" + (scope === k ? " primary" : "")}
                  disabled={busy}
                  onClick={() => { setScope(k); loadPreview(k); }}>{label}</button>
        ))}
      </div>

      {!prev ? <Loading /> : prev.error ? (
        <div className="muted">خواندن پیش‌نمایش ناموفق بود.</div>
      ) : (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginBottom: 12 }}>
            <Tile n={prev.on_panels} label="روی پنل‌ها غیرفعال می‌شود" />
            <Tile n={prev.orphaned} label="سرورشان حذف شده — فقط در دیتابیس" muted />
            <Tile n={prev.protected} label="محافظت‌شده (متعلق به ساب)" good />
          </div>

          {prev.protected > 0 && (
            <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid rgba(52,211,153,.3)",
                          borderRadius: 12, padding: 12, marginBottom: 12 }}>
              <b>🛡 {prev.protected} کانفیگ کنار گذاشته می‌شود</b>
              <p className="muted tiny" style={{ margin: "6px 0 0" }}>
                ایمیل این‌ها متعلق به سابسکریپشن است (یا شبیه آن است). چون بعضی اینباندها بین
                کانفیگ‌های تکی و ساب‌ها مشترک‌اند، غیرفعال‌کردنشان می‌توانست سرویس یک مشتری فعال را قطع کند.
              </p>
              {(prev.protected_samples || []).map((p) => (
                <div key={p.id} className="mono tiny" style={{ direction: "ltr", textAlign: "left", marginTop: 4 }}>
                  {p.email}
                </div>
              ))}
            </div>
          )}

          {(prev.servers || []).length > 0 && (
            <div className="table-wrap" style={{ marginBottom: 12 }}>
              <table>
                <thead><tr><th>سرور</th><th>تعداد</th><th>اینباندها</th></tr></thead>
                <tbody>
                  {prev.servers.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name}</td>
                      <td className="mono">{fmt(s.count)}</td>
                      <td className="mono tiny">{(s.inbounds || []).join("، ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ background: "rgba(251,191,36,.1)", border: "1px solid rgba(251,191,36,.35)",
                        borderRadius: 12, padding: 12, marginBottom: 12 }}>
            <p className="tiny" style={{ margin: 0, lineHeight: 2 }}>
              • برای هر اینباند فقط <b>یک بار</b> روی پنل نوشته می‌شود (<code>bulkDisable</code> در 3x-ui 3.7+)،
              پس xray به‌ازای هر کانفیگ ری‌استارت نمی‌شود و اتصال ساب‌ها قطع نمی‌شود.<br />
              • اگر پنلی قدیمی‌تر باشد، خودکار به حالت تک‌به‌تک برمی‌گردد و در گزارش هشدار می‌دهد.<br />
              • بازگرداندن یک کلاینت غیرفعال‌شده در بعضی نسخه‌های 3x-ui درست کار نمی‌کند، پس این کار را
              نهایی در نظر بگیر.
            </p>
          </div>

          <button className="btn danger" disabled={busy || !total} onClick={run}>
            {busy ? "در حال اجرا…" : `⛔ غیرفعال کن (${fmt(total)} کانفیگ)`}
          </button>
        </>
      )}

      {(log.lines || []).length > 0 && (
        <div ref={box} className="mono tiny" style={{ marginTop: 12, background: "rgba(0,0,0,.28)",
               border: "1px solid var(--line)", borderRadius: 10, padding: 10, maxHeight: 320,
               overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7 }}>
          {(log.lines || []).join("\n")}{log.running ? "\n⏳ …" : ""}
        </div>
      )}
    </Card>
  );
}

function Tile({ n, label, muted, good }) {
  const color = good ? "#6ee7b7" : muted ? "var(--txt3)" : "var(--txt1)";
  return (
    <div style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--bd)",
                  borderRadius: 12, padding: "12px 14px" }}>
      <div style={{ fontSize: "1.6rem", fontWeight: 800, color }}>{fmt(n)}</div>
      <div className="muted tiny" style={{ marginTop: 2 }}>{label}</div>
    </div>
  );
}

const daysLeft = (ms) => {
  if (!ms) return null;
  return Math.max(0, Math.floor((Number(ms) - Date.now()) / 86400000));
};

export default function Configs() {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(0);

  const load = (p = page, query = q) => {
    setData(null);
    api.get(`/api/configs?page=${p}&q=${encodeURIComponent(query)}`)
      .then(setData)
      .catch(() => setData({ configs: [], total_pages: 1, total: 0 }));
  };
  useEffect(() => { load(1, q); /* eslint-disable-next-line */ }, []);

  const search = (v) => { setQ(v); setPage(1); load(1, v); };
  const goPage = (p) => { setPage(p); load(p, q); };

  const toggle = async (c) => {
    setBusy(c.id);
    try {
      const r = await api.post(`/configs/${c.id}/toggle`);
      toast(r.success ? "وضعیت روی پنل تغییر کرد ✅" : "پنل تغییر را نپذیرفت", r.success ? "success" : "error");
      load();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(0); }
  };

  const remove = async (c) => {
    if (!confirm(
      `کانفیگ «${c.email}» حذف شود؟\n\n` +
      "روی همه‌ی سرورهایی که این کانفیگ رویشان ساخته شده حذف می‌شود و برگشت‌پذیر نیست."
    )) return;
    setBusy(c.id);
    try {
      const r = await api.post(`/configs/${c.id}/delete`);
      toast(`حذف شد — ${r.deleted_remote} سرور، ${r.deleted_local} رکورد ✅`);
      load();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(0); }
  };

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div style={{ background: "rgba(56,189,248,.08)", border: "1px solid rgba(56,189,248,.3)",
                    borderRadius: 12, padding: 12 }}>
        <b>ℹ️ این‌ها کانفیگ‌های تک‌سروره‌ی قدیمی هستند.</b>
        <p className="muted tiny" style={{ margin: "6px 0 0" }}>
          فروش جدید همه به‌صورت «سابسکریپشن چندسروره» انجام می‌شود؛ آن‌ها را در «ساب‌های کاربران» ببین.
          این صفحه فقط برای رسیدگی به مشتری‌های قدیمی است.
        </p>
      </div>

      <BulkDisable onDone={() => load(1, q)} />

      <Toolbar right={data && <span className="muted tiny">{fmt(data.total)} کانفیگ</span>}>
        <Search value={q} onChange={search} placeholder="جستجو: ایمیل، نام یا آیدی کاربر…" />
      </Toolbar>

      {!data ? <Loading /> : !data.configs.length ? (
        <Card><Empty emoji="🔑">کانفیگی یافت نشد</Empty></Card>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>کانفیگ</th><th>کاربر</th><th>سرور</th><th>حجم</th><th>انقضا</th><th>وضعیت</th><th>عملیات</th>
              </tr></thead>
              <tbody>
                {data.configs.map((c) => {
                  const d = daysLeft(c.expire_timestamp);
                  return (
                    <tr key={c.id}>
                      <td>
                        <div className="mono" style={{ direction: "ltr", textAlign: "left" }}>{c.email}</div>
                        <div className="muted tiny">{timeAgo(c.created_at)}</div>
                      </td>
                      <td>
                        <div className="row" style={{ gap: 8 }}>
                          <Avatar name={c.full_name || c.username || "?"} />
                          <div>
                            <div>{c.full_name || "—"}</div>
                            <div className="muted tiny mono">{c.username ? `@${c.username}` : c.telegram_id}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        {c.server_name || "—"}
                        {c.history_count > 1 && (
                          <div className="muted tiny" title={(c.history_servers || []).join(" ← ")}>
                            {c.history_count} بار جابه‌جا شده
                          </div>
                        )}
                      </td>
                      <td className="mono">{c.traffic_gb > 0 ? `${c.traffic_gb} GB` : "نامحدود"}</td>
                      <td>
                        {d === null ? <span className="muted tiny">بدون انقضا</span>
                          : d > 0 ? <span className="mono">{d} روز</span>
                          : <span className="badge b-red">منقضی</span>}
                      </td>
                      <td>
                        {c.is_active
                          ? <span className="badge b-green">فعال</span>
                          : <span className="badge b-gray">غیرفعال</span>}
                      </td>
                      <td>
                        <div className="row" style={{ gap: 6 }}>
                          <button className="btn xs" disabled={busy === c.id} onClick={() => toggle(c)}>
                            {c.is_active ? "قطع" : "وصل"}
                          </button>
                          <button className="btn xs danger" disabled={busy === c.id} onClick={() => remove(c)}>حذف</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager page={data.page} totalPages={data.total_pages} onGo={goPage} />
        </>
      )}
    </div>
  );
}
