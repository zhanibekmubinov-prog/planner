import { useEffect, useMemo, useRef, useState } from "react";
import { canEdit, Direction, dirColor, isOverdue, post, Project, projColor, put, showDate, STATUS_LABEL, STATUSES, Task, TaskIn, TaskStatus } from "./api";
import { createMindMap, MindButton } from "./MindMaps";
import { Store } from "./store";

type Props = {
  store: Store; direction: Direction | null; project: Project | null; looseOnly: boolean; selectedId: number | null;
  onSelect: (id: number | null) => void; onEditDirection: (d: Direction) => void; onOpenDirection: (d: Direction) => void;
  onEditProject: (p: Project) => void; onShare: () => void;
  onOpenMindmap: (id: number) => void; onMindmaps: (directionId: number | null) => void;
};

const toIn = (t: Task): TaskIn => ({
  title: t.title, description: t.description ?? null, status: t.status, priority: t.priority,
  deadline: t.deadline ?? null, next_check_at: t.next_check_at ?? null,
  direction_ids: t.directions.map((d) => d.id), tool_ids: t.tools.map((x) => x.id), project_id: t.project_id ?? null,
});

export default function Board({ store, direction, project, looseOnly, selectedId, onSelect, onEditDirection, onOpenDirection, onEditProject, onShare, onOpenMindmap, onMindmaps }: Props) {
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [hideDone, setHideDone] = useState(false);
  const [dragOver, setDragOver] = useState<TaskStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<TaskStatus | null>(null);

  const tasks = useMemo(
    () => store.tasks.filter((t) => {
      if (project) return t.project_id === project.id;
      if (!direction) return true;
      if (!t.directions.some((d) => d.id === direction.id)) return false;
      return looseOnly ? !t.project_id : true;
    }),
    [store.tasks, direction, project, looseOnly],
  );
  // Право писать на эту доску: своё или открытое на редактирование
  const editable = project ? canEdit(project.access) : direction ? canEdit(direction.access) && direction.access !== "via" : true;
  const readOnlyWho = (project ? (project.access === "view" ? project.owner : null) : direction && (direction.access === "view" || direction.access === "via") ? direction.owner : null)?.name;
  const accent = project ? projColor(project, store.directions) : direction ? dirColor(direction) : null;
  const counts = useMemo(() => {
    const c: Record<TaskStatus, number> = { backlog: 0, in_progress: 0, waiting: 0, done: 0 };
    tasks.forEach((t) => c[t.status]++);
    return c;
  }, [tasks]);
  const columns = STATUSES.filter((s) => (filter === "all" ? !(hideDone && s === "done") : s === filter));

  // Создание задачи — поле прямо в колонке; Enter сохраняет и оставляет поле для следующей, Esc закрывает
  async function createTask(status: TaskStatus, title: string): Promise<boolean> {
    if (!title.trim()) return false;
    setBusy(true);
    try {
      await post<Task>("/tasks", {
        title: title.trim(), status, priority: 3, direction_ids: direction ? [direction.id] : [], tool_ids: [], project_id: project?.id ?? null,
      } satisfies TaskIn);
      await store.reloadTasks();
      return true;
    } catch (e) { store.setError(String(e)); return false; } finally { setBusy(false); }
  }

  async function moveTask(id: number, status: TaskStatus) {
    const t = store.tasks.find((x) => x.id === id);
    if (!t || t.status === status) return;
    if (t.access === "view") { store.setError("Только просмотр: эту задачу вам открыли без права редактирования"); return; }
    store.patchTask({ ...t, status });
    try {
      // исполнитель без права редактирования меняет только статус — отдельным запросом
      store.patchTask(t.access === "assignee" ? await post<Task>(`/tasks/${id}/status`, { status }) : await put<Task>(`/tasks/${id}`, { ...toIn(t), status }));
    } catch (e) { store.setError(String(e)); void store.reloadTasks(); }
  }

  return (
    <>
      <div className="topbar" style={accent ? { ["--dir" as string]: accent } : undefined}>
        <h2>
          {direction && (
            <button className="crumb" onClick={() => onOpenDirection(direction)} title="К карте проектов направления">
              <span className="swatch" style={{ background: dirColor(direction) }} />{direction.name}
            </button>
          )}
          {direction && (project || looseOnly) && <span className="crumb-sep" aria-hidden="true">›</span>}
          {project ? <span className="crumb-cur"><span className="swatch" style={{ background: accent ?? undefined }} />{project.name}</span>
            : looseOnly ? <span className="crumb-cur muted">Без проекта</span>
            : !direction ? "Все задачи" : null}
          {!direction && !project && null}
        </h2>
        {readOnlyWho && <span className="tag ro-tag" title="Открыто вам только на просмотр">только просмотр · {readOnlyWho}</span>}
        {project && editable && <button className="btn ghost sm" onClick={() => onEditProject(project)}>Изменить</button>}
        {!project && direction && editable && <button className="btn ghost sm" onClick={() => onEditDirection(direction)}>Изменить</button>}
        {((project && project.access === "owner") || (!project && direction && direction.access === "owner")) && <button className="btn ghost sm" onClick={onShare}>⇄ Поделиться</button>}
        {direction && !project && !looseOnly && (() => {
          const maps = store.mindmaps.filter((m) => m.direction_id === direction.id && !m.task_id);
          return <MindButton count={maps.length} onClick={async () => {
            if (maps.length === 1) onOpenMindmap(maps[0].id);
            else if (maps.length > 1) onMindmaps(direction.id);
            else if (editable) { try { const m = await createMindMap(store, direction.name, { direction_id: direction.id }); onOpenMindmap(m.id); } catch (e) { store.setError(String(e)); } }
          }} />;
        })()}
        <span className="spacer" />
        <span className="saving">{busy ? "сохраняю…" : ""}</span>
        {editable && <button className="btn primary" onClick={() => setAdding("backlog")}>+ Задача</button>}
        {(project?.goal || (!project && direction?.goal)) && <div className="goal">{project ? project.goal : direction?.goal}</div>}
      </div>

      <div className="filters tabs" role="tablist" aria-label="Фильтр по статусу">
        <button role="tab" aria-selected={filter === "all"} className={`tab ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
          Все <span className="n">{tasks.length}</span>
        </button>
        {STATUSES.map((s) => (
          <button key={s} role="tab" aria-selected={filter === s} className={`tab st-${s} ${filter === s ? "on" : ""}`} onClick={() => setFilter(filter === s ? "all" : s)}>
            {STATUS_LABEL[s]} <span className="n">{counts[s]}</span>
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {filter === "all" && (
          <label className="tab check">
            <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} /> скрыть готовые
          </label>
        )}
      </div>

      {tasks.length === 0 ? (
        <div className="state">
          <h3>{project ? `В проекте «${project.name}» пока нет задач` : looseOnly ? "Задач без проекта нет" : direction ? `В направлении «${direction.name}» пока нет задач` : "Задач пока нет"}</h3>
          <p>{editable ? "Добавьте первую — она появится в колонке «Бэклог»." : "Здесь появятся задачи, когда их добавит владелец."}</p>
          {!editable ? null : adding ? (
            <div style={{ width: 320 }}><NewTaskInput onSubmit={(t) => createTask("backlog", t)} onClose={() => setAdding(null)} /></div>
          ) : (
            <button className="btn primary" onClick={() => setAdding("backlog")}>+ Задача</button>
          )}
        </div>
      ) : (
        <div className="board" style={{ ["--cols" as string]: columns.length }}>
          {columns.map((s) => {
            const items = tasks.filter((t) => t.status === s);
            return (
              <section
                key={s}
                className={`col ${dragOver === s ? "over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); if (dragOver !== s) setDragOver(s); }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => {
                  e.preventDefault(); setDragOver(null);
                  const id = Number(e.dataTransfer.getData("text/task-id"));
                  if (id) void moveTask(id, s);
                }}
              >
                <header className="col-head">
                  {STATUS_LABEL[s]} <span className="n">{items.length}</span>
                  {editable && <button className="add" title="Добавить задачу сюда" aria-label="Добавить задачу" onClick={() => setAdding(s)}>+</button>}
                </header>
                <div className="col-body">
                  {adding === s && <NewTaskInput onSubmit={(t) => createTask(s, t)} onClose={() => setAdding(null)} />}
                  {items.length === 0 && adding !== s && <div className="col-empty">{editable ? "Перетащите задачу сюда" : "Пусто"}</div>}
                  {items.map((t) => (
                    <TaskCard key={t.id} task={t} selected={t.id === selectedId} showDirs={!direction} showProject={!project} project={store.projects.find((p) => p.id === t.project_id)} directions={store.directions} onClick={() => onSelect(t.id)}
                      mindmap={store.mindmaps.find((m) => m.task_id === t.id)} onOpenMindmap={onOpenMindmap} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}

function NewTaskInput({ onSubmit, onClose }: { onSubmit: (title: string) => Promise<boolean>; onClose: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);

  async function submit(keepOpen: boolean) {
    if (!value.trim()) { onClose(); return; }
    setBusy(true);
    const ok = await onSubmit(value);
    setBusy(false);
    if (ok) { setValue(""); if (!keepOpen) onClose(); else ref.current?.focus(); }
  }

  return (
    <div className="new-task">
      <textarea
        ref={ref} className="new-task-input" rows={2} value={value} placeholder="Название задачи…"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(true); }
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
        }}
        disabled={busy}
      />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="hint">Enter — добавить, Esc — закрыть</span>
        <span className="row">
          <button className="btn ghost sm" onClick={onClose}>Отмена</button>
          <button className="btn primary sm" onClick={() => submit(false)} disabled={busy || !value.trim()}>Добавить</button>
        </span>
      </div>
    </div>
  );
}

function TaskCard({ task, selected, showDirs, showProject, project, directions, onClick, mindmap, onOpenMindmap }: { task: Task; selected: boolean; showDirs: boolean; showProject: boolean; project?: Project; directions: Direction[]; onClick: () => void; mindmap?: { id: number }; onOpenMindmap: (id: number) => void }) {
  const [dragging, setDragging] = useState(false);
  const shared = showDirs && (task.access === "edit" || task.access === "view");   // на общей доске направления/проекта пометка избыточна
  const overdue = task.status !== "done" && isOverdue(task.deadline ? `${task.deadline}T23:59:59` : null);
  const checkDue = task.status !== "done" && isOverdue(task.next_check_at);
  return (
    <div
      role="button"
      tabIndex={0}
      className={`card ${selected ? "selected" : ""} ${task.status === "done" ? "done" : ""} ${dragging ? "dragging" : ""} ${task.access === "view" ? "ro" : ""}`}
      draggable={task.access !== "view"}
      onDragStart={(e) => { e.dataTransfer.setData("text/task-id", String(task.id)); e.dataTransfer.effectAllowed = "move"; setDragging(true); }}
      onDragEnd={() => setDragging(false)}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
    >
      <span className="rail">
        {(task.directions.length ? task.directions : [null]).map((d, i) => (
          <span key={i} style={{ background: d ? dirColor(d) : "var(--line-strong)" }} />
        ))}
      </span>
      <div className="title">{task.title}</div>
      <div className="meta">
        <span className="code mono">#{task.id}</span>
        <span className={`pri p${task.priority}`}>P{task.priority}</span>
        {showProject && project && <span className="tag proj-tag" title="Проект"><span className="dot" style={{ background: projColor(project, directions) }} />{project.name}</span>}
        {shared && <span className="tag shared-tag" title={`Открыл ${task.owner?.name ?? "коллега"} · ${task.access === "edit" ? "редактирование" : "просмотр"}`}>⇄ {task.owner?.name?.split(" ")[0] ?? ""}</span>}
        {task.deadline && <span className={`mono ${overdue ? "over" : ""}`}>{overdue ? "⚑ " : ""}до {showDate(task.deadline)}</span>}
        {task.next_check_at && <span className={`mono ${checkDue ? "warn" : ""}`}>⟳ {showDate(task.next_check_at)}</span>}
        {task.tools.length > 0 && <span className="tag">{task.tools.length} тул{task.tools.length === 1 ? "" : "а"}</span>}
        {mindmap && <span style={{ marginLeft: "auto" }}><MindButton size="sm" count={1} label="" title="Открыть майндмап задачи" onClick={() => onOpenMindmap(mindmap.id)} /></span>}
      </div>
      {showDirs && task.directions.length > 0 && (
        <div className="dirs">
          {task.directions.map((d) => (
            <span key={d.id} className="tag"><span className="dot" style={{ background: dirColor(d), marginRight: 4 }} />{d.name}</span>
          ))}
        </div>
      )}
    </div>
  );
}
