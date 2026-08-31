import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { solvePow } from "../pow.js";

/* Inline SVGs rather than an icon dependency: the login must render before
   anything else is trusted, and it is the one screen that has to work when the
   rest of the bundle does not. */
const IcoUser = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);
const IcoLock = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);
const IcoEye = ({ off }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    {off
      ? <><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" /><path d="M1 1l22 22" /></>
      : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>}
  </svg>
);
const IcoRefresh = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
  </svg>
);
const Shield = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2.5 4 6v6c0 4.7 3.3 8.4 8 9.5 4.7-1.1 8-4.8 8-9.5V6l-8-3.5z" />
    <path d="m8.6 12.2 2.3 2.3 4.5-4.6" />
  </svg>
);

// Messages the SERVER's error codes map to. Anything unmapped falls back to the
// generic credentials message — an attacker should never learn from the copy
// which layer stopped them.
const MESSAGES = {
  invalid_credentials: "نام کاربری یا رمز عبور اشتباه است",
  captcha_wrong: "کد تصویر درست وارد نشده است",
  need_captcha: "برای ادامه باید کد تصویر را وارد کنی",
  challenge_missing: "نشست ورود منقضی شد. دوباره تلاش کن.",
  challenge_expired: "نشست ورود منقضی شد. دوباره تلاش کن.",
  too_fast: "خیلی سریع ارسال شد. یک لحظه صبر کن و دوباره بزن.",
  network: "ارتباط با سرور برقرار نشد",
};

