import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import {
  Card, Loading, Empty, Modal, Pager, toast,
  Toolbar, Search, Select, Chips, usePref,
} from "../components/ui.jsx";

/* Keys must match SUB_SORTS / SUB_FILTERS in web/app.py. */
const SORTS = [
  { k: "newest", label: "🕒 جدیدترین" },
  { k: "oldest", label: "🕒 قدیمی‌ترین" },
  { k: "name_az", label: "🔤 نام سرویس (الف → ی)" },
  { k: "name_za", label: "🔤 نام سرویس (ی → الف)" },
  { k: "owner_az", label: "👤 نام صاحب سرویس" },
  { k: "expiry_soon", label: "⏳ نزدیک‌ترین انقضا" },
  { k: "expiry_late", label: "⏳ دورترین انقضا" },
  { k: "usage_desc", label: "📊 بیشترین مصرف" },
  { k: "usage_asc", label: "📊 کمترین مصرف" },
  { k: "traffic_desc", label: "💾 بیشترین حجم" },
];
const FILTERS = [
  { k: "all", label: "همه" },
  { k: "active", label: "فعال" },
  { k: "expiring", label: "رو به انقضا (۳ روز)" },
  { k: "near_limit", label: "حجم رو به اتمام" },
  { k: "expired", label: "منقضی" },
  { k: "inactive", label: "غیرفعال" },
  { k: "unlimited", label: "نامحدود" },
];

const gb = (bytes) => (Number(bytes || 0) / 1024 ** 3).toFixed(2);
const tsToInput = (ms) => {
  if (!ms) return "";
  const d = new Date(Number(ms));
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function EditModal({ p, onClose, onSaved }) {
  const email = useRef(); const traffic = useRef(); const expire = useRef(); const [active, setActive] = useState(String(p.is_active));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.form(`/subs/profiles/${p.id}/edit`, {
        email: email.current.value, traffic_gb: traffic.current.value,
        expire_at: expire.current.value, is_active: active,
      });
      toast("ذخیره شد ✅"); onSaved();
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };
  return (
    <Modal title={`✏️ ویرایش ساب — ${p.name || p.email}`} onClose={onClose}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="field"><label>ایمیل/شناسه</label><input className="inp mono" ref={email} defaultValue={p.email} dir="ltr" /></div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>حجم (GB)</label><input className="inp" ref={traffic} type="number" step="0.1" defaultValue={p.traffic_gb} dir="ltr" /></div>
          <div className="field"><label>وضعیت</label>
            <select className="inp" value={active} onChange={(e) => setActive(e.target.value)}>
              <option value="1">فعال</option><option value="0">غیرفعال</option>
            </select></div>
        </div>
        <div className="field"><label>انقضا</label><input className="inp" ref={expire} type="datetime-local" defaultValue={tsToInput(p.expire_timestamp)} dir="ltr" /></div>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "…" : "💾 ذخیره"}</button>
      </div>
    </Modal>
  );
}

export default function SubProfiles() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = usePref("subs.sort", "newest");
  const [filt, setFilt] = usePref("subs.filter", "all");
  const [edit, setEdit] = useState(null);
  const tmr = useRef();

  const load = (opts = {}) => {
    const params = new URLSearchParams({
      page: opts.page ?? page, q: opts.q ?? q,
      sort: opts.sort ?? sort, filter: opts.filter ?? filt,
    });
    setData(null);
    api.get(`/api/subs/profiles?${params}`).then(setData).catch(() => setData({ profiles: [] }));
  };
  useEffect(() => { load({ page: 1, q: "" }); }, []);
  const onSearch = (v) => {
    setQ(v); clearTimeout(tmr.current);
    tmr.current = setTimeout(() => { setPage(1); load({ page: 1, q: v }); }, 350);
  };
  const control = (key, setter) => (v) => { setter(v); setPage(1); load({ page: 1, [key]: v }); };
  const sortBy = control("sort", setSort);
  const filterBy = control("filter", setFilt);

  const act = async (id, kind, confirmMsg) => {
    if (confirmMsg && !confirm(confirmMsg)) return;
    try { await api.post(`/subs/profiles/${id}/${kind}`); toast("انجام شد ✅"); load(); }
    catch (e) { toast("خطا", "error"); }
  };
  const copy = (url) => { navigator.clipboard?.writeText(url).then(() => toast("لینک کپی شد ✅")); };

  const profiles = (data && data.profiles) || [];

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Toolbar right={data && data.total != null ? `${fmt(data.total)} سرویس` : null}>
        <Search value={q} onChange={onSearch} placeholder="نام سرویس، ایمیل، مشتری یا آیدی تلگرام…" />
        <Select label="مرتب‌سازی" value={sort} options={SORTS} onChange={sortBy} />
      </Toolbar>
      <Chips options={FILTERS} value={filt} onChange={filterBy} />

      {!data ? <Loading /> : !profiles.length ? (
        <Card><Empty emoji="📄">
          سرویسی با این جستجو و فیلتر پیدا نشد.
          {(q || filt !== "all") && (
            <div style={{ marginTop: 12 }}>
              <button className="btn sm" onClick={() => {
                setQ(""); setFilt("all"); setPage(1); load({ page: 1, q: "", filter: "all" });
              }}>پاک کردن فیلترها</button>
            </div>
          )}
        </Empty></Card>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          {profiles.map((p) => (
            <Card key={p.id}>
              <div className="row between" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 700 }}>
                    {p.name || p.email} <span className={"badge " + (p.is_active ? "b-green" : "b-red")}>{p.is_active ? "فعال" : "غیرفعال"}</span>
                  </div>
                  <div className="muted tiny" style={{ marginTop: 3 }}>
                    {p.full_name || "—"} {p.username ? `@${p.username}` : ""} <span className="mono">{p.telegram_id}</span>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                    <span className="muted tiny">حجم: {gb(p.used_bytes)}/{p.traffic_gb || "∞"} GB ({p.used_pct}%)</span>
                    <span className="muted tiny">{p.days_left < 0 ? "بدون انقضا" : `${p.days_left} روز مانده`}</span>
                  </div>
                  <div style={{ height: 5, background: "rgba(255,255,255,.07)", borderRadius: 4, marginTop: 6, overflow: "hidden" }}>
                    <div style={{ width: `${p.used_pct}%`, height: "100%", background: p.used_pct > 85 ? "var(--red,#f43f5e)" : "var(--p2)" }} />
                  </div>
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <button className="btn xs" onClick={() => copy(p.url)}>🔗 لینک</button>
                  <button className="btn xs" onClick={() => setEdit(p)}>✏️</button>
                  <button className="btn xs" onClick={() => act(p.id, "toggle")}>{p.is_active ? "🔴" : "🟢"}</button>
                  <button className="btn xs" onClick={() => act(p.id, "reset-usage", "مصرف صفر شود؟")}>♻️ حجم</button>
                  <button className="btn xs" onClick={() => act(p.id, "reset-time", "زمان از نو شود؟")}>⏱ زمان</button>
                  <button className="btn xs" onClick={() => act(p.id, "rebuild", "لینک‌ها بازسازی شوند؟")}>🔧</button>
                  <button className="btn xs danger" onClick={() => act(p.id, "delete", `ساب «${p.name || p.email}» کامل حذف شود؟`)}>🗑</button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {data && <Pager page={data.page} totalPages={data.total_pages} onGo={(pg) => { setPage(pg); load({ page: pg }); }} />}
      {edit && <EditModal p={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
    </div>
  );
}
