import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

export default function MiniApp() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [cert, setCert] = useState({ lines: [], running: false, status: "idle" });
  const box = useRef();
  const tmr = useRef();

  const load = () => api.get("/api/miniapp").then(setData).catch(() => setData({ settings: {} }));
  useEffect(() => { load(); return () => clearTimeout(tmr.current); }, []);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [cert]);

  const pollCert = () => {
    api.get("/miniapp/cert/log").then((l) => {
      setCert(l);
      if (l.running) tmr.current = setTimeout(pollCert, 1500);
      else if (l.status === "ok") { toast("گواهی صادر شد ✅"); load(); }
      else if (l.status === "error") toast("صدور گواهی ناموفق بود", "error");
    }).catch(() => { tmr.current = setTimeout(pollCert, 2000); });
  };

  const save = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    setBusy(true);
    try {
      await api.form("/miniapp/settings", {
        miniapp_enabled: f.get("enabled") ? "1" : "0",
        miniapp_title: f.get("title") || "",
        miniapp_logo: f.get("logo") || "🌐",
        miniapp_domain: f.get("domain") || "",
      });
      toast("ذخیره شد ✅");
      load();
    } catch (err) { toast(err.message || "خطا", "error"); } finally { setBusy(false); }
  };

  const issueCert = async () => {
    const domain = (document.getElementById("ma-domain")?.value || "").trim();
    const email = (document.getElementById("ma-email")?.value || "").trim();
    if (!domain) { toast("اول دامنه مینی‌اپ را وارد کن", "error"); return; }
    if (!confirm(`برای ${domain} گواهی SSL گرفته شود؟\nدامنه باید از قبل به IP همین سرور اشاره کند.`)) return;
    try {
      await api.form("/miniapp/cert/start", { miniapp_domain: domain, cert_email: email });
      toast("صدور گواهی شروع شد…");
      setCert({ lines: [], running: true, status: "running" });
      pollCert();
    } catch (e) { toast(e.message || "خطا", "error"); }
  };

  if (!data) return <Loading />;
  const s = data.settings || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="📱 مینی‌اپ تلگرام" sub="نسخه‌ی وب سرویس که داخل خود تلگرام باز می‌شود">
        <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          {String(s.miniapp_enabled) === "1"
            ? <span className="badge b-green">✅ فعال</span>
            : <span className="badge b-gray">خاموش</span>}
          {data.built
            ? <span className="badge b-green">بیلد موجود است</span>
            : <span className="badge b-yellow">⚠️ هنوز build نشده</span>}
          {data.app_url && <a className="btn xs ghost" href={data.app_url} target="_blank" rel="noreferrer">باز کردن ↗</a>}
        </div>

        {!data.built && (
          <div style={{ background: "rgba(251,191,36,.1)", border: "1px solid rgba(251,191,36,.35)",
                        borderRadius: 12, padding: 12, marginBottom: 12 }}>
            <b>مینی‌اپ هنوز build نشده است.</b>
            <p className="muted tiny" style={{ margin: "6px 0 0" }}>روی سرور این را اجرا کن:</p>
            <code className="mono" style={{ direction: "ltr", display: "block", marginTop: 6 }}>
              npm --prefix web/miniapp run build
            </code>
          </div>
        )}

        <form onSubmit={save} className="grid" style={{ gap: 10 }}>
          <label className="row" style={{ gap: 8, cursor: "pointer" }}>
            <input type="checkbox" name="enabled" defaultChecked={String(s.miniapp_enabled) === "1"} />
            <span>مینی‌اپ برای کاربران فعال باشد</span>
          </label>
          <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            <div className="field"><label>عنوان</label>
              <input className="inp" name="title" defaultValue={s.miniapp_title || ""} placeholder="اطلس" /></div>
            <div className="field"><label>لوگو (ایموجی)</label>
              <input className="inp" name="logo" defaultValue={s.miniapp_logo || "🌐"} /></div>
          </div>
          <div className="field"><label>دامنه مینی‌اپ</label>
            <input className="inp mono" id="ma-domain" name="domain" dir="ltr"
                   defaultValue={s.miniapp_domain || ""} placeholder="app.example.com" />
            <p className="muted tiny" style={{ margin: "5px 0 0" }}>
              تلگرام فقط دامنه‌ی HTTPS معتبر را باز می‌کند. این دامنه باید به IP همین سرور اشاره کند.
            </p>
          </div>
          <button className="btn primary" disabled={busy}>{busy ? "…" : "💾 ذخیره"}</button>
        </form>
      </Card>

      <Card title="🔐 گواهی SSL مینی‌اپ" sub="صدور گواهی Let's Encrypt و ساخت vhost روی پورت ۴۴۳">
        <div className="grid" style={{ gap: 10 }}>
          <div className="field"><label>ایمیل برای Let's Encrypt</label>
            <input className="inp mono" id="ma-email" dir="ltr" defaultValue={s.cert_email || ""} placeholder="you@example.com" /></div>
          <button className="btn primary" disabled={cert.running} onClick={issueCert}>
            {cert.running ? "در حال صدور…" : "🔐 صدور گواهی"}
          </button>
        </div>
        {(cert.lines || []).length > 0 && (
          <div ref={box} className="mono tiny" style={{ marginTop: 12, background: "rgba(0,0,0,.28)",
                 border: "1px solid var(--line)", borderRadius: 10, padding: 10, maxHeight: 300,
                 overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7, direction: "ltr", textAlign: "left" }}>
            {(cert.lines || []).join("\n")}{cert.running ? "\n⏳ …" : ""}
          </div>
        )}
        <p className="muted tiny" style={{ marginTop: 10 }}>
          قبل از زدن این دکمه مطمئن شو رکورد A دامنه به IP این سرور اشاره می‌کند، وگرنه صدور گواهی رد می‌شود.
        </p>
      </Card>
    </div>
  );
}
