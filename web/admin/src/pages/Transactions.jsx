import React, { useEffect, useState } from "react";
import { BASE, api, fmt } from "../api.js";
import { Card, Loading, Empty, Modal, toast, timeAgo, Avatar } from "../components/ui.jsx";

const STATUS = {
  approved: { label: "تایید شده", cls: "b-green" },
  rejected: { label: "رد شده", cls: "b-red" },
  receipt_submitted: { label: "در انتظار بررسی", cls: "b-yellow" },
  pending: { label: "در انتظار بررسی", cls: "b-yellow" },
  processing: { label: "در حال بررسی", cls: "b-blue" },
};

const FILTERS = [
  { k: "pending", label: "در انتظار" },
  { k: "topup", label: "شارژ کیف پول" },
  { k: "order", label: "سفارش‌ها" },
  { k: "", label: "همه" },
];

const isPending = (t) => t.status === "receipt_submitted" || t.status === "pending" || t.status === "processing";

export default function Transactions() {
  const [rows, setRows] = useState(null);
  const [filter, setFilter] = useState("pending");
  const [zoom, setZoom] = useState(null);
  const [busy, setBusy] = useState("");

  const load = () => api.get("/api/transactions?limit=200")
    .then((r) => setRows(r.transactions || []))
    .catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const act = async (t, kind) => {
    const key = `${t.tx_type}:${t.tx_id}`;
    setBusy(key);
    try {
      // Top-ups and orders are reviewed through their own endpoints — an order
      // approval also provisions the service, a top-up only credits the wallet.
      const base = t.tx_type === "topup" ? "topups" : "orders";
      await api.post(`/api/${base}/${t.tx_id}/${kind}`);
      toast(kind === "approve" ? "تایید شد ✅" : "رد شد");
      setZoom(null);
      load();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };

  const shown = (rows || []).filter((t) => {
    if (filter === "pending") return isPending(t);
    if (filter === "topup" || filter === "order") return t.tx_type === filter;
    return true;
  });
  const pendingCount = (rows || []).filter(isPending).length;

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <div className="row" style={{ gap: 7 }}>
          {FILTERS.map((f) => (
            <button key={f.k} className={"btn sm" + (filter === f.k ? " primary" : "")}
                    onClick={() => setFilter(f.k)}>
              {f.label}{f.k === "pending" && pendingCount > 0 ? ` (${pendingCount})` : ""}
            </button>
          ))}
        </div>
        <button className="btn xs" onClick={load}>↻ تازه‌سازی</button>
      </div>

      {!rows ? <Loading /> : !shown.length ? (
        <Card><Empty emoji="🧾">رسیدی در این دسته نیست</Empty></Card>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>نوع</th><th>کاربر</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th><th>رسید</th><th>عملیات</th>
            </tr></thead>
            <tbody>
              {shown.map((t) => {
                const st = STATUS[t.status] || { label: t.status, cls: "b-gray" };
                const key = `${t.tx_type}:${t.tx_id}`;
                return (
                  <tr key={key}>
                    <td>
                      <span className={"badge " + (t.tx_type === "topup" ? "b-blue" : "b-gray")}>
                        {t.tx_type === "topup" ? "💳 شارژ" : "🛒 سفارش"} #{t.tx_id}
                      </span>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 8 }}>
                        <Avatar name={t.full_name || t.username || "?"} />
                        <div>
                          <div>{t.full_name || "—"}</div>
                          <div className="muted tiny mono">
                            {t.username ? `@${t.username}` : t.telegram_id}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="mono">{fmt(t.amount)}</td>
                    <td><span className={"badge " + st.cls}>{st.label}</span></td>
                    <td className="muted tiny">{timeAgo(t.created_at)}</td>
                    <td>
                      {t.has_receipt
                        ? <button className="btn xs" onClick={() => setZoom(t)}>🖼 دیدن</button>
                        : <span className="muted tiny">—</span>}
                    </td>
                    <td>
                      {isPending(t) ? (
                        <div className="row" style={{ gap: 6 }}>
                          <button className="btn xs success" disabled={busy === key} onClick={() => act(t, "approve")}>تایید</button>
                          <button className="btn xs danger" disabled={busy === key} onClick={() => act(t, "reject")}>رد</button>
                        </div>
                      ) : <span className="muted tiny">{timeAgo(t.reviewed_at) || "—"}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {zoom && (
        <Modal title={`رسید ${zoom.tx_type === "topup" ? "شارژ" : "سفارش"} #${zoom.tx_id} — ${fmt(zoom.amount)} تومان`}
               onClose={() => setZoom(null)}>
          {/* The image is pulled from Telegram on demand; there is no local copy. */}
          <img src={`${BASE}/receipts/${zoom.tx_type}/${zoom.tx_id}`} alt="رسید"
               style={{ width: "100%", borderRadius: 12, background: "rgba(0,0,0,.2)" }} />
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <span className="muted tiny">{zoom.full_name || "—"}</span>
            <span className="muted tiny mono">{zoom.telegram_id}</span>
          </div>
          {isPending(zoom) && (
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              <button className="btn success" disabled={busy} onClick={() => act(zoom, "approve")}>✅ تایید</button>
              <button className="btn danger" disabled={busy} onClick={() => act(zoom, "reject")}>❌ رد</button>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
