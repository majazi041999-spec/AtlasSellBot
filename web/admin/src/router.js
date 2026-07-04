import { useEffect, useState, useCallback } from "react";

// Minimal hash router — keeps the URL at `<base>/v2/#/path` so refresh & deep
// links work without any server-side route config (the secret prefix is dynamic).
export function currentPath() {
  const h = window.location.hash.replace(/^#/, "");
  return h || "/dashboard";
}

export function navigate(path) {
  if (currentPath() === path) return;
  window.location.hash = path;
}

export function useRoute() {
  const [path, setPath] = useState(currentPath());
  useEffect(() => {
    const onHash = () => setPath(currentPath());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = useCallback((p) => navigate(p), []);
  return [path, go];
}

// Match "/users/42" against "/users/:id" → { id: "42" } or null.
export function match(pattern, path) {
  const pp = pattern.split("/").filter(Boolean);
  const cp = path.split("/").filter(Boolean);
  if (pp.length !== cp.length) return null;
  const params = {};
  for (let i = 0; i < pp.length; i++) {
    if (pp[i].startsWith(":")) params[pp[i].slice(1)] = decodeURIComponent(cp[i]);
    else if (pp[i] !== cp[i]) return null;
  }
  return params;
}
