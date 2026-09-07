// Слои интерфейса: Esc закрывает только верхний слой (карточка → меню → окно доступа → confirm),
// и общий счётчик «несохранённых форм» — чтобы автообновление приложения не стирало ввод (В3).
import { useEffect, useRef } from "react";

declare global { interface Window { __plannerDirty?: number } }

const stack: symbol[] = [];

/**
 * Зарегистрировать слой и закрывать его по Esc, пока он верхний. Слушатель — в capture-фазе с stopPropagation,
 * поэтому Esc не «пробивает» несколько слоёв за раз (С9). active=false — слой не зарегистрирован.
 */
export function useEscape(handler: () => void, active = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!active) return;
    const id = Symbol("layer");
    stack.push(id);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || stack[stack.length - 1] !== id) return;
      e.stopPropagation(); e.preventDefault();
      ref.current();
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      const i = stack.indexOf(id); if (i >= 0) stack.splice(i, 1);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [active]);
}

export const layerCount = () => stack.length;

/** Держит window.__plannerDirty, пока dirty=true (и снимает при размонтировании). */
export function useDirtyFlag(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    window.__plannerDirty = (window.__plannerDirty ?? 0) + 1;
    return () => { window.__plannerDirty = Math.max(0, (window.__plannerDirty ?? 1) - 1); };
  }, [dirty]);
}
export const hasDirtyForms = () => (window.__plannerDirty ?? 0) > 0;