export default function Login({ onAuthed }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [captcha, setCaptcha] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [chal, setChal] = useState(null);        // the current challenge
  const [nonce, setNonce] = useState(null);      // solved proof-of-work
  const [lockLeft, setLockLeft] = useState(0);
  const honey = useRef();                        // the honeypot input
  const abort = useRef();

  /* Fetch a challenge and start solving it immediately. The work happens while
     the admin is still typing, so by the time they press the button it is
     already done and they never wait for it. */
  const arm = useCallback(async () => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setNonce(null);
    try {
      const c = await api.get("/api/login/challenge");
      setChal(c);
      setLockLeft(c.locked_for || 0);
      const n = await solvePow(c.pow.prefix, c.pow.bits, { signal: ctl.signal });
      if (!ctl.signal.aborted) setNonce(n);
    } catch (e) {
      if (!ctl.signal.aborted) setErr(MESSAGES.network);
    }
  }, []);

  useEffect(() => { arm(); return () => abort.current?.abort(); }, [arm]);

  // Lockout countdown.
  useEffect(() => {
    if (lockLeft <= 0) return;
    const t = setTimeout(() => setLockLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [lockLeft]);

  const submit = async (e) => {
    e.preventDefault();
    if (busy || lockLeft > 0) return;
    setErr("");
    setBusy(true);
    try {
      await api.post("/api/login", {
        username,
        password,
        challenge_id: chal?.id,
        pow_nonce: nonce,
        captcha,
        website: honey.current?.value || "",   // must stay empty
      });
      onAuthed();
    } catch (e2) {
      const code = e2?.data?.error || "invalid_credentials";
      if (code === "locked") {
        setLockLeft(e2.data.retry_after || 300);
        setErr("");
      } else {
        setErr(MESSAGES[code] || MESSAGES.invalid_credentials);
      }
      setCaptcha("");
      // Every challenge is single-use on the server, so a retry needs a new
      // one — and the response tells us whether it will now carry a captcha.
      arm();
    } finally { setBusy(false); }
  };

  const locked = lockLeft > 0;
  const ready = !!nonce;
  const mm = String(Math.floor(lockLeft / 60)).padStart(2, "0");
  const ss = String(lockLeft % 60).padStart(2, "0");

  return (
    <div className="login-wrap">
      <div className="login-grid" />
      <form className="login-card" onSubmit={submit} noValidate>
        <div className="lg-mark"><Shield /></div>
        <h1 className="lg-title">پنل مدیریت اطلس</h1>
        <p className="lg-sub">برای ادامه وارد حساب مدیریت شوید</p>

        <div role="alert" aria-live="assertive">
          {err && (
            <div className="lg-error" key={err}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" /><path d="M12 8v5M12 16h.01" strokeLinecap="round" />
              </svg>
              <span>{err}</span>
            </div>
          )}
        </div>

        {locked && (
          <div className="lg-error warn">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" strokeLinecap="round" />
            </svg>
            {/* The digits tick every second — announcing each tick would make the
                page unusable with a screen reader, so only the sentence is live. */}
            <span>تلاش‌های ناموفق زیاد بود. تا{" "}
              <bdi dir="ltr" aria-live="off" style={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>
                {mm}:{ss}
              </bdi>{" "}دیگر صبر کن.
            </span>
          </div>
        )}

        <div className="lg-field">
          <label htmlFor="lg-u">نام کاربری</label>
          <div className="lg-input-wrap">
            <span className="lg-ico"><IcoUser /></span>
            <input id="lg-u" name="username" className="lg-input" value={username} autoFocus
                   autoComplete="username" disabled={locked}
                   onChange={(e) => setUsername(e.target.value)} />
          </div>
        </div>

        <div className="lg-field">
          <label htmlFor="lg-p">رمز عبور</label>
          <div className="lg-input-wrap">
            <span className="lg-ico"><IcoLock /></span>
            <input id="lg-p" name="password" className="lg-input" type={show ? "text" : "password"}
                   value={password} autoComplete="current-password" disabled={locked}
                   onChange={(e) => setPassword(e.target.value)} />
            <button type="button" className="lg-eye" disabled={locked}
                    aria-pressed={show}
                    aria-label={show ? "پنهان کردن رمز" : "نمایش رمز"}
                    onClick={() => setShow((v) => !v)}>
              <IcoEye off={show} />
            </button>
          </div>
        </div>

        {/* Honeypot. Off-screen rather than display:none, because some bots skip
            hidden fields but almost none skip a positioned one. Never focusable
            or announced, so a human — including a screen-reader user — cannot
            fill it by accident. */}
        <input ref={honey} name="website" tabIndex={-1} autoComplete="off" aria-hidden="true"
               style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }} />

        {/* The slot is always mounted so revealing the captcha animates its
            height open instead of snapping the whole centred card upward. */}
        <div className={"lg-captcha-slot" + (chal?.captcha && !locked ? " open" : "")}>
          <div className="lg-captcha">
            {chal?.captcha && (
              <>
                <img className="lg-captcha-img" src={chal.captcha.image} alt="کد تصویری" />
                <div className="lg-captcha-row">
                  <div className="lg-input-wrap">
                    <input className="lg-input" value={captcha} maxLength={12}
                           placeholder={"·".repeat(chal.captcha.length)}
                           aria-label="کد داخل تصویر"
                           onChange={(e) => setCaptcha(e.target.value)} />
                  </div>
                  <button type="button" className="lg-refresh" onClick={arm} aria-label="تصویر تازه">
                    <IcoRefresh />
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        <button className="lg-submit" disabled={busy || locked || !ready}>
          {busy ? "در حال بررسی…" : locked ? "قفل موقت" : !ready ? "آماده‌سازی…" : "ورود"}
        </button>

        <div className={"lg-guard " + (ready ? "ok" : "work")}>
          <span className="lg-guard-dot" />
          <span>
            {ready
              ? "بررسی امنیتی خودکار انجام شد — نیازی به کاری از طرف شما نیست"
              : "در حال انجام بررسی امنیتی خودکار…"}
          </span>
        </div>

        <p className="lg-foot">این صفحه با محدودیت نرخ و قفل تدریجی محافظت می‌شود</p>
      </form>
    </div>
  );
}
