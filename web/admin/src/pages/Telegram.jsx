import React, { useEffect, useState } from "react";
import { api, BASE } from "../api.js";
import { Card, Loading, toast } from "../components/ui.jsx";

/** A full Telegram client inside the panel.
 *
 *  It is our own build of Telegram Web A, served under <secret>/tg/ with its
 *  traffic relayed through our server (docs/telegram-web.md), so it works from
 *  Iran without a VPN. The owner logs in inside it exactly as on
 *  web.telegram.org, and the session stays in this browser, never on the server.
 *  Telegram requires every client to carry its own api_id/api_hash; the owner
 *  creates one once at my.telegram.org and enters it below.
 */
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
      <Card title="✈️ راه‌اندازی تلگرام" sub="فقط یک بار لازم است">
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
            <button className="btn primary" disabled={busy || !apiId} onClick={save}>ذخیره</button>
            {onCancel && <button className="btn" onClick={onCancel}>انصراف</button>}
          </div>
        </div>
      </Card>
    </div>
  );
}

export default function Telegram() {
  const [cfg, setCfg] = useState(null);
  const [editing, setEditing] = useState(false);
  const load = () => api.get("/api/tg/settings").then(setCfg).catch(() => setCfg({ error: true }));
  useEffect(() => { load(); }, []);

  if (!cfg) return <Loading />;
  if (cfg.error) return <Card title="✈️ تلگرام"><div className="muted">دریافت تنظیمات ناموفق بود.</div></Card>;
  if (!cfg.configured || editing) {
    return <Setup current={cfg} onSaved={() => { setEditing(false); load(); }}
                  onCancel={cfg.configured ? () => setEditing(false) : null} />;
  }

  const src = `${BASE}/tg/`;
  return (
    <div className="screen tg-screen">
      <div className="row tg-bar">
        <b>✈️ تلگرام</b>
        <span className="muted tiny">نشست تلگرامت فقط در همین مرورگر ذخیره می‌شود، نه روی سرور.</span>
        <div className="row" style={{ gap: 8, marginInlineStart: "auto" }}>
          <a className="btn xs" href={src} target="_blank" rel="noopener noreferrer">↗ تب جدید</a>
          <button className="btn xs" onClick={() => setEditing(true)}>⚙️ api_id</button>
        </div>
      </div>
      <iframe className="tg-frame" src={src} title="Telegram"
              allow="clipboard-read; clipboard-write; microphone; camera; fullscreen; autoplay; display-capture" />
    </div>
  );
}
