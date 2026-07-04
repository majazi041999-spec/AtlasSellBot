import React, { useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components/ui.jsx";

export default function Login({ onAuthed }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await api.post("/api/login", { username, password });
      onAuthed();
    } catch (e2) {
      setErr("نام کاربری یا رمز عبور اشتباه است");
    } finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card screen" onSubmit={submit}>
        <div className="login-logo">🛡️</div>
        <h2 style={{ textAlign: "center", margin: "0 0 4px" }}>پنل مدیریت اطلس</h2>
        <p className="muted tiny" style={{ textAlign: "center", margin: "0 0 18px" }}>برای ادامه وارد شوید</p>
        <div className="field" style={{ marginBottom: 12 }}>
          <label>نام کاربری</label>
          <input className="inp" value={username} onChange={(e) => setUsername(e.target.value)} dir="ltr" autoFocus />
        </div>
        <div className="field" style={{ marginBottom: 16 }}>
          <label>رمز عبور</label>
          <input className="inp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
        </div>
        {err && <div className="badge b-red" style={{ width: "100%", justifyContent: "center", padding: 9, marginBottom: 12 }}>{err}</div>}
        <button className="btn primary" style={{ width: "100%" }} disabled={busy}>
          {busy ? <Spinner /> : "ورود"}
        </button>
      </form>
    </div>
  );
}
