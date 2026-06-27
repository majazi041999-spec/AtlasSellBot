import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor("#0b0f1a"); tg.setBackgroundColor("#0b0f1a"); } catch (e) {}
}

createRoot(document.getElementById("root")).render(<App />);
