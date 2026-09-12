// Launch data is only a transport value. The server still verifies Telegram's
// HMAC, user and expiry for every request; never trust a decoded user here.
export const getTelegram = () => window.Telegram?.WebApp;

export function initData() {
  const sdkData = getTelegram()?.initData;
  if (sdkData) return sdkData;
  // Desktop may reach our host while telegram.org (the SDK host) is blocked.
  // Telegram supplies the same signed string in the launch fragment. Decode
  // that outer parameter exactly once, preserving its inner signed values.
  return new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData") || "";
}

export function closeOrReload() {
  const app = getTelegram();
  if (typeof app?.close === "function") {
    try { app.close(); return; } catch (_) { /* Reload below. */ }
  }
  window.location.reload();
}
