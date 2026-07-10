import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

const STEPS = ["تنظیمات پایه", "نصب و راه‌اندازی", "تست اتصال", "لینک‌ها", "اسپانسر (کانال)", "آمار زنده"];

function Stepper({ step, go }) {
  return (
    <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 4 }}>
      {STEPS.map((s, i) => (
        <button key={i} onClick={() => go(i)} className="btn xs"
          style={{ background: i === step ? "var(--p2)" : "rgba(255,255,255,.05)", color: i === step ? "#fff" : "var(--txt3)" }}>
          {i + 1}. {s}
        </button>
      ))}
    </div>
  );
}

function LogBox({ running, lines, status }) {
  const box = useRef();
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines]);
  if (!(lines || []).length && !running) return null;
  return (
    <div ref={box} className="mono tiny" style={{ background: "rgba(0,0,0,.28)", border: "1px solid var(--line)",
      borderRadius: 10, padding: 10, maxHeight: 240, overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7, marginTop: 10 }}>
      {(lines || []).join("\n")}{running ? "\n⏳ …" : ""}
    </div>
  );
}

function Copy({ text, label }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn xs" disabled={!text} onClick={() => {
      navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); });
    }}>{done ? "✓ کپی شد" : label || "کپی"}</button>
  );
}

export default function Proxy() {
  const [d, setD] = useState(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState("");
  const [cfg, setCfg] = useState({ port: 443, domain: "www.cloudflare.com", host: "", tag: "" });
  const [log, setLog] = useState({ lines: [], running: false, status: "idle" });
  const [testOut, setTestOut] = useState("");
  const tmr = useRef();

  const load = () => api.get("/api/proxy").then((r) => {
    setD(r);
    setCfg((c) => ({ ...c, port: r.config.port, domain: r.config.domain, host: r.config.host, tag: r.config.tag }));
  }).catch(() => setD({ error: true }));
  useEffect(() => { load(); return () => clearTimeout(tmr.current); }, []);

  // Poll the install log while a job runs.
  const pollLog = () => {
    api.get("/api/proxy/install/log").then((l) => {
      setLog(l);
      if (l.running) { tmr.current = setTimeout(pollLog, 1200); }
      else { load(); if (l.status === "ok") toast("عملیات با موفقیت انجام شد ✅"); }
    }).catch(() => {});
  };

  const save = async (extra = {}) => {
    setBusy("save");
    try {
      const r = await api.post("/api/proxy/save", { ...cfg, ...extra });
      toast("ذخیره شد ✅");
      await load();
      return r;
    } catch (e) { toast(e.message || "خطا", "error"); } finally { setBusy(""); }
  };

  const install = async (apply = false) => {
    setBusy("install");
    try {
      await save();
      await api.post("/api/proxy/install", { apply });
      setLog({ lines: [], running: true, status: "running" });
      pollLog();
      if (!apply) setStep(1);
    } catch (e) { toast(e.message || "شروع نصب ناموفق بود", "error"); } finally { setBusy(""); }
  };

  const runTest = async () => {
    setBusy("test"); setTestOut("در حال تست…");
    try { const r = await api.get("/api/proxy/test"); setTestOut(r.output || ""); toast(r.success ? "تست موفق ✅" : "تست ناموفق ❌", r.success ? "success" : "error"); }
    catch (e) { setTestOut(e.message || "خطا"); } finally { setBusy(""); }
  };

  if (!d) return <Loading />;
  const st = d.status || {};
  const links = d.links || {};

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="🛰 پروکسی تلگرام (MTProto) با اسپانسر"
        sub="ساخت مرحله‌به‌مرحله؛ برای تبلیغ کانال از طریق کانال اسپانسری پروکسی">
        <Stepper step={step} go={setStep} />
        <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <span className={"badge " + (st.active ? "b-green" : "b-red")}>{st.active ? "🟢 فعال" : "🔴 غیرفعال"}</span>
          <span className="badge b-blue">پورت {d.config.port}</span>
          {st.active && <span className="badge b-purple">🔌 {st.connections} اتصال آنلاین</span>}
          {d.config.tag ? <span className="badge b-green">اسپانسر تنظیم شده</span> : null}
        </div>
      </Card>

      {step === 0 && (
        <Card title="۱) تنظیمات پایه">
          <p className="muted tiny" style={{ marginTop: 0 }}>
            پروکسی MTProto یک راه ساده و پرسرعت برای اتصال کاربران به تلگرام است. با «کانال اسپانسر»،
            کانال شما هنگام اتصال به کاربر پیشنهاد می‌شود — عالی برای تبلیغات.
          </p>
          <div className="grid" style={{ gap: 10 }}>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><label>آدرس سرور (IP یا دامنه)</label>
                <input className="inp" value={cfg.host} dir="ltr" placeholder="مثال: 1.2.3.4"
                  onChange={(e) => setCfg({ ...cfg, host: e.target.value })} />
                <p className="muted tiny" style={{ margin: "4px 0 0" }}>همان IP عمومی سرور که کاربران به آن وصل می‌شوند.</p>
              </div>
              <div className="field"><label>پورت</label>
                <input className="inp" type="number" value={cfg.port} dir="ltr"
                  onChange={(e) => setCfg({ ...cfg, port: e.target.value })} />
                <p className="muted tiny" style={{ margin: "4px 0 0" }}>۴۴۳ بهترین است، ولی اگر پنل/سرویس دیگری روی ۴۴۳ است پورت آزاد دیگری بگذار.</p>
              </div>
            </div>
            <div className="field"><label>دامنه تقلید (fake-TLS SNI)</label>
              <input className="inp" value={cfg.domain} dir="ltr"
                onChange={(e) => setCfg({ ...cfg, domain: e.target.value })} />
              <p className="muted tiny" style={{ margin: "4px 0 0" }}>
                ترافیک پروکسی شبیه اتصال به این دامنه دیده می‌شود (مقاومت در برابر فیلترینگ). پیش‌فرض عالی است؛ می‌توانی www.cloudflare.com یا یک دامنه معتبر دیگر بگذاری.
              </p>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn primary" disabled={busy === "save"} onClick={() => save().then(() => setStep(1))}>💾 ذخیره و ادامه ›</button>
            </div>
          </div>
        </Card>
      )}

      {step === 1 && (
        <Card title="۲) نصب و راه‌اندازی">
          <p className="muted tiny" style={{ marginTop: 0 }}>
            با زدن دکمه زیر، پروکسی (mtg) روی سرور نصب، سرویس دائمی ساخته، پورت در فایروال باز و اجرا می‌شود.
            همه‌چیز خودکار است؛ فقط چند ثانیه صبر کن.
          </p>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button className="btn primary" disabled={busy === "install" || log.running} onClick={() => install(false)}>
              {log.running ? "در حال نصب…" : "🚀 نصب و راه‌اندازی"}
            </button>
            {d.config.has_secret && <button className="btn" disabled={log.running} onClick={() => install(true)}>♻️ اعمال تغییرات و ری‌استارت</button>}
          </div>
          <LogBox running={log.running} lines={log.lines} status={log.status} />
          {!log.running && log.status === "ok" && (
            <button className="btn success sm" style={{ marginTop: 10 }} onClick={() => setStep(2)}>مرحله بعد: تست ›</button>
          )}
        </Card>
      )}

      {step === 2 && (
        <Card title="۳) تست اتصال">
          <p className="muted tiny" style={{ marginTop: 0 }}>تست می‌کند که سرویس فعال است، پورت گوش می‌دهد و اتصال TCP برقرار می‌شود.</p>
          <button className="btn primary" disabled={busy === "test"} onClick={runTest}>🧪 اجرای تست</button>
          {testOut ? <pre className="mono tiny" style={{ background: "rgba(0,0,0,.28)", border: "1px solid var(--line)", borderRadius: 10, padding: 10, marginTop: 10, whiteSpace: "pre-wrap" }}>{testOut}</pre> : null}
          <button className="btn success sm" style={{ marginTop: 10 }} onClick={() => setStep(3)}>مرحله بعد: لینک‌ها ›</button>
        </Card>
      )}

      {step === 3 && (
        <Card title="۴) لینک‌های اتصال">
          {!d.config.host ? (
            <p className="muted">اول در مرحله ۱ «آدرس سرور» را وارد کن تا لینک ساخته شود.</p>
          ) : !links.tg ? (
            <p className="muted">لینکی نیست — ابتدا نصب را کامل کن.</p>
          ) : (
            <div className="grid" style={{ gap: 12 }}>
              <div className="field"><label>لینک اتصال (t.me)</label>
                <div className="row" style={{ gap: 8 }}>
                  <input className="inp mono tiny" readOnly value={links.https} dir="ltr" />
                  <Copy text={links.https} />
                </div>
              </div>
              <div className="field"><label>لینک tg://</label>
                <div className="row" style={{ gap: 8 }}>
                  <input className="inp mono tiny" readOnly value={links.tg} dir="ltr" />
                  <Copy text={links.tg} />
                </div>
              </div>
              <p className="muted tiny" style={{ margin: 0 }}>لینک t.me را در کانال/به کاربران بده؛ با یک کلیک پروکسی در تلگرامشان اضافه می‌شود.</p>
              <button className="btn success sm" onClick={() => setStep(4)}>مرحله بعد: اسپانسر ›</button>
            </div>
          )}
        </Card>
      )}

      {step === 4 && (
        <Card title="۵) کانال اسپانسر (تبلیغ کانال)">
          <div className="grid" style={{ gap: 10 }}>
            <div style={{ background: "rgba(52,211,153,.06)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
              <b>راهنمای گرفتن تگ اسپانسر از تلگرام:</b>
              <ol style={{ margin: "8px 0 0", paddingInlineStart: 18, lineHeight: 2, fontSize: ".85rem" }}>
                <li>در تلگرام به <b>@MTProxybot</b> پیام بده و <span className="mono">/newproxy</span> را بفرست.</li>
                <li>وقتی «server:port» خواست، بفرست: <span className="mono" dir="ltr">{(d.config.host || "IP") + ":" + d.config.port}</span></li>
                <li>وقتی «secret» خواست، سکرت پروکسی را بفرست (از لینک tg بعد از <span className="mono">secret=</span>).</li>
                <li>حالا <span className="mono">/tag</span> را بفرست و پروکسی‌ات را انتخاب کن؛ ربات یک <b>تگ</b> ۳۲ کاراکتری می‌دهد.</li>
                <li>آن تگ را این‌جا بگذار و «ذخیره و اعمال» بزن.</li>
              </ol>
            </div>
            <div className="field"><label>تگ اسپانسر (۳۲ کاراکتر hex)</label>
              <input className="inp mono" value={cfg.tag} dir="ltr" placeholder="مثال: 3f9b1c…"
                onChange={(e) => setCfg({ ...cfg, tag: e.target.value })} />
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn primary" disabled={busy === "install" || log.running} onClick={() => install(true)}>💾 ذخیره و اعمال اسپانسر</button>
              {cfg.tag && <button className="btn" onClick={() => { setCfg({ ...cfg, tag: "" }); save({ tag: "" }).then(() => install(true)); }}>حذف اسپانسر</button>}
            </div>
            <LogBox running={log.running} lines={log.lines} status={log.status} />
          </div>
        </Card>
      )}

      {step === 5 && (
        <Card title="۶) آمار زنده"
          right={<button className="btn xs" onClick={load}>↻ بروزرسانی</button>}>
          <div className="grid stat-grid">
            <div style={{ background: "rgba(52,211,153,.08)", border: "1px solid var(--line)", borderRadius: 14, padding: 16 }}>
              <div style={{ fontSize: "1.8rem", fontWeight: 800, color: st.active ? "#34d399" : "var(--red,#f43f5e)" }}>{st.connections || 0}</div>
              <div className="muted tiny">اتصال آنلاین همین حالا</div>
            </div>
            <div style={{ background: "rgba(124,111,255,.08)", border: "1px solid var(--line)", borderRadius: 14, padding: 16 }}>
              <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>{st.active ? "فعال ✅" : "غیرفعال ❌"}</div>
              <div className="muted tiny">وضعیت سرویس (پورت {st.port || d.config.port})</div>
            </div>
          </div>
          <p className="muted tiny" style={{ marginTop: 10 }}>
            «اتصال آنلاین» تعداد اتصال‌های TCP برقرار روی پورت پروکسی است (تعداد کاربران وصل). برای مصرف دقیق حجم،
            به شمارنده‌های فایروال سرور نیاز است که در نسخه‌های بعدی اضافه می‌شود.
          </p>
          <button className="btn danger sm" style={{ marginTop: 12 }} onClick={() => {
            if (confirm("سرویس پروکسی حذف شود؟")) api.post("/api/proxy/uninstall").then(() => { toast("در حال حذف…"); setLog({ lines: [], running: true, status: "running" }); pollLog(); });
          }}>🗑 حذف پروکسی</button>
        </Card>
      )}
    </div>
  );
}
