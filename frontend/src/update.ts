// Обновление приложения без перезагрузки посреди ввода (В3): новая версия ждёт, пока человек нажмёт «Обновить»,
// либо применяется сама — когда вкладка скрыта и нет несохранённых форм (window.__plannerDirty).
import { useEffect, useState } from "react";
import { hasDirtyForms } from "./layers";

type Listener = (available: boolean) => void;
const listeners = new Set<Listener>();
let available = false;
let applyFn: (() => void) | null = null;

/** Вызывается из main.tsx, когда service worker сообщил о новой версии. */
export function announceUpdate(apply: () => void) {
  applyFn = apply; available = true;
  listeners.forEach((l) => l(true));
  if (document.visibilityState === "hidden" && !hasDirtyForms()) apply();
}
export function applyUpdate() { applyFn?.(); }
/** Ждёт ли уже скачанная новая версия (для «потянуть-обновить»: тогда применяем её, а не просто перечитываем данные). */
export function updatePending(): boolean { return available; }

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && available && !hasDirtyForms()) applyFn?.();
  });
}

/** Есть ли отложенное обновление — для плашки в App. */
export function useUpdateAvailable(): boolean {
  const [v, setV] = useState(available);
  useEffect(() => { listeners.add(setV); return () => { listeners.delete(setV); }; }, []);
  return v;
}
