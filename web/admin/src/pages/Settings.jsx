import React, { useEffect, useState, useRef } from "react";
import { api, BASE } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

// Small controlled field helpers ------------------------------------------------
function Text({ s, set, k, label, ph, ltr }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input className="inp" value={s[k] ?? ""} onChange={(e) => set(k, e.target.value)} placeholder={ph} dir={ltr ? "ltr" : "rtl"} />
    </div>
  );
}
function Area({ s, set, k, label, mono }) {
  return (
    <div className="field">
      <label>{label}</label>
      <textarea value={s[k] ?? ""} onChange={(e) => set(k, e.target.value)}
        style={{ width: "100%", minHeight: 84, borderRadius: 8, padding: 8, background: "rgba(0,0,0,.2)",
          color: "var(--txt)", border: "1px solid var(--line)", fontFamily: mono ? "monospace" : "inherit",
          fontSize: mono ? ".78rem" : ".9rem", direction: mono ? "ltr" : "rtl" }} />
    </div>
  );
}
function Toggle({ s, set, k, label }) {
  const on = String(s[k]) === "1";
  return (
    <div className="row between" style={{ padding: "6px 0" }}>
      <span style={{ fontSize: ".9rem" }}>{label}</span>
      <button className={"btn xs " + (on ? "success" : "")} onClick={() => set(k, on ? "0" : "1")}>
        {on ? "✅ روشن" : "⭕️ خاموش"}
      </button>
    </div>
  );
}
function Select({ s, set, k, label, options }) {
  return (
    <div className="field">
      <label>{label}</label>
      <select className="inp" value={String(s[k] ?? "")} onChange={(e) => set(k, e.target.value)}>
        {options.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
      </select>
    </div>
  );
}

/** Per-subscription concurrent-connection limit.
 *
 *  Its own state and its own save button, separate from the big settings form:
 *  this switches paying customers off, and an accidental save of the whole
 *  settings page must never be able to arm it as a side effect.
 */
const KIND_LABEL = {
  warned: ["b-yellow", "هشدار"],
  cut: ["b-red", "قطع شد"],
  would_cut: ["b-gray", "قطع می‌شد"],
  restored: ["b-green", "برگشت"],
  restore_failed: ["b-red", "برگشت ناموفق"],
};

function fmtWhen(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("fa-IR", { month: "2-digit", day: "2-digit",
                                     hour: "2-digit", minute: "2-digit" });
}
function fmtLeft(sec) {
  if (sec >= 3600) return `${Math.round(sec / 3600)} ساعت`;
  if (sec >= 60) return `${Math.round(sec / 60)} دقیقه`;
  return `${sec} ثانیه`;
}

/** "Which models can my key use?" — the answer to the one AI misconfiguration
 *  that cannot be fixed by re-reading the key.
 *
 *  A 404 from Gemini means the project has no model by that name, and model ids
 *  are Google's to rename whenever they like. So rather than shipping a name
 *  that will eventually be wrong, this asks the key and lets the owner click
 *  one. Save the key first — it is read from the server, never from this form.
 */
function AiModelPicker({ s, set }) {
  const [state, setState] = useState(null);   // null | "loading" | result
  const load = async () => {
    setState("loading");
    try { setState(await api.get("/api/analytics/ai/models")); }
    catch (e) { setState({ ok: false, message: e.message || "خطا" }); }
  };
  return (
    <div>
      <button className="btn sm" onClick={load} disabled={state === "loading"}>
        {state === "loading" ? "در حال بررسی…" : "🔍 بررسی کلید و مدل‌های در دسترس"}
      </button>
      {state && state !== "loading" && !state.ok && (
        <p className="tiny" style={{ margin: "6px 0 0", color: "#fb7185", lineHeight: 1.9 }}>
          {state.message}
        </p>
      )}
      {state && state !== "loading" && state.ok && (
        <div style={{ marginTop: 8 }}>
          <p className="muted tiny" style={{ margin: "0 0 6px" }}>
            کلید سالم است. روی هرکدام بزنی، در فیلد بالا گذاشته می‌شود
            (بعد ذخیره را نزنی اعمال نمی‌شود):
          </p>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {state.models.map((m) => (
              <button key={m.id}
                      className={"btn xs " + (String(s.ai_model).trim() === m.id ? "success" : "")}
                      onClick={() => set("ai_model", m.id)}
                      title={m.label}>
                <span className="mono" dir="ltr">{m.id}</span>
              </button>
            ))}
            {!state.models.length && (
              <span className="muted tiny">این کلید به هیچ مدلی دسترسی ندارد.</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── shared gateways ─────────────────────────────────────────────────────────
// A carrier NAT gives one subscriber a different public address per connection,
// so one customer on a phone can look like twenty simultaneous places. This
// panel shows the networks known to do that, the evidence for each, and lets
// the owner overrule one that was learned wrongly.
function GatewayList({ gateways, s, set, reload }) {
  const [open, setOpen] = useState(false);
  const [block, setBlock] = useState("");
  const [busy, setBusy] = useState(false);
  const learn = String(s.ip_limit_gateways_enabled ?? "1") === "1";

  const act = async (fn, ok) => {
    setBusy(true);
    try { await fn(); toast(ok); await reload(); }
    catch (e) { toast(e.message || "خطا", "err"); }
    finally { setBusy(false); }
  };
  const add = () => act(
    () => api.post("/api/ipguard/gateways", { block: block.trim() }),
    "اضافه شد").then(() => setBlock(""));
  const toggle = (g) => act(
    () => api.post("/api/ipguard/gateways/toggle",
                   { block: g.block, enabled: g.enabled ? "0" : "1" }),
    g.enabled ? "غیرفعال شد" : "فعال شد");
  const del = (g) => act(
    () => api.post("/api/ipguard/gateways/delete", { block: g.block }), "حذف شد");
  const scan = () => act(async () => {
    const r = await api.post("/api/ipguard/gateways/scan", {});
    toast(`${(r.found || []).length} شبکه‌ی مشترک شناسایی شد`);
  }, "بررسی انجام شد");

  const live = gateways.filter((g) => g.enabled).length;

  return (
    <div style={{ background: "rgba(129,140,248,.07)", border: "1px solid rgba(129,140,248,.3)",
                  borderRadius: 12, padding: 12 }}>
      <Toggle s={s} set={set} k="ip_limit_gateways_enabled"
              label="شبکه‌های مشترک (NAT اپراتور) خودکار شناسایی شوند" />
      <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 2 }}>
        اپراتورهای موبایل و بعضی ISPها برای <b>هر اتصال</b> یک آی‌پی متفاوت از استخر
        خودشان می‌دهند. بدون این قابلیت، یک مشتری روی گوشی می‌تواند <b>۱۵ تا ۲۰ مکان</b>
        شمرده شود و بی‌گناه قطع شود. یک آدرس که برای <b>دو مشتری متفاوت</b> دیده شود
        قطعاً یک گیت‌وی مشترک است — هیچ دستگاهی مال دو نفر نیست — و شبکه‌ی آن آدرس
        از آن به بعد روی هم <b>یک مکان</b> حساب می‌شود.
      </p>

      <div className="row between" style={{ marginTop: 10, gap: 8, flexWrap: "wrap" }}>
        <span className="muted tiny">
          {gateways.length ? `${live} شبکه‌ی فعال از ${gateways.length}` : "هنوز شبکه‌ای ثبت نشده"}
        </span>
        <span className="row" style={{ gap: 6 }}>
          <button className="btn xs" disabled={busy || !learn} onClick={scan}>🔍 بررسی الان</button>
          <button className="btn xs" onClick={() => setOpen((v) => !v)}>
            {open ? "بستن" : "مدیریت"}
          </button>
        </span>
      </div>

      {open && (
        <div className="grid" style={{ gap: 8, marginTop: 10 }}>
          {gateways.map((g) => (
            <div key={g.block} className="row between"
                 style={{ background: "var(--bg2)", border: "1px solid var(--line)",
                          borderRadius: 10, padding: "8px 10px", gap: 8, flexWrap: "wrap" }}>
              <span className="grid" style={{ gap: 2 }}>
                <span className="mono" dir="ltr" style={{ fontSize: ".85rem" }}>{g.block}</span>
                <span className="muted tiny" dir="ltr">
                  {g.evidence || g.note || "—"}
                </span>
              </span>
              <span className="row" style={{ gap: 6 }}>
                <span className={`badge ${g.source === "manual" ? "b-blue" : g.source === "seed" ? "b-gray" : "b-green"}`}>
                  {g.source === "manual" ? "دستی" : g.source === "seed" ? "پیش‌فرض" : "خودکار"}
                </span>
                {!g.enabled && <span className="badge b-gray">غیرفعال</span>}
                <button className="btn xs" disabled={busy} onClick={() => toggle(g)}>
                  {g.enabled ? "غیرفعال کن" : "فعال کن"}
                </button>
                <button className="btn xs danger" disabled={busy} onClick={() => del(g)}>حذف</button>
              </span>
            </div>
          ))}

          <div className="row" style={{ gap: 6 }}>
            <input className="inp" dir="ltr" placeholder="31.171.96.0/21" value={block}
                   onChange={(e) => setBlock(e.target.value)} />
            <button className="btn sm" disabled={busy || !block.trim()} onClick={add}>افزودن</button>
          </div>

          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
            <Text s={s} set={set} k="ip_limit_gateway_min_users" label="حداقل مشتری متفاوت روی یک آی‌پی" ltr />
            <Text s={s} set={set} k="ip_limit_gateway_bits" label="پهنای بلوک (مثلاً ۲۴ = /24)" ltr />
            <Text s={s} set={set} k="ip_limit_gateway_window_hours" label="بازه‌ی شواهد (ساعت)" ltr />
            <Text s={s} set={set} k="ip_limit_gateway_scan_minutes" label="فاصله‌ی بررسی (دقیقه)" ltr />
          </div>
        </div>
      )}
    </div>
  );
}


function IpGuardCard() {
  const [d, setD] = useState(null);
  const [s, setS] = useState({});
  const [busy, setBusy] = useState(false);
  const [showLog, setShowLog] = useState(false);

  const load = () => api.get("/api/ipguard").then((r) => { setD(r); setS(r.settings); })
                        .catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);

  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/ipguard", s);
      toast(r.released ? `ذخیره شد — ${r.released} اشتراک از حالت قطع خارج شد` : "ذخیره شد");
      await load();
    } catch (e) { toast(e.message || "خطا در ذخیره", "err"); }
    finally { setBusy(false); }
  };
  const release = async (pid) => {
    try { await api.post(`/api/ipguard/release/${pid}`); toast("آزاد شد"); await load(); }
    catch (e) { toast(e.message || "خطا", "err"); }
  };

  if (!d) return null;
  const on = String(s.ip_limit_enabled) === "1";
  const dry = String(s.ip_limit_warn_only) === "1";
  const events = d.events || [];
  const cut = d.cut_now || [];

  return (
    <Card title="🔐 محدودیت اتصال هم‌زمان" sub="سقف تعداد مکان‌هایی که هم‌زمان به یک اشتراک وصل می‌شوند"
          right={<button className="btn sm primary" disabled={busy} onClick={save}>
                   {busy ? "…" : "💾 ذخیره"}</button>}>
      <div className="grid" style={{ gap: 10 }}>
        <Toggle s={s} set={set} k="ip_limit_enabled" label="این سیستم فعال باشد" />

        {(d.coverage?.blind_servers || []).length > 0 && (
          <div style={{ background: "rgba(56,189,248,.09)", border: "1px solid rgba(56,189,248,.35)",
                        borderRadius: 12, padding: 12 }}>
            <b>🌐 این سرورها پشت CDN هستند و قابل کنترل نیستند</b>
            <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 2 }}>
              {d.coverage.blind_servers.join("، ")} — روی این سرورها، آی‌پی‌ای که به
              xray می‌رسد <b>آدرس خود کلادفلر است، نه مشتری</b>. یک مشتری روی ده‌ها
              سرور لبه‌ی کلادفلر پخش می‌شود، پس شمارش اتصال آنجا بی‌معناست و
              <b> عمداً انجام نمی‌شود</b> (وگرنه هر مشتری سالمی قطع می‌شد).
              <br />
              یعنی این محدودیت فقط روی <b>{d.coverage.policeable} سرور از {d.coverage.seen_servers}</b> اعمال می‌شود.
              برای پوشش کامل باید روی آن سرورها آی‌پی واقعی مشتری به xray برسد
              (nginx با <span className="mono" dir="ltr">CF-Connecting-IP</span> +
              <span className="mono" dir="ltr"> PROXY protocol</span>).
            </p>
          </div>
        )}

        {on && (
          <div style={{ background: dry ? "rgba(251,191,36,.09)" : "rgba(251,113,133,.09)",
                        border: `1px solid ${dry ? "rgba(251,191,36,.3)" : "rgba(251,113,133,.3)"}`,
                        borderRadius: 12, padding: 12 }}>
            <Toggle s={s} set={set} k="ip_limit_warn_only"
                    label="فقط ثبت و هشدار — هیچ اشتراکی قطع نشود" />
            <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 2 }}>
              {dry ? (
                <>
                  <b>حالت آزمایشی روشن است</b> و هیچ مشتری‌ای قطع نمی‌شود. چند روز همین‌طور
                  بگذار، بعد «سابقه» را باز کن و ببین چه کسانی قطع <i>می‌شدند</i>. اگر
                  اسم مشتری‌های سالم آنجا نبود، این گزینه را خاموش کن تا واقعاً اعمال شود.
                </>
              ) : (
                <><b>اعمال واقعی روشن است.</b> از این پس اشتراکی که مکرراً از سقف رد شود،
                   پلکانی قطع می‌شود. قبل از این، حتماً چند روز حالت آزمایشی را دیده باش.</>
              )}
            </p>
          </div>
        )}

        {on && (
          <>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
              <Text s={s} set={set} k="ip_limit_default" label="سقف پیش‌فرض (تعداد مکان)" ltr />
              <Text s={s} set={set} k="ip_limit_steps" label="پله‌های قطع (ثانیه)" ltr />
              <Text s={s} set={set} k="ip_limit_strikes" label="چند بررسی پشت‌سرهم تا اقدام" ltr />
              <Text s={s} set={set} k="ip_limit_poll_seconds" label="فاصله‌ی بررسی (ثانیه)" ltr />
            </div>
            <Text s={s} set={set} k="ip_limit_cdn_extra"
                  label="رنج CDN های دیگر (اختیاری، با کاما) — کلادفلر از قبل هست" ltr />
            <GatewayList gateways={d.gateways || []} s={s} set={set} reload={load} />

            {cut.length > 0 && (
              <div>
                <div className="muted tiny" style={{ marginBottom: 6 }}>
                  الان قطع هستند ({cut.length})
                </div>
                <div className="grid" style={{ gap: 6 }}>
                  {cut.map((c) => (
                    <div key={c.profile_id} className="row between"
                         style={{ background: "rgba(251,113,133,.08)", border: "1px solid var(--line)",
                                  borderRadius: 10, padding: "8px 10px", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: ".85rem" }}>
                        اشتراک #{c.profile_id} — {c.last_ip_count} مکان — پله {c.level}
                      </span>
                      <span className="row" style={{ gap: 8 }}>
                        <span className="badge b-red">{fmtLeft(c.seconds_left)} مانده</span>
                        <button className="btn xs" onClick={() => release(c.profile_id)}>آزاد کن</button>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button className="btn sm" onClick={() => setShowLog((v) => !v)}>
              {showLog ? "بستن سابقه" : `📜 سابقه (${events.length})`}
            </button>

            {showLog && (
              <div className="table-wrap" style={{ maxHeight: 340, overflowY: "auto" }}>
                <table>
                  <thead><tr><th>زمان</th><th>اشتراک</th><th>رویداد</th><th>مکان‌ها</th><th>سقف</th></tr></thead>
                  <tbody>
                    {events.length === 0 && (
                      <tr><td colSpan={5} className="muted tiny">هنوز چیزی ثبت نشده</td></tr>
                    )}
                    {events.map((e) => {
                      const k = KIND_LABEL[e.kind] || ["b-gray", e.kind];
                      return (
                        <tr key={e.id}>
                          <td className="tiny">{fmtWhen(e.created_at)}</td>
                          <td className="tiny">{e.profile_name || e.profile_email || `#${e.profile_id}`}</td>
                          <td><span className={"badge " + k[0]}>{k[1]}</span></td>
                          <td className="mono">{e.ip_count || "—"}</td>
                          <td className="mono">{e.limit_used || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <p className="muted tiny" style={{ margin: 0, lineHeight: 2 }}>
          <b>ملاک، اتصال هم‌زمان است، نه تعداد آی‌پی در طول روز.</b> کاربری که با سیم‌کارت
          است و آی‌پی‌اش عوض می‌شود، یک مکان حساب می‌شود — چون آی‌پی قبلی‌اش دیگر ترافیک
          ندارد و کنار گذاشته می‌شود.
          <br />
          هیچ باری روی سرورها اضافه نمی‌شود: پنل 3x-ui خودش هر ۱۰ ثانیه این اطلاعات را
          دارد و ما فقط <b>یک درخواست برای هر سرور</b> می‌فرستیم.
          <br />
          <b>«قطع» یعنی اتصال جدید برقرار نمی‌شود</b>؛ اتصال‌های باز فعلی تا وقتی خودشان
          بسته شوند ادامه دارند (چند ثانیه تا چند دقیقه). زمان و حجم اشتراک مشتری از
          بین نمی‌رود.
          <br />
          برای تغییر سقف <b>یک اشتراک خاص</b>، لینک همان ساب را در ربات بفرست و از پنل
          مدیریت ساب، «سقف اتصال» را عوض کن.
        </p>
      </div>
    </Card>
  );
}


export default function Settings() {
  const [s, setS] = useState(null);
  const [servers, setServers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [logo, setLogo] = useState("");
  const logoRef = useRef();

  useEffect(() => {
    api.get("/api/settings").then((r) => { setS(r.settings); setServers(r.servers || []); })
      .catch(() => toast("خطا در بارگذاری تنظیمات", "error"));
    api.get("/api/branding").then((r) => setLogo(r.logo || "")).catch(() => {});
  }, []);

  const set = (k, v) => setS((o) => ({ ...o, [k]: v }));

  const saveRepPricing = async () => {
    setBusy("reppricing");
    try {
      await api.post("/api/rep-pricing", {
        rep_price_per_gb: s.rep_price_per_gb, rep_unlimited_price: s.rep_unlimited_price, rep_min_topup: s.rep_min_topup,
      });
      toast("قیمت‌گذاری نمایندگان ذخیره شد ✅");
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(false); }
  };

  const uploadLogo = async () => {
    const file = logoRef.current?.files?.[0];
    if (!file) { toast("عکسی انتخاب نشده", "error"); return; }
    setBusy("logo");
    try { const r = await api.form("/api/logo", { logo: file }); setLogo(r.logo || ""); toast("لوگو ذخیره شد ✅ (favicon و پنل هم به‌روز شد)"); }
    catch (e) { toast(e.message || "خطا در آپلود", "error"); } finally { setBusy(false); }
  };
  const clearLogo = async () => {
    setBusy("logo");
    try { await api.post("/api/logo/clear"); setLogo(""); toast("لوگو حذف شد"); }
    catch (e) { toast("خطا", "error"); } finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true);
    try {
      // Submit the COMPLETE snapshot — the endpoint resets any omitted field.
      const body = {};
      Object.entries(s).forEach(([k, v]) => { body[k] = v == null ? "" : v; });
      await api.form("/settings", body);
      toast("تنظیمات ذخیره شد ✅");
    } catch (e) { toast(e.message || "خطا در ذخیره", "error"); } finally { setBusy(false); }
  };

  if (!s) return <Loading />;
  const srvOpts = [{ v: "0", t: "— انتخاب نشده —" }, ...servers.map((x) => ({ v: String(x.id), t: x.name + (x.is_active ? "" : " (غیرفعال)") }))];

  return (
    <div className="screen grid" style={{ gap: 16, paddingBottom: 80 }}>
      <Card title="🏷 برند و ظاهر">
        <div className="grid" style={{ gap: 8 }}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="ui_brand_name" label="نام برند" />
            <Text s={s} set={set} k="ui_logo_emoji" label="ایموجی لوگو" ltr />
          </div>
          <Text s={s} set={set} k="ui_panel_subtitle" label="زیرعنوان پنل" />
          <Text s={s} set={set} k="ui_topbar_note" label="یادداشت نوار بالا" />
        </div>
        <div style={{ borderTop: "1px solid var(--line)", marginTop: 12, paddingTop: 12 }}>
          <label style={{ fontWeight: 700, fontSize: ".85rem" }}>🖼 لوگو (پنل، favicon و صفحه‌ی لینک مرورگر)</label>
          <div className="row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
            {logo ? <img src={logo} alt="logo" style={{ width: 56, height: 56, borderRadius: 14, objectFit: "cover", border: "1px solid var(--line)" }} /> : <div style={{ width: 56, height: 56, borderRadius: 14, display: "grid", placeItems: "center", background: "rgba(255,255,255,.05)" }}>🛡️</div>}
            <input type="file" accept="image/*" ref={logoRef} className="inp" style={{ maxWidth: 240 }} />
            <button className="btn sm primary" disabled={busy === "logo"} onClick={uploadLogo}>⬆️ آپلود</button>
            {logo && <button className="btn sm danger" disabled={busy === "logo"} onClick={clearLogo}>حذف</button>}
          </div>
          <p className="muted tiny" style={{ margin: "6px 0 0" }}>تصویر به‌صورت خودکار ریسایز می‌شود. برای نماینده‌ها، لوگوی خودشان نشان داده می‌شود نه این.</p>
        </div>
      </Card>

      <Card title="🧬 سابسکریپشن">
        <div className="grid" style={{ gap: 8 }}>
          <Text s={s} set={set} k="public_base_url" label="آدرس پایه عمومی (public base url)" ph="https://domain.com" ltr />
          <Toggle s={s} set={set} k="sub_info_enabled" label="نمایش خط اطلاعات در ساب" />
          <Toggle s={s} set={set} k="sub_info_sync_on_render" label="سینک در لحظه‌ی رندر ساب" />
          <Text s={s} set={set} k="sub_info_template" label="قالب خط اطلاعات" />
          <Text s={s} set={set} k="sub_brand_template" label="قالب خط برند" />
          <p className="muted tiny" style={{ margin: 0 }}>حداقل/حداکثر نود حذف شده؛ هر ساب روی همه‌ی نودها ساخته می‌شود.</p>
        </div>
      </Card>

      <Card title="🏢 نمایندگان">
        <div className="field"><label>حداقل شارژ اولیه نماینده (تومان)</label>
          <input className="inp" value={s.rep_min_topup ?? ""} onChange={(e) => set("rep_min_topup", e.target.value.replace(/[^\d]/g, ""))} dir="ltr" />
          <p className="muted tiny" style={{ margin: "4px 0 0" }}>نماینده تا این مبلغ شارژ نکند، «ساخت سرویس» برایش فعال نمی‌شود (ضد سوءاستفاده). در قوانین نمایندگی هم نشان داده می‌شود.</p>
        </div>
      </Card>

      <Card title="🏢 قیمت‌گذاری نمایندگان">
        <div className="grid" style={{ gap: 8 }}>
          <p className="muted tiny" style={{ margin: 0 }}>قیمت واحد برای همه‌ی نماینده‌ها. اگر برای یک نماینده قیمت اختصاصی (کاستوم) در صفحه‌ی کاربر تنظیم کنی، آن قیمت اولویت دارد.</p>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="field"><label>قیمت هر GB (تومان)</label>
              <input className="inp" value={s.rep_price_per_gb ?? "0"} onChange={(e) => set("rep_price_per_gb", e.target.value)} dir="ltr" /></div>
            <div className="field"><label>قیمت نامحدود (تومان)</label>
              <input className="inp" value={s.rep_unlimited_price ?? "0"} onChange={(e) => set("rep_unlimited_price", e.target.value)} dir="ltr" /></div>
          </div>
          <div className="field"><label>حداقل شارژ اولیه‌ی نماینده‌های جدید (تومان)</label>
            <input className="inp" value={s.rep_min_topup ?? "0"} onChange={(e) => set("rep_min_topup", e.target.value)} dir="ltr" />
            <p className="muted tiny" style={{ margin: "4px 0 0" }}>فقط برای نماینده‌هایی که تازه درخواست می‌دهند اعمال می‌شود؛ نماینده‌های فعلی مستثنا هستند.</p>
          </div>
          <button className="btn primary sm" disabled={busy === "reppricing"} onClick={saveRepPricing}>💾 ذخیره قیمت‌گذاری نمایندگان</button>
        </div>
      </Card>

      <Card title="🎁 اکانت تست">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle s={s} set={set} k="test_account_enabled" label="فعال بودن اکانت تست" />
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="test_account_traffic_gb" label="حجم (GB)" ltr />
            <Text s={s} set={set} k="test_account_duration_days" label="مدت (روز)" ltr />
          </div>
          <div className="field" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
            <label>🏢 سقف تست روزانه‌ی نمایندگان (۰ = مثل کاربر عادی، فقط یک‌بار)</label>
            <input className="inp" type="number" min="0" value={s.rep_test_daily_limit ?? "0"} onChange={(e) => set("rep_test_daily_limit", e.target.value)} dir="ltr" />
            <p className="muted tiny" style={{ margin: "4px 0 0" }}>اگر عددی بزرگ‌تر از صفر بگذاری، هر نماینده می‌تواند روزانه تا این تعداد اکانت تست بگیرد (جدا از کاربران عادی).</p>
          </div>
        </div>
      </Card>

      <Card title="💳 اطلاعات کارت">
        <div className="grid" style={{ gap: 8 }}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="card_number" label="شماره کارت" ltr />
            <Text s={s} set={set} k="card_bank" label="بانک" />
          </div>
          <Text s={s} set={set} k="card_holder" label="نام صاحب کارت" />
        </div>
      </Card>

      <Card title="🤖 تحلیل هوش مصنوعی" sub="اختیاری — پیش‌فرض خاموش">
        <div className="grid" style={{ gap: 10 }}>
          <div style={{ background: "rgba(251,191,36,.09)", border: "1px solid rgba(251,191,36,.3)",
                        borderRadius: 12, padding: 12 }}>
            <b>قبل از روشن‌کردن، این را بدان:</b>
            <p className="muted tiny" style={{ margin: "6px 0 0", lineHeight: 2 }}>
              با روشن‌کردن، <b>آمار درآمد کسب‌وکارت</b> (مجموع‌های روزانه، پیش‌بینی، نام پکیج‌ها)
              به سرویس‌دهنده‌ی هوش مصنوعی فرستاده می‌شود. هیچ اطلاعات مشتری، آیدی تلگرام،
              شماره یا توکن اشتراکی فرستاده نمی‌شود.
              <br />
              روی طرح‌های <b>رایگان</b> داده‌ات هزینه‌ی سرویس است. شرایط رسمی Gemini برای طرح
              رایگان می‌گوید گوگل از آنچه می‌فرستی برای بهبود محصولاتش استفاده می‌کند و
              <b>ممکن است بازبین انسانی</b> ورودی و خروجی را بخواند. روی طرح پولی این‌طور نیست.
              اگر از OpenRouter استفاده می‌کنی، خاموش‌کردن آموزش برای مدل‌های رایگان
              <b>تنظیم جداگانه‌ای</b> دارد و با تنظیم مدل‌های پولی یکی نیست.
              اگر این برایت مهم است، روشنش نکن؛ پیش‌بینی و آمار بدون آن هم کامل کار می‌کند.
            </p>
          </div>

          <Toggle s={s} set={set} k="ai_enabled" label="تحلیل هوش مصنوعی فعال باشد" />

          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Select s={s} set={set} k="ai_provider" label="سرویس‌دهنده" options={[
              { v: "gemini", t: "Google Gemini (رایگان)" },
              { v: "openai", t: "سازگار با OpenAI (OpenRouter / Groq / پروکسی)" },
            ]} />
            <Text s={s} set={set} k="ai_model" label="نام مدل" ltr />
          </div>

          <AiModelPicker s={s} set={set} />

          {String(s.ai_provider) === "openai" && (
            <Text s={s} set={set} k="ai_base_url" label="آدرس پایه (Base URL)" ltr />
          )}

          <div className="field">
            <label>کلید API {String(s.ai_key_set) === "1" ? "— کلیدی ذخیره شده است" : ""}</label>
            <input className="inp mono" dir="ltr" type="password" autoComplete="new-password"
                   placeholder={String(s.ai_key_set) === "1" ? "برای تغییر، کلید جدید را بنویس" : "کلید را اینجا بگذار"}
                   onChange={(e) => set("ai_api_key", e.target.value)} />
            <p className="muted tiny" style={{ margin: "5px 0 0" }}>
              کلید هرگز به مرورگر برگردانده نمی‌شود. اگر این فیلد را خالی بگذاری، کلید فعلی
              دست‌نخورده می‌ماند.
            </p>
          </div>

          <p className="muted tiny" style={{ margin: 0, lineHeight: 2 }}>
            <b>Gemini:</b> از <span className="mono" dir="ltr">aistudio.google.com</span> کلید رایگان بگیر
            (بدون کارت اعتباری). مدل پیشنهادی <span className="mono" dir="ltr">gemini-2.5-flash</span> —
            حدود ۱۰ تا ۱۵ درخواست در دقیقه و چند صد درخواست در روز، که برای این کار خیلی بیش از کافی است.
            <br />
            <b>اگر Gemini جواب نداد:</b> این سرویس در ایران مسدود است. اگر سرور ربات داخل ایران باشد،
            خطای دسترسی می‌گیری — در آن صورت گزینه‌ی «سازگار با OpenAI» را انتخاب کن و آدرس یک
            سرویس در دسترس را بگذار.
            <br />
            <b>اعداد را مدل نمی‌سازد.</b> پیش‌بینی و آمار روی همین سرور محاسبه می‌شود؛ مدل فقط تفسیر می‌کند.
          </p>
        </div>
      </Card>

      <Card title="🔐 امنیت ورود به پنل">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle s={s} set={set} k="login_alert_enabled"
                  label="خبردادن در تلگرام وقتی تلاش ورود ناموفق بود" />
          <Toggle s={s} set={set} k="login_captcha_always"
                  label="کد تصویری در هر ورود اجباری باشد" />
          <p className="muted tiny" style={{ margin: "4px 0 0", lineHeight: 2 }}>
            • بدون این گزینه، بررسی امنیتی نامرئی است و کد تصویری فقط پس از چند تلاش ناموفق نشان داده می‌شود.<br />
            • هشدارها برای جلوگیری از سیل پیام، برای هر IP حداکثر هر ۱۰ دقیقه یک بار فرستاده می‌شوند — ولی قفل‌شدن یک IP همیشه خبر می‌دهد.<br />
            • محدودیت نرخ و قفل تدریجی همیشه فعال‌اند و خاموش‌کردنی نیستند.
          </p>
        </div>
      </Card>

      <IpGuardCard />

      <Card title="📢 عضویت اجباری و پشتیبانی">
        <div className="grid" style={{ gap: 8 }}>
          <Toggle s={s} set={set} k="force_channel" label="عضویت اجباری در کانال" />
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Text s={s} set={set} k="channel_username" label="یوزرنیم کانال (بدون @)" ltr />
            <Text s={s} set={set} k="support_username" label="یوزرنیم پشتیبانی" ltr />
          </div>
        </div>
      </Card>

      <Card title="🖥 سرورها و مهاجرت">
        <div className="grid" style={{ gap: 8 }}>
          <Select s={s} set={set} k="default_server_id" label="سرور پیش‌فرض" options={srvOpts} />
          <Toggle s={s} set={set} k="auto_least_loaded_server" label="انتخاب خودکار کم‌بارترین سرور" />
          <Toggle s={s} set={set} k="legacy_sync_enabled" label="سینک کانفیگ‌های قدیمی" />
        </div>
      </Card>

      <Card title="💬 متن‌های ربات">
        <div className="grid" style={{ gap: 8 }}>
          <Area s={s} set={set} k="welcome_message" label="پیام خوش‌آمد" />
          <Toggle s={s} set={set} k="maintenance_mode" label="حالت تعمیر (Maintenance)" />
          <Area s={s} set={set} k="maintenance_message" label="پیام حالت تعمیر" />
          <Area s={s} set={set} k="support_body" label="متن پشتیبانی" />
        </div>
      </Card>

      <Card title="🎨 CSS/JS سفارشی (پیشرفته)">
        <div className="grid" style={{ gap: 8 }}>
          <Area s={s} set={set} k="ui_custom_css" label="CSS سفارشی" mono />
          <Area s={s} set={set} k="ui_custom_js" label="JS سفارشی" mono />
        </div>
      </Card>

      <Card title="🔐 پیشرفته (SSL / دامنه / همه‌ی متن‌ها)"
        sub="تنظیم دامنه و گواهی SSL و بقیه‌ی متن‌های ربات فعلاً در صفحه‌ی کامل قدیمی انجام می‌شود.">
        <a className="btn sm" href={`${BASE}/settings`}>باز کردن تنظیمات کامل (SSL/دامنه) ↗</a>
      </Card>

      <div style={{ position: "sticky", bottom: 12 }}>
        <button className="btn primary" style={{ width: "100%" }} disabled={busy} onClick={save}>
          {busy ? "…" : "💾 ذخیره همه‌ی تنظیمات"}
        </button>
      </div>
    </div>
  );
}
