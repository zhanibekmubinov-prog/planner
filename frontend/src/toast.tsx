// Тост после удаления: «Направление «X» удалено · Отменить» (10 с). Один тост за раз, внизу слева, доступен с клавиатуры.
// Использование: const toast = useToast(); toast("Задача удалена", { action: "Отменить", onAction: () => restore() });
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ToastOptions = { action?: string; onAction?: () => void | Promise<void>; ms?: number };
type Show = (text: string, options?: ToastOptions) => void;

const Ctx = createContext<Show>(() => {});
export const useToast = (): Show => useContext(Ctx);

type Item = { id: number; text: string; options: ToastOptions; until: number };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [item, setItem] = useState<Item | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const seq = useRef(0);

  const dismiss = useCallback(() => { if (timer.current) window.clearTimeout(timer.current); timer.current = null; setItem(null); setBusy(false); }, []);
  const show = useCallback<Show>((text, options = {}) => {
    const ms = options.ms ?? 10_000;
    if (timer.current) window.clearTimeout(timer.current);
    setBusy(false);
    setItem({ id: ++seq.current, text, options, until: Date.now() + ms });
    timer.current = window.setTimeout(() => { timer.current = null; setItem(null); }, ms);
  }, []);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  async function act() {
    if (!item?.options.onAction || busy) return;
    setBusy(true);
    try { await item.options.onAction(); } finally { dismiss(); }
  }

  return (
    <Ctx.Provider value={show}>
      {children}
      {item && (
        <div className="toast" role="status" aria-live="polite" key={item.id} style={{ ["--ms" as string]: `${item.options.ms ?? 10_000}ms` }}>
          <span className="toast-text">{item.text}</span>
          {item.options.action && <button className="toast-action" onClick={act} disabled={busy}>{busy ? "…" : item.options.action}</button>}
          <button className="toast-close" onClick={dismiss} aria-label="Скрыть">×</button>
          <span className="toast-life" aria-hidden="true" />
        </div>
      )}
    </Ctx.Provider>
  );
}
