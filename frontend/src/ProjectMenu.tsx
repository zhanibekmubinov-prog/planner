// Проекты: контекстное меню (правая кнопка / «⋯»), окно создания/изменения, переименование.
// Никаких браузерных prompt/confirm — только свои окна.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { canEdit, del, Direction, DIRECTION_COLORS, dirColor, post, Project, ProjectIn, projColor, put } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

export type ProjectAnchor = { project: Project; x: number; y: number };

export function projectAnchorFromEvent(project: Project, e: React.MouseEvent): ProjectAnchor {
  e.preventDefault(); e.stopPropagation();
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const byButton = e.type !== "contextmenu";
  return { project, x: byButton ? r.left : e.clientX, y: byButton ? r.bottom + 4 : e.clientY };
}

export const projectBody = (p: Project): ProjectIn => ({ direction_id: p.direction_id, name: p.name, description: p.description ?? null, goal: p.goal ?? null, color: p.color ?? null, status: p.status });

type MenuProps = {
  store: Store; anchor: ProjectAnchor; onClose: () => void;
  onOpen: (p: Project) => void; onEdit: (p: Project) => void; onRename: (p: Project) => void; onShare: (p: Project) => void; onDeleted: (p: Project) => void;
};

export default function ProjectMenu({ store, anchor, onClose, onOpen, onEdit, onRename, onShare, onDeleted }: MenuProps) {
  const p = anchor.project;
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: anchor.x, y: anchor.y });
  const confirm = useConfirm();
  const editable = canEdit(p.access);
  const color = projColor(p, store.directions);

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

  async function setStatus(status: Project["status"]) {
    onClose();
    try { await put<Project>(`/projects/${p.id}`, { ...projectBody(p), status }); await store.reloadProjects(); }
    catch (e) { store.setError(String(e)); }
  }
  async function remove() {
    onClose();
    if (!(await confirm(`Проект «${p.name}» будет удалён. Его задачи останутся в направлении — без проекта.`, { danger: true, okLabel: "Удалить проект" }))) return;
    try { await del(`/projects/${p.id}`); await Promise.all([store.reloadProjects(), store.reloadTasks()]); onDeleted(p); }
    catch (e) { store.setError(String(e)); }
  }
  const run = (fn: (p: Project) => void) => () => { onClose(); fn(p); };
  const open = store.tasks.filter((t) => t.status !== "done" && t.project_id === p.id).length;

  return (
    <div className="ctx-backdrop" onMouseDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div ref={ref} className="ctx-menu" role="menu" aria-label={`Проект ${p.name}`} style={{ left: pos.x, top: pos.y }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ctx-title"><span className="swatch" style={{ background: color }} /><span className="ctx-name">{p.name}</span><span className="mono ctx-count">{open}</span></div>
        <button role="menuitem" onClick={run(onOpen)}>Открыть доску проекта</button>
        {editable && <>
          <hr />
          <button role="menuitem" onClick={run(onRename)}>Переименовать…</button>
          <button role="menuitem" onClick={run(onEdit)}>Изменить: цель, цвет, описание…</button>
        </>}
        {p.access === "owner" && <button role="menuitem" onClick={run(onShare)}><span className="ctx-ico">⇄</span>Поделиться…</button>}
        {editable && <>
          <hr />
          {p.status === "active"
            ? <button role="menuitem" onClick={() => setStatus("paused")}>Поставить на паузу</button>
            : <button role="menuitem" onClick={() => setStatus("active")}>{p.status === "paused" ? "Возобновить" : "Вернуть из архива"}</button>}
          {p.status !== "archived" && <button role="menuitem" onClick={() => setStatus("archived")}>В архив</button>}
        </>}
        {p.access === "owner" && <>
          <hr />
          <button role="menuitem" className="danger" onClick={remove}>Удалить проект…</button>
        </>}
        {!editable && <p className="ctx-note">Только просмотр — открыл {p.owner?.name ?? "коллега"}</p>}
      </div>
    </div>
  );
}

