import React from "react";

// A single stroke language keeps navigation and actions consistent at small sizes.
const paths = {
  home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" /></>,
  services: <><rect x="4" y="3" width="16" height="7" rx="2" /><rect x="4" y="14" width="16" height="7" rx="2" /><path d="M8 6.5h.01M8 17.5h.01M12 6.5h4M12 17.5h4" /></>,
  buy: <><path d="m13 2-9 12h7l-1 8 10-12h-7Z" /></>,
  wallet: <><path d="M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h15v11H5a3 3 0 0 1-3-3V6" /><path d="M21 12h-5a2 2 0 0 0 0 4h5Z" /></>,
  referral: <><rect x="3" y="8" width="18" height="4" rx="1" /><path d="M5 12v9h14v-9M12 8v13" /><path d="M12 8H8a3 3 0 1 1 3-3l1 3Zm0 0h4a3 3 0 1 0-3-3l-1 3Z" /></>,
  rep: <><path d="M4 21V7h6V3h10v18M2 21h20M7 11v2m0 3v2m7-11h2m-2 4h2m-2 4h2m-3 6v-3h4v3" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18M5 6.5h14M5 17.5h14" /></>,
  arrow: <path d="M19 12H5m6-6-6 6 6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  support: <><path d="M4 14v-3a8 8 0 0 1 16 0v3M20 17v1a3 3 0 0 1-3 3h-4" /><rect x="2" y="11" width="4" height="7" rx="2" /><rect x="18" y="11" width="4" height="7" rx="2" /></>,
  chart: <><path d="M4 3v17h17M8 15v-4m5 4V7m5 8v-6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3" /></>,
  edit: <><path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z" /></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 13-2l2 3M4 16l2 3a8 8 0 0 0 13-2" /></>,
  devices: <><rect x="2" y="4" width="14" height="11" rx="2" /><path d="M9 15v4H5m4 0h3" /><rect x="16" y="10" width="6" height="11" rx="1" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>,
  upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" /></>,
  lock: <><rect x="4" y="10" width="16" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>,
};

export default function Icon({ name, className = "" }) {
  return <svg className={`icon ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[name] || paths.globe}</svg>;
}
