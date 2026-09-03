// Контекстное меню направления (правая кнопка мыши / кнопка «⋯») и окно переименования.
// Никаких браузерных prompt/confirm: всё — свои окна.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { canEdit, del, Direction, DirectionIn, dirColor, MIND_COLOR, put } from "./api";
import { useConfirm } from "./confirm";
import { MindGlyph } from "./MindMaps";
import { Store } from "./store";

export type MenuAnchor = { direction: Direction; x: number; y: number };

/** Открыть меню из обработчика onContextMenu или клика по «⋯». */
export function anchorFromEvent(direction: Direction, e: React.MouseEvent): MenuAnchor {
  e.preventDefault(); e.stopPropagation();
  // Для клика по кнопке ставим меню под кнопкой, для правой кнопки — в точку курсора
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const byButton = e.type !== "contextmenu";
  return { direction, x: byButton ? r.left : e.clientX, y: byButton ? r.bottom + 4 : e.clientY };
}

type Props = {
  store: Store; anchor: MenuAnchor; onClose: () => void;
  onOpen: (d: Direction) => void; onBoard: (d: Direction) => void; onNewProject: (d: Direction) => void; onShare: (d: Direction) => void;
  onMindmaps: (d: Direction) => void; onEdit: (d: Direction) => void; onRename: (d: Direction) => void; onDeleted: (d: Direction) => void;
};

const bodyOf = (d: Direction): DirectionIn => ({ name: d.name, description: d.description ?? null, goal: d.goal ?? null, color: d.color ?? null, status: d.status });

export default function DirectionMenu({ store, anchor, onClose, onOpen, onBoard, onNewProject, onShare, onMindmaps, onEdit, onRename, onDeleted }: Props) {
  const d = anchor.direction;
  const editable = canEdit(d.access) && d.access !== "via";
  const owner = !d.access || d.access === "owner";
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: anchor.x, y: anchor.y });
  const confirm = useConfirm();

  // Не вылезать за край экрана
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    setPos({ x: Math.max(8, Math.min(anchor.x, window.innerWidth - w - 8)), y: Math.max(8, Math.min(anchor.y, window.innerHeight - h - 8)) });
  }, [anchor]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey); window.addEventListener("resize", onClose);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("resize", onClose); };
  }, [onClose]);

  async function setStatus(status: Direction["status"]) {
    onClose();
    try { await put<Direction>(`/directions/${d.id}`, { ...bodyOf(d), status }); await store.reloadDirections(); }
    catch (e) { store.setError(String(e)); }
  }
  async function remove() {
    onClose();
    if (!(await confirm(`Направление «${d.name}» будет удалено вместе с его проектами. Задачи останутся, но потеряют привязку к нему.`, { danger: true, okLabel: "Удалить направление" }))) return;
    try { await del(`/directions/${d.id}`); await Promise.all([store.reloadDirections(), store.reloadProjects(), store.reloadTasks()]); onDeleted(d); }
    catch (e) { store.setError(String(e)); }
  }
  const run = (fn: (d: Direction) => void) => () => { onClose(); fn(d); };
  const open = store.tasks.filter((t) => t.status !== "done" && t.directions.some((x) => x.id === d.id)).length;

  return (
    <div className="ctx-backdrop" onMouseDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div ref={ref} className="ctx-menu" role="menu" aria-label={`Направление ${d.name}`} style={{ left: pos.x, top: pos.y }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ctx-title"><span className="swatch" style={{ background: dirColor(d) }} /><span className="ctx-name">{d.name}</span><span className="mono ctx-count">{open}</span></div>
        <button role="menuitem" onClick={run(onOpen)}>Карта проектов</button>
        <button role="menuitem" onClick={run(onBoard)}>Все задачи направления</button>
        {editable && <button role="menuitem" onClick={run(onNewProject)}><span className="ctx-ico">+</span>Новый проект…</button>}
        {d.access !== "via" && <button role="menuitem" onClick={run(onMindmaps)} style={{ ["--mind" as string]: MIND_COLOR }}><span className="ctx-ico" style={{ color: MIND_COLOR }}><MindGlyph size={12} /></span>Майндмапы направления</button>}
        {editable && <>
          <hr />
          <button role="menuitem" onClick={run(onRename)}>Переименовать…</button>
          <button role="menuitem" onClick={run(onEdit)}>Изменить: цель, цвет, описание…</button>
        </>}
        {owner && <button role="menuitem" onClick={run(onShare)}><span className="ctx-ico">⇄</span>Поделиться…</button>}
        {editable && <>
          <hr />
          {d.status === "active"
            ? <button role="menuitem" onClick={() => setStatus("paused")}>Поставить на паузу</button>
            : <button role="menuitem" onClick={() => setStatus("active")}>{d.status === "paused" ? "Возобновить" : "Вернуть из архива"}</button>}
          {d.status !== "archived" && <button role="menuitem" onClick={() => setStatus("archived")}>В архив</button>}
        </>}
        {owner && <>
          <hr />
          <button role="menuitem" className="danger" onClick={remove}>Удалить направление…</button>
        </>}
        {!editable && <p className="ctx-note">{d.access === "via" ? "Вам открыта только часть этого направления" : "Только просмотр"} — {d.owner?.name ?? "коллега"}</p>}
      </div>
    </div>
  );
}

/** Маленькое окно «Переименовать». */
export function RenameModal({ store, direction, onClose }: { store: Store; direction: Direction; onClose: () => void }) {
  const [name, setName] = useState(direction.name);
  const [busy, setBusy] = useState(false);
  async function save() {
    const v = name.trim(); if (!v || v === direction.name) { onClose(); return; }
    setBusy(true);
    try { await put<Direction>(`/directions/${direction.id}`, { ...bodyOf(direction), name: v }); await store.reloadDirections(); await store.reloadTasks(); onClose(); }
    catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal confirm" role="dialog" aria-modal="true" aria-label="Переименовать направление">
        <h3>Переименовать направление</h3>
        <input className="input" value={name} autoFocus onFocus={(e) => e.currentTarget.select()} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void save(); if (e.key === "Escape") onClose(); }} />
        <div className="foot">
          <button className="btn" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !name.trim()}>Сохранить</button>
        </div>
      </div>
    </div>
  );
}
