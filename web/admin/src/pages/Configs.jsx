import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Pager, Search, Toolbar, toast, timeAgo, Avatar } from "../components/ui.jsx";

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
