import React, { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import { useRoute } from "./router.js";
import { Loading, ToastHost } from "./components/ui.jsx";
import Shell from "./components/Shell.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Users from "./pages/Users.jsx";
import Orders from "./pages/Orders.jsx";
import Subscriptions from "./pages/Subscriptions.jsx";
import Servers from "./pages/Servers.jsx";
import Packages from "./pages/Packages.jsx";
import Settings from "./pages/Settings.jsx";
import Proxy from "./pages/Proxy.jsx";
import Discounts from "./pages/Discounts.jsx";
import SubProfiles from "./pages/SubProfiles.jsx";

export default function App() {
  const [authed, setAuthed] = useState(null); // null=checking, false=login, true=in
  const [path, go] = useRoute();
  const [badges, setBadges] = useState({});

  const check = useCallback(() => {
    api.get("/api/me").then(() => setAuthed(true)).catch(() => setAuthed(false));
  }, []);
  useEffect(() => { check(); }, [check]);

  const onBadges = useCallback((b) => setBadges((s) => ({ ...s, ...b })), []);
  const logout = async () => { try { await api.post("/api/logout"); } catch (e) {} setAuthed(false); };

  if (authed === null) return <ToastWrap><Loading /></ToastWrap>;
  if (!authed) return <ToastWrap><Login onAuthed={() => { setAuthed(true); go("/dashboard"); }} /></ToastWrap>;

  const base = "/" + path.split("/").filter(Boolean)[0];
  let page;
  if (base === "/users") page = <Users />;
  else if (base === "/orders") page = <Orders onBadges={onBadges} />;
  else if (base === "/subs") page = <Subscriptions />;
  else if (base === "/servers") page = <Servers />;
  else if (base === "/packages") page = <Packages />;
  else if (base === "/settings") page = <Settings />;
  else if (base === "/proxy") page = <Proxy />;
  else if (base === "/discounts") page = <Discounts />;
  else if (base === "/subprofiles") page = <SubProfiles />;
  else page = <Dashboard onBadges={onBadges} go={go} />;

  return (
    <ToastWrap>
      <Shell path={path} go={go} badges={badges} onLogout={logout}>
        {page}
      </Shell>
    </ToastWrap>
  );
}

function ToastWrap({ children }) {
  return (<>{children}<ToastHost /></>);
}
