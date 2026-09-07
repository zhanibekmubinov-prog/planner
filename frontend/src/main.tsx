import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ConfirmProvider } from "./confirm";
import { ToastProvider } from "./toast";
import { announceUpdate } from "./update";
import { registerSW } from "virtual:pwa-register";

// Обновление без Ctrl+F5: service worker проверяет новую версию при открытии и раз в минуту.
// Когда версия готова, страница НЕ перезагружается сама посреди работы (В3): показываем плашку «Обновить»,
// а автоматически применяем только в скрытой вкладке без несохранённых форм (см. update.ts).
const updateSW = registerSW({
  immediate: true,
  onRegisteredSW(_url, reg) { if (reg) setInterval(() => void reg.update(), 60_000); },
  onNeedRefresh() { announceUpdate(() => void updateSW(true)); },
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
    <ToastProvider>
      <ConfirmProvider>
        <App />
      </ConfirmProvider>
    </ToastProvider>
  </React.StrictMode>
);
