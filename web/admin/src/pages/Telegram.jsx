import React, { useEffect, useState } from "react";
import { api, BASE } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

/** Telegram inside the panel.
 *
 *  The app itself is our own build of Telegram Web A at <secret>/tg/, opened
 *  full-window (the «تلگرام» menu links straight to it, and Chrome can install
 *  it as a desktop app). Its traffic is relayed through our server
 *  (docs/telegram-web.md), so it works from Iran without a VPN, and the
 *  Telegram session stays in the owner's browser.
 *
 *  This page only exists for the one-time setup (#/telegram/setup): Telegram
 *  requires every client to carry its own api_id/api_hash. Landing on
 *  #/telegram (e.g. after the panel login that /tg/ redirected to) goes
 *  straight on to the app.
 */
const APP_URL = `${BASE}/tg/`;

function Setup({ current, onSaved, onCancel }) {
  const [apiId, setApiId] = useState(current?.api_id || "");
  const [apiHash, setApiHash] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await api.post("/api/tg/settings", { api_id: apiId.trim(), api_hash: apiHash.trim() });
      toast("ذخیره شد ✅");
      onSaved();
    } catch (e) {
      toast(e.message || "ذخیره نشد", "error");
    } finally { setBusy(false); }
  };

  return (
    <div className="screen grid" style={{ gap: 18, maxWidth: 720 }}>
      <Card title="✈️ تنظیم تلگرام" sub="فقط یک بار لازم است">
        <div className="grid" style={{ gap: 10, lineHeight: 1.9 }}>
          <div>تلگرام برای هر برنامه‌ی تلگرامی یک شناسه‌ی اختصاصی می‌خواهد. یک بار بساز و این‌جا وارد کن:</div>
          <ol style={{ margin: 0, paddingInlineStart: 20 }}>
            <li>با فیلترشکن برو به <b className="mono">my.telegram.org</b> و با شماره‌ی خودت وارد شو.</li>
            <li><b>API development tools</b> را بزن و یک اپ بساز (نام دلخواه، Platform: <b>Web</b>).</li>
            <li><b className="mono">App api_id</b> و <b className="mono">App api_hash</b> را همین‌جا وارد کن.</li>
          </ol>
          <div className="field">
            <label>api_id</label>
            <input className="inp mono" dir="ltr" inputMode="numeric" value={apiId}
                   onChange={(e) => setApiId(e.target.value.replace(/\D/g, ""))} placeholder="1234567" />
          </div>
          <div className="field">
            <label>api_hash{current?.hash_set ? " (خالی بگذاری، همان قبلی می‌ماند)" : ""}</label>
            <input className="inp mono" dir="ltr" value={apiHash} autoComplete="off"
                   onChange={(e) => setApiHash(e.target.value.trim())} placeholder="0123456789abcdef0123456789abcdef" />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn primary" disabled={busy || !apiId} onClick={save}>ذخیره و باز کردن تلگرام</button>
            {onCancel && <button className="btn" onClick={onCancel}>باز کردن تلگرام بدون تغییر</button>}
          </div>
        </div>
      </Card>
    </div>
  );
}

export default function Telegram({ path = "" }) {
  const wantsSetup = path.startsWith("/telegram/setup");
  const [cfg, setCfg] = useState(null);
  const openApp = () => window.location.replace(APP_URL);

  useEffect(() => { api.get("/api/tg/settings").then(setCfg).catch(() => setCfg({ error: true })); }, []);
  useEffect(() => { if (cfg?.configured && !wantsSetup) openApp(); }, [cfg, wantsSetup]);

  if (!cfg) return <Loading />;
  if (cfg.error) return <Card title="✈️ تلگرام"><div className="muted">دریافت تنظیمات ناموفق بود.</div></Card>;
  if (!cfg.configured || wantsSetup) {
    return <Setup current={cfg} onSaved={openApp} onCancel={cfg.configured ? openApp : null} />;
  }
  return <Loading />;   // on the way to the app
}