/** Окно создания / изменения проекта. */
export function ProjectModal({ store, direction, project, onClose, onSaved }: { store: Store; direction: Direction; project: Project | null; onClose: () => void; onSaved: (p: Project) => void }) {
  const [draft, setDraft] = useState<ProjectIn>(project ? projectBody(project) : { direction_id: direction.id, name: "", description: null, goal: null, color: null, status: "active" });
  const [busy, setBusy] = useState(false);
  const inherited = dirColor(direction);
  const editableDirs = store.directions.filter((d) => d.status !== "archived" && canEdit(d.access) && d.access !== "via" || d.id === draft.direction_id);

  async function save() {
    const name = draft.name.trim(); if (!name) return;
    setBusy(true);
    try {
      const saved = project ? await put<Project>(`/projects/${project.id}`, { ...draft, name }) : await post<Project>("/projects", { ...draft, name });
      await store.reloadProjects(); if (project && project.direction_id !== saved.direction_id) await store.reloadTasks();
      onSaved(saved);
    } catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={project ? "Изменить проект" : "Новый проект"} style={{ borderTop: `4px solid ${draft.color || inherited}` }}>
        <h3>{project ? "Изменить проект" : "Новый проект"}</h3>
        <div className="field">
          <label>Название</label>
          <input className="input" value={draft.name} autoFocus placeholder="Например, «Договор основной»" onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter") void save(); if (e.key === "Escape") onClose(); }} />
        </div>
        <div className="field">
          <label>Направление</label>
          <select className="select" value={draft.direction_id} onChange={(e) => setDraft({ ...draft, direction_id: Number(e.target.value) })} disabled={!project && editableDirs.length <= 1}>
            {editableDirs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          {project && project.direction_id !== draft.direction_id && <span className="hint">Задачи проекта получат новое направление (старое останется у них тоже).</span>}
        </div>
        <div className="field">
          <label>Цель</label>
          <input className="input" value={draft.goal ?? ""} placeholder="Чего добиваемся этим проектом" onChange={(e) => setDraft({ ...draft, goal: e.target.value || null })} />
        </div>
        <div className="field">
          <label>Описание</label>
          <textarea className="textarea" rows={3} value={draft.description ?? ""} onChange={(e) => setDraft({ ...draft, description: e.target.value || null })} />
        </div>
        <div className="field">
          <label>Цвет</label>
          <div className="swatches">
            <button type="button" className={`inherit ${!draft.color ? "on" : ""}`} style={{ background: inherited }} title="Как у направления" onClick={() => setDraft({ ...draft, color: null })}>≈</button>
            {DIRECTION_COLORS.map((c) => <button type="button" key={c} className={draft.color === c ? "on" : ""} style={{ background: c }} onClick={() => setDraft({ ...draft, color: c })} aria-label={c} />)}
          </div>
        </div>
        {project && (
          <div className="field">
            <label>Статус</label>
            <div className="seg" role="radiogroup">
              {(["active", "paused", "archived"] as const).map((s) => (
                <button key={s} type="button" role="radio" aria-checked={draft.status === s} className={draft.status === s ? "on" : ""} onClick={() => setDraft({ ...draft, status: s })}>{{ active: "Активен", paused: "На паузе", archived: "В архиве" }[s]}</button>
              ))}
            </div>
          </div>
        )}
        <div className="foot">
          <button className="btn" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !draft.name.trim()}>{project ? "Сохранить" : "Создать проект"}</button>
        </div>
      </div>
    </div>
  );
}

/** Маленькое окно «Переименовать проект». */
export function RenameProjectModal({ store, project, onClose }: { store: Store; project: Project; onClose: () => void }) {
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  async function save() {
    const v = name.trim(); if (!v || v === project.name) { onClose(); return; }
    setBusy(true);
    try { await put<Project>(`/projects/${project.id}`, { ...projectBody(project), name: v }); await store.reloadProjects(); onClose(); }
    catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal confirm" role="dialog" aria-modal="true" aria-label="Переименовать проект">
        <h3>Переименовать проект</h3>
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
