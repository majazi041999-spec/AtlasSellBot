import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
import { getTelegram } from "./telegram.js";

function prepareTelegram() {
  const tg = getTelegram();
  if (!tg) return;
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor("#0b141a"); tg.setBackgroundColor("#0b141a"); } catch (e) {}
}
prepareTelegram();
document.querySelector('script[src="https://telegram.org/js/telegram-web-app.js"]')
  ?.addEventListener("load", prepareTelegram, { once: true });

createRoot(document.getElementById("root")).render(<App />);
