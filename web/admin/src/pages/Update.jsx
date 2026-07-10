import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

export default function Update() {
  const [info, setInfo] = useState(null);
  const [checking, setChecking] = useState(false);
  const [log, setLog] = useState({ lines: [], running: false, status: "idle" });
  const [applying, setApplying] = useState(false);
  const box = useRef();
  const tmr = useRef();

  const check = () => {
    setChecking(true);
    api.get("/update/check").then((r) => setInfo(r)).catch((e) => setInfo({ error: e.message || "خطا" })).finally(() => setChecking(false));
  };
  useEffect(() => { check(); return () => clearTimeout(tmr.current); }, []);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [log]);

  const pollLog = () => {
    api.get("/update/log").then((l) => {
      setLog(l);
      if (l.running) tmr.current = setTimeout(pollLog, 1500);
      else { setApplying(false); if (l.status === "ok") toast("آپدیت انجام شد ✅ پنل ری‌استارت شد"); }
    }).catch(() => { tmr.current = setTimeout(pollLog, 2000); });
  };

  const apply = async () => {
    if (!confirm("آپدیت اعمال شود؟ پنل چند ثانیه ری‌استارت می‌شود.")) return;
    setApplying(true);
    try {
      await api.post("/update/apply");
      toast("آپدیت شروع شد…");
      setLog({ lines: [], running: true, status: "running" });
      pollLog();
    } catch (e) { toast(e.message || "خطا", "error"); setApplying(false); }
  };

  return (
    <div className="screen grid" style={{ gap: 16 }}>
      <Card title="🔄 به‌روزرسانی پنل" right={<button className="btn xs" disabled={checking} onClick={check}>↻ بررسی مجدد</button>}>
        {!info ? <Loading /> : info.error ? (
          <div style={{ background: "rgba(251,113,133,.1)", border: "1px solid rgba(251,113,133,.4)", borderRadius: 10, padding: 12 }}>{info.error}</div>
        ) : (
          <div className="grid" style={{ gap: 12 }}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              {info.up_to_date
                ? <span className="badge b-green">✅ به‌روز هستید</span>
                : <span className="badge b-yellow">🆕 {info.commits_behind} تغییر جدید موجود است</span>}
              <span className="muted tiny mono">نسخه فعلی: {info.local_hash}</span>
              {!info.up_to_date && <span className="muted tiny mono">→ {info.remote_hash}</span>}
            </div>

            {!info.up_to_date && (info.changelog_md || (info.changelog || []).length > 0) && (
              <div style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
                <b style={{ fontSize: ".85rem" }}>تغییرات جدید:</b>
                {info.changelog_md ? (
                  <pre className="tiny" style={{ whiteSpace: "pre-wrap", margin: "8px 0 0", fontFamily: "inherit", color: "var(--txt2)" }}>{info.changelog_md}</pre>
                ) : (
                  <ul style={{ margin: "8px 0 0", paddingInlineStart: 18, lineHeight: 1.9, fontSize: ".82rem" }}>
                    {info.changelog.slice(0, 20).map((c) => (
                      <li key={c.hash}><span className="mono muted">{c.hash}</span> {c.message} <span className="muted tiny">— {c.author} {c.time}</span></li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {!info.up_to_date && (
              <button className="btn primary" disabled={applying || log.running} onClick={apply}>
                {log.running ? "در حال به‌روزرسانی…" : "⬇️ دریافت و اعمال آپدیت"}
              </button>
            )}
            <p className="muted tiny" style={{ margin: 0 }}>آپدیت کد را از گیت‌هاب می‌گیرد و سرویس را ری‌استارت می‌کند. چند ثانیه پنل در دسترس نخواهد بود.</p>
          </div>
        )}
      </Card>

      {(log.lines || []).length > 0 || log.running ? (
        <Card title="📜 گزارش به‌روزرسانی">
          <div ref={box} className="mono tiny" style={{ background: "rgba(0,0,0,.28)", border: "1px solid var(--line)", borderRadius: 10, padding: 10, maxHeight: 300, overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7 }}>
            {(log.lines || []).join("\n")}{log.running ? "\n⏳ …" : ""}
          </div>
          {log.running && <p className="muted tiny" style={{ marginTop: 8 }}>اگر پنل قطع شد نگران نباش — در حال ری‌استارت است؛ چند ثانیه بعد صفحه را رفرش کن.</p>}
        </Card>
      ) : null}
    </div>
  );
}
