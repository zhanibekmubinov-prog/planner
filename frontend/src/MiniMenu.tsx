// Маленькое контекстное меню (правая кнопка / «⋯») для карточки «Без проекта» и строк задач.
// Тот же вид, что у меню направления/проекта; Esc и клик мимо — закрыть; не вылезает за край экрана.
import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useEscape } from "./layers";

export type MenuItem = { label: ReactNode; onClick: () => void; danger?: boolean; icon?: ReactNode } | "hr";
export type MiniAnchor = { x: number; y: number };

/** Точка для меню: под кнопкой при клике, в курсоре — при правой кнопке. Гасит событие, чтобы не всплыло к родителю. */
export function miniAnchor(e: React.MouseEvent): MiniAnchor {
  e.preventDefault(); e.stopPropagation();
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const byButton = e.type !== "contextmenu";
  return { x: byButton ? r.left : e.clientX, y: byButton ? r.bottom + 4 : e.clientY };
}

type Props = { anchor: MiniAnchor; title?: ReactNode; label: string; items: MenuItem[]; onClose: () => void };

export default function MiniMenu({ anchor, title, label, items, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(anchor);
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    setPos({ x: Math.max(8, Math.min(anchor.x, window.innerWidth - el.offsetWidth - 8)), y: Math.max(8, Math.min(anchor.y, window.innerHeight - el.offsetHeight - 8)) });
  }, [anchor]);
  useEscape(onClose);
  useEffect(() => { window.addEventListener("resize", onClose); return () => window.removeEventListener("resize", onClose); }, [onClose]);
  useEffect(() => { ref.current?.querySelector<HTMLButtonElement>("button[role=menuitem]")?.focus(); }, []);

  return (
    <div className="ctx-backdrop" onMouseDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div ref={ref} className="ctx-menu" role="menu" aria-label={label} style={{ left: pos.x, top: pos.y }} onMouseDown={(e) => e.stopPropagation()}>
        {title && <div className="ctx-title">{title}</div>}
        {items.map((it, i) => it === "hr" ? <hr key={i} /> : (
          <button key={i} role="menuitem" className={it.danger ? "danger" : ""} onClick={() => { onClose(); it.onClick(); }}>
            {it.icon && <span className="ctx-ico">{it.icon}</span>}{it.label}
          </button>
        ))}
      </div>
    </div>
  );
}
