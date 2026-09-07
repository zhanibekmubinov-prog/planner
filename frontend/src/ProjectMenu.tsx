// Проекты: контекстное меню (правая кнопка / «⋯»), окно создания/изменения (с переносом в другое направление), переименование.
// Никаких браузерных prompt/confirm — только свои окна.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AccessPreview, api, canEdit, Direction, DIRECTION_COLORS, dirColor, errorText, MoveMode, PERMISSION_LABEL, post, Project, ProjectIn, projColor, put } from "./api";
import { useConfirm } from "./confirm";
import { useDeletion } from "./deletion";
import { useDirtyFlag, useEscape } from "./layers";
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
  const p = store.projects.find((x) => x.id === anchor.project.id) ?? anchor.project;   // Н5: актуальный объект
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: anchor.x, y: anchor.y });
  const confirm = useConfirm();
  const { deleteProject } = useDeletion(store);
  const editable = canEdit(p.access);
  const color = projColor(p, store.directions);

  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    setPos({ x: Math.max(8, Math.min(anchor.x, window.innerWidth - w - 8)), y: Math.max(8, Math.min(anchor.y, window.innerHeight - h - 8)) });
  }, [anchor]);
  useEscape(onClose);
  useEffect(() => { window.addEventListener("resize", onClose); return () => window.removeEventListener("resize", onClose); }, [onClose]);

  async function setStatus(status: Project["status"]) {
    onClose();
    if (status === "archived" && !(await confirm(`Проект «${p.name}» уйдёт с карты проектов и из левой панели. Задачи останутся внутри. Вернуть — из раздела «Архив».`, { title: "Убрать в архив?", okLabel: "В архив" }))) return;
    try { await put<Project>(`/projects/${p.id}`, { ...projectBody(p), status }); await store.reloadProjects(); }
    catch (e) { store.setError(errorText(e)); }
  }
  async function remove() {
    onClose();
    if (await deleteProject(p)) onDeleted(p);
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
          <button role="menuitem" onClick={run(onEdit)}>Изменить: цель, цвет, направление…</button>
        </>}
        {p.access === "owner" && <button role="menuitem" onClick={run(onShare)}><span className="ctx-ico">⇄</span>Поделиться…</button>}
        {editable && <>
          <hr />
          {p.status === "active"
            ? <button role="menuitem" onClick={() => setStatus("paused")}>Поставить на паузу</button>
            : <button role="menuitem" onClick={() => setStatus("active")}>{p.status === "paused" ? "Возобновить" : "Вернуть из архива"}</button>}
          {p.status !== "archived" && <button role="menuitem" onClick={() => setStatus("archived")}>В архив…</button>}
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

/** Окно создания / изменения проекта. При смене направления — блок «Перенос» (владелец, решение 2). */
export function ProjectModal({ store, direction, project, onClose, onSaved }: { store: Store; direction: Direction; project: Project | null; onClose: () => void; onSaved: (p: Project) => void }) {
  const initial: ProjectIn = project ? projectBody(project) : { direction_id: direction.id, name: "", description: null, goal: null, color: null, status: "active" };
  const [draft, setDraft] = useState<ProjectIn>(initial);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [moveMode, setMoveMode] = useState<MoveMode>("move");
  const [preview, setPreview] = useState<AccessPreview[] | null>(null);
  const [grant, setGrant] = useState<Set<number>>(new Set());
  const confirm = useConfirm();
  const inherited = dirColor(direction);
  const editableDirs = store.directions.filter((d) => d.status !== "archived" && canEdit(d.access) && d.access !== "via" || d.id === draft.direction_id);
  const moving = !!project && project.direction_id !== draft.direction_id;
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  useDirtyFlag(dirty);

  // Кто сейчас видит проект и кто потеряет доступ после переноса
  useEffect(() => {
    if (!moving || !project) { setPreview(null); return; }
    let alive = true;
    setPreview(null);
    api<AccessPreview[]>(`/projects/${project.id}/access-preview?direction_id=${draft.direction_id}`)
      .then((rows) => { if (!alive) return; setPreview(rows); setGrant(new Set(rows.filter((r) => !r.keeps_access).map((r) => r.user.id))); })
      .catch(() => { if (alive) setPreview([]); });
    return () => { alive = false; };
  }, [moving, project, draft.direction_id]);

  async function close() {
    if (busyRef.current) return;
    if (dirty && !(await confirm("Введённое не сохранится.", { title: "Закрыть без сохранения?", okLabel: "Закрыть" }))) return;
    onClose();
  }
  useEscape(() => void close());

  async function save() {
    if (busyRef.current) return;
    const name = draft.name.trim(); if (!name) return;
    busyRef.current = true; setBusy(true);
    try {
      if (project && draft.status === "archived" && project.status !== "archived"
        && !(await confirm(`Проект «${name}» уйдёт с карты проектов. Вернуть — из раздела «Архив».`, { title: "Убрать в архив?", okLabel: "В архив" }))) return;
      const body: ProjectIn = { ...draft, name };
      if (moving) { body.move_mode = moveMode; body.grant_access_user_ids = (preview ?? []).filter((r) => !r.keeps_access && grant.has(r.user.id)).map((r) => r.user.id); }
      const saved = project ? await put<Project>(`/projects/${project.id}`, body) : await post<Project>("/projects", body);
      await store.reloadProjects(); if (moving) await Promise.all([store.reloadTasks(), store.reloadShared()]);
      onSaved(saved);
    } catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }

  const losing = (preview ?? []).filter((r) => !r.keeps_access);
  const toggleGrant = (id: number) => setGrant((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const newDir = store.directions.find((d) => d.id === draft.direction_id);

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) void close(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={project ? "Изменить проект" : "Новый проект"} style={{ borderTop: `4px solid ${draft.color || inherited}` }}>
        <h3>{project ? "Изменить проект" : "Новый проект"}</h3>
        <div className="field">
          <label>Название</label>
          <input className="input" value={draft.name} autoFocus placeholder="Например, «Договор основной»" onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
        </div>
        <div className="field">
          <label>Направление</label>
          <select className="select" value={draft.direction_id} onChange={(e) => setDraft({ ...draft, direction_id: Number(e.target.value) })} disabled={!project && editableDirs.length <= 1}>
            {editableDirs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        {moving && (
          <div className="move-block" data-testid="move-block">
            <div className="move-head">Перенос в «{newDir?.name ?? "…"}»</div>
            <div className="move-modes" role="radiogroup" aria-label="Режим переноса">
              <label className={moveMode === "move" ? "on" : ""}>
                <input type="radio" name="move_mode" checked={moveMode === "move"} onChange={() => setMoveMode("move")} />
                <span><b>Перенести</b><small>задачи проекта потеряют направление «{direction.name}» и получат новое</small></span>
              </label>
              <label className={moveMode === "copy" ? "on" : ""}>
                <input type="radio" name="move_mode" checked={moveMode === "copy"} onChange={() => setMoveMode("copy")} />
                <span><b>Скопировать</b><small>задачи останутся в обоих направлениях</small></span>
              </label>
            </div>
            <div className="move-access">
              <div className="move-access-head">
                <span>Кто сейчас видит проект</span>
                {losing.length > 1 && <span className="row">
                  <button type="button" className="btn ghost sm" onClick={() => setGrant(new Set(losing.map((r) => r.user.id)))}>Все</button>
                  <button type="button" className="btn ghost sm" onClick={() => setGrant(new Set())}>Никого</button>
                </span>}
              </div>
              {preview === null ? <span className="hint">проверяю доступ…</span>
                : preview.length === 0 ? <span className="hint">Никому, кроме вас, проект не открыт.</span>
                : (
                  <ul className="move-people">
                    {preview.map((r) => (
                      <li key={r.user.id}>
                        {r.keeps_access
                          ? <span className="move-keep" title="Видит новое направление — доступ сохранится сам">✓</span>
                          : <input type="checkbox" checked={grant.has(r.user.id)} onChange={() => toggleGrant(r.user.id)} aria-label={`Оставить доступ: ${r.user.name}`} />}
                        <span className="move-who">{r.user.name} <span className="mono">{r.user.email}</span></span>
                        <span className="hint">{PERMISSION_LABEL[r.permission].toLowerCase()} · {r.keeps_access ? "сохранит доступ" : grant.has(r.user.id) ? "оставить доступ к проекту" : "потеряет доступ"}</span>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          </div>
        )}
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
          <button className="btn" onClick={() => void close()} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !draft.name.trim() || (moving && preview === null)}>{project ? (moving ? (moveMode === "move" ? "Перенести и сохранить" : "Скопировать и сохранить") : "Сохранить") : "Создать проект"}</button>
        </div>
      </div>
    </div>
  );
}

/** Маленькое окно «Переименовать проект». */
export function RenameProjectModal({ store, project, onClose }: { store: Store; project: Project; onClose: () => void }) {
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  useEscape(onClose);
  async function save() {
    if (busyRef.current) return;
    const v = name.trim(); if (!v || v === project.name) { onClose(); return; }
    busyRef.current = true; setBusy(true);
    try { await put<Project>(`/projects/${project.id}`, { ...projectBody(project), name: v }); await store.reloadProjects(); onClose(); }
    catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal confirm" role="dialog" aria-modal="true" aria-label="Переименовать проект">
        <h3>Переименовать проект</h3>
        <input className="input" value={name} autoFocus onFocus={(e) => e.currentTarget.select()} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
        <div className="foot">
          <button className="btn" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !name.trim()}>Сохранить</button>
        </div>
      </div>
    </div>
  );
}
