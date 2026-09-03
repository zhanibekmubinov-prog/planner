import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ConfirmProvider } from "./confirm";
import { registerSW } from "virtual:pwa-register";

// Обновление без Ctrl+F5: service worker проверяет новую версию при открытии и раз в минуту,
// а когда новая версия встала — страница перезагружается один раз сама.
const updateSW = registerSW({
  immediate: true,
  onRegisteredSW(_url, reg) { if (reg) setInterval(() => void reg.update(), 60_000); },
  onNeedRefresh() { void updateSW(true); },
});
let reloading = false;
navigator.serviceWorker?.addEventListener("controllerchange", () => { if (!reloading) { reloading = true; window.location.reload(); } });
import "@fontsource/rubik/400.css";
import "@fontsource/rubik/500.css";
import "@fontsource/rubik/600.css";
import "@fontsource/source-serif-4/600.css";
import "@fontsource/source-serif-4/700.css";
import "@fontsource/source-code-pro/400.css";
import "@fontsource/source-code-pro/500.css";
import "@fontsource/michroma/400.css";

document.documentElement.dataset.theme = "journal";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfirmProvider>
      <App />
    </ConfirmProvider>
  </React.StrictMode>
);
