// Собственный диалог подтверждения вместо системного window.confirm.
// Использование: const confirm = useConfirm(); if (await confirm("Удалить?", { title: "Удалить проект?", danger: true })) …
// Правила (К2): фокус на «Отмена»; Enter никогда не подтверждает опасное действие; клавиши не «пробивают» диалог
// к другим слушателям окна; typeToConfirm — ввод названия, пока не совпадёт — кнопка выключена.
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useEscape } from "./layers";

export type ConfirmOptions = {
  title?: string; okLabel?: string; cancelLabel?: string; danger?: boolean;
  /** Требовать ввести это слово (название), прежде чем кнопка станет доступна. Сравнение без учёта регистра и пробелов по краям. */
  typeToConfirm?: string;
  /** Дополнительный блок под текстом (список затронутого, подсказки). */
  details?: ReactNode;
};
type Ask = (message: string, options?: ConfirmOptions) => Promise<boolean>;

const Ctx = createContext<Ask>(() => Promise.resolve(false));
let openCount = 0;
/** Открыт ли сейчас диалог — для обработчиков клавиш на страницах (майндмап). */
export const isConfirmOpen = () => openCount > 0;

export function useConfirm(): Ask {
  return useContext(Ctx);
}

type State = { message: string; options: ConfirmOptions; resolve: (v: boolean) => void };
const norm = (s: string) => s.trim().toLowerCase();

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null);
  const cur = useRef<State | null>(null);
  const [typed, setTyped] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);

  const ask = useCallback<Ask>((message, options = {}) => new Promise((resolve) => {
    cur.current?.resolve(false);            // второй вопрос поверх первого — первый считается отклонённым
    cur.current = { message, options, resolve };
    setTyped("");
    setState(cur.current);
  }), []);
  const close = useCallback((v: boolean) => {
    const s = cur.current; if (!s) return;
    cur.current = null; s.resolve(v); setState(null);
  }, []);

  const danger = !!state?.options.danger;
  const need = state?.options.typeToConfirm;
  const matched = !need || norm(typed) === norm(need);

  useEscape(() => close(false), !!state);

  useEffect(() => { if (state) cancelRef.current?.focus(); }, [state]);
  useEffect(() => {
    if (!state) return;
    openCount++;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return;                    // Esc обрабатывает слой (useEscape)
      e.stopPropagation();                                // ничего не долетает до страницы под диалогом
      if (e.key === "Enter") {
        e.preventDefault();
        if (!danger && matched) close(true);              // опасное действие Enter не подтверждает никогда
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => { openCount--; window.removeEventListener("keydown", onKey, true); };
  }, [state, danger, matched, close]);

  return (
    <Ctx.Provider value={ask}>
      {children}
      {state && (
        <div className="backdrop confirm-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(false); }}>
          <div className={`modal confirm ${danger ? "is-danger" : ""}`} role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-text">
            <h3 id="confirm-title">{state.options.title ?? (danger ? "Подтвердите удаление" : "Подтвердите действие")}</h3>
            <p id="confirm-text" className="confirm-text">{state.message}</p>
            {state.options.details && <div className="confirm-details">{state.options.details}</div>}
            {need && (
              <label className="confirm-type">
                <span>Введите название, чтобы подтвердить: <b>{need}</b></span>
                <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} aria-label="Введите название, чтобы подтвердить" />
              </label>
            )}
            <div className="foot">
              <button ref={cancelRef} className="btn" onClick={() => close(false)}>{state.options.cancelLabel ?? "Отмена"}</button>
              <button className={`btn ${danger ? "danger-solid" : "primary"}`} disabled={!matched} onClick={() => close(true)}>
                {state.options.okLabel ?? (danger ? "Удалить" : "Да")}
              </button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  );
}
