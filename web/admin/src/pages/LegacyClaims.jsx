import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, Empty, toast, timeAgo, Avatar } from "../components/ui.jsx";

export default function LegacyClaims() {
  const [claims, setClaims] = useState(null);
  const [busy, setBusy] = useState(0);

  const load = () => api.get("/api/legacy-claims")
    .then((r) => setClaims(r.claims || []))
    .catch(() => setClaims([]));
  useEffect(() => { load(); }, []);

  const act = async (c, kind) => {
    if (kind === "approve" && !confirm(
      `کانفیگ «${c.email || c.uuid}» به حساب ${c.full_name || c.telegram_id} وصل شود؟`
    )) return;
    setBusy(c.id);
    try {
      await api.post(`/legacy-claims/${c.id}/${kind}`);
      toast(kind === "approve" ? "تایید شد و به حساب کاربر وصل شد ✅" : "درخواست رد شد");
      load();
    } catch (e) {
      // The approve path can fail for a real reason (the config isn't on any
      // panel any more) — show that instead of a generic error.
      toast(e.message || "خطا", "error");
    } finally { setBusy(0); }
  };

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div style={{ background: "rgba(56,189,248,.08)", border: "1px solid rgba(56,189,248,.3)",
                    borderRadius: 12, padding: 12 }}>
        <b>ℹ️ درخواست انتقال کانفیگ قدیمی</b>
        <p className="muted tiny" style={{ margin: "6px 0 0" }}>
          کاربری که قبلاً بیرون از ربات کانفیگ خریده، لینکش را برای ربات فرستاده تا به حسابش وصل شود.
          با تایید، کانفیگ روی پنل پیدا و به نام او ثبت می‌شود. همین کار از داخل ربات هم ممکن است.
        </p>
      </div>

      <Card title="⏳ در انتظار بررسی"
            right={<button className="btn xs" onClick={load}>↻ تازه‌سازی</button>}>
        {!claims ? <Loading /> : !claims.length ? (
          <Empty emoji="✅">درخواست بازی وجود ندارد</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>کاربر</th><th>شناسه کانفیگ</th><th>لینک</th><th>تاریخ</th><th>عملیات</th></tr></thead>
              <tbody>
                {claims.map((c) => (
                  <tr key={c.id}>
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
                      <div className="mono" style={{ direction: "ltr", textAlign: "left" }}>{c.email || "—"}</div>
                      {c.uuid && <div className="muted tiny mono" style={{ direction: "ltr", textAlign: "left" }}>{c.uuid}</div>}
                    </td>
                    <td style={{ maxWidth: 260 }}>
                      <div className="mono tiny" style={{ direction: "ltr", textAlign: "left",
                             overflowWrap: "anywhere" }}>{c.config_link || "—"}</div>
                    </td>
                    <td className="muted tiny">{timeAgo(c.created_at)}</td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn xs success" disabled={busy === c.id} onClick={() => act(c, "approve")}>تایید</button>
                        <button className="btn xs danger" disabled={busy === c.id} onClick={() => act(c, "reject")}>رد</button>
                      </div>
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
