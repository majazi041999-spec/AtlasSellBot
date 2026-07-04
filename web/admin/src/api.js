// The server injects window.__PANEL_BASE__ = "/<secret>" into index.html so the
// secret prefix is never baked into the committed bundle. API lives at
// `<base>/api/...`; legacy action endpoints live at `<base>/...`.
export const BASE = (typeof window !== "undefined" && window.__PANEL_BASE__) || "";

async function request(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${BASE}${path}`, opts);
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (r.status === 401) {
    const e = new Error("unauthorized");
    e.unauthorized = true;
    throw e;
  }
  if (!r.ok || (data && data.error)) {
    const e = new Error((data && data.error) || `HTTP ${r.status}`);
    e.data = data; e.status = r.status;
    throw e;
  }
  return data ?? {};
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),
  // legacy action endpoints (existing panel) — JSON in, {success:true} out
  action: (path, body) => request(path, { method: "POST", body }),
};

export const fmt = (n) => Number(n || 0).toLocaleString("en-US");
export const fmtFa = (n) => Number(n || 0).toLocaleString("fa-IR");
