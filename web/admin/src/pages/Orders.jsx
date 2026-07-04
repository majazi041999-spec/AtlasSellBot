import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { Card, Loading, Empty, Pager, toast } from "../components/ui.jsx";

const STATUS = {
  approved: { label: "تایید شده", cls: "b-green" },
  receipt_submitted: { label: "در انتظار", cls: "b-yellow" },
  processing: { label: "در حال پردازش", cls: "b-blue" },
  pending_payment: { label: "منتظر پرداخت", cls: "b-gray" },
  pending_receipt: { label: "منتظر رسید", cls: "b-gray" },
  rejected: { label: "رد شده", cls: "b-red" },
};
const FILTERS = [
  { k: "", label: "همه" },
  { k: "receipt_submitted", label: "در انتظار" },
  { k: "approved", label: "تایید شده" },
  { k: "rejected", label: "رد شده" },
];

export default function Orders({ onBadges }) {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(0);

  const load = (p = page, st = status) => {
    setData(null);
    api.get(`/api/orders?page=${p}&status=${st}`).then((r) => {
      setData(r);
      onBadges?.({ pending_orders: r.pending_count });
    }).catch(() => setData({ orders: [], total_pages: 1 }));
  };
  useEffect(() => { load(1, status); /* eslint-disable-next-line */ }, [status]);

  const act = async (oid, kind) => {
    setBusy(oid);
    try {
      await api.post(`/api/orders/${oid}/${kind}`);
      toast(kind === "approve" ? "سفارش تایید و فعال شد ✅" : "سفارش رد شد");
      load();
    } catch (e) { toast(kind === "approve" ? "تایید/ساخت ناموفق بود" : "خطا", "error"); }
    finally { setBusy(0); }
  };
  const goPage = (p) => { setPage(p); load(p, status); };

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <div className="row between">
        <div className="row" style={{ gap: 7 }}>
          {FILTERS.map((f) => (
            <button key={f.k} className={"btn sm" + (status === f.k ? " primary" : "")} onClick={() => { setStatus(f.k); setPage(1); }}>{f.label}</button>
          ))}
        </div>
        {data && <span className="muted tiny">{fmt(data.total)} سفارش</span>}
      </div>

      {!data ? <Loading /> : !data.orders.length ? (
        <Card><Empty>سفارشی یافت نشد</Empty></Card>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>#</th><th>پکیج</th><th>کاربر</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th><th>عملیات</th>
            </tr></thead>
            <tbody>
              {data.orders.map((o) => {
                const st = STATUS[o.status] || { label: o.status, cls: "b-gray" };
                const pend = o.status === "receipt_submitted" || o.status === "processing";
                return (
                  <tr key={o.id}>
                    <td><b>#{o.id}</b></td>
                    <td>{o.pkg_name || "—"} {o.is_renew && <span className="badge b-purple">تمدید</span>}</td>
                    <td>
                      <div>{o.full_name || "—"}</div>
                      <div className="muted tiny">{o.username ? `@${o.username}` : ""} <span className="mono">{o.telegram_id}</span></div>
                    </td>
                    <td><b style={{ color: "var(--p2)" }}>{fmt(o.price)}</b> <span className="muted tiny">ت</span></td>
                    <td><span className={"badge " + st.cls}>{st.label}</span></td>
                    <td className="muted tiny">{(o.created_at || "").slice(0, 16).replace("T", " ")}</td>
                    <td>
                      {pend ? (
                        <div className="row" style={{ gap: 6 }}>
                          <button className="btn xs success" disabled={busy === o.id} onClick={() => act(o.id, "approve")}>تایید</button>
                          <button className="btn xs danger" disabled={busy === o.id} onClick={() => act(o.id, "reject")}>رد</button>
                        </div>
                      ) : <span className="muted tiny">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager page={data.page} totalPages={data.total_pages} onGo={goPage} />}
    </div>
  );
}
