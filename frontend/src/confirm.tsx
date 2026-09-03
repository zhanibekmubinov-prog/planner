// Собственный диалог подтверждения вместо системного window.confirm.
// Использование: const confirm = useConfirm(); if (await confirm("Удалить?", { danger: true })) …
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

type Options = { title?: string; okLabel?: string; cancelLabel?: string; danger?: boolean };
type Ask = (message: string, options?: Options) => Promise<boolean>;

const Ctx = createContext<Ask>(() => Promise.resolve(false));

export function useConfirm(): Ask {
  return useContext(Ctx);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ message: string; options: Options; resolve: (v: boolean) => void } | null>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  const ask = useCallback<Ask>((message, options = {}) => new Promise((resolve) => setState({ message, options, resolve })), []);
  const close = (v: boolean) => { state?.resolve(v); setState(null); };

  useEffect(() => {
    if (!state) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); close(false); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Ctx.Provider value={ask}>
      {children}
      {state && (
        <div className="backdrop confirm-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(false); }}>
          <div className="modal confirm" role="alertdialog" aria-modal="true">
            <h3>{state.options.title ?? (state.options.danger ? "Подтвердите удаление" : "Подтвердите действие")}</h3>
            <p className="confirm-text">{state.message}</p>
            <div className="foot">
              <button className="btn" onClick={() => close(false)}>{state.options.cancelLabel ?? "Отмена"}</button>
              <button ref={okRef} className={`btn ${state.options.danger ? "danger-solid" : "primary"}`} onClick={() => close(true)}>
                {state.options.okLabel ?? (state.options.danger ? "Удалить" : "Да")}
              </button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  );
}
