import { useMemo, useState } from "react";
import { Direction, dirColor, isOverdue, post, put, showDate, STATUS_LABEL, STATUSES, Task, TaskIn, TaskStatus } from "./api";
import { Store } from "./store";

type Props = {
  store: Store; direction: Direction | null; selectedId: number | null;
  onSelect: (id: number | null) => void; onEditDirection: (d: Direction) => void;
};

const toIn = (t: Task): TaskIn => ({
  title: t.title, description: t.description ?? null, status: t.status, priority: t.priority,
  deadline: t.deadline ?? null, next_check_at: t.next_check_at ?? null,
  direction_ids: t.directions.map((d) => d.id), tool_ids: t.tools.map((x) => x.id),
});

export default function Board({ store, direction, selectedId, onSelect, onEditDirection }: Props) {
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [hideDone, setHideDone] = useState(false);
  const [dragOver, setDragOver] = useState<TaskStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const tasks = useMemo(
    () => store.tasks.filter((t) => !direction || t.directions.some((d) => d.id === direction.id)),
    [store.tasks, direction],
  );
  const counts = useMemo(() => {
    const c: Record<TaskStatus, number> = { backlog: 0, in_progress: 0, waiting: 0, done: 0 };
    tasks.forEach((t) => c[t.status]++);
    return c;
  }, [tasks]);
  const columns = STATUSES.filter((s) => (filter === "all" ? !(hideDone && s === "done") : s === filter));

  async function createTask(status: TaskStatus) {
    const title = window.prompt("Название задачи");
    if (!title?.trim()) return;
    setBusy(true);
    try {
      const t = await post<Task>("/tasks", {
        title: title.trim(), status, priority: 3, direction_ids: direction ? [direction.id] : [], tool_ids: [],
      } satisfies TaskIn);
      await store.reloadTasks();
      onSelect(t.id);
    } catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }

  async function moveTask(id: number, status: TaskStatus) {
    const t = store.tasks.find((x) => x.id === id);
    if (!t || t.status === status) return;
    store.patchTask({ ...t, status });
    try {
      store.patchTask(await put<Task>(`/tasks/${id}`, { ...toIn(t), status }));
    } catch (e) { store.setError(String(e)); void store.reloadTasks(); }
  }

  return (
    <>
      <div className="topbar">
        <h2>
          {direction && <span className="swatch" style={{ background: dirColor(direction) }} />}
          {direction ? direction.name : "Все задачи"}
        </h2>
        {direction && <button className="btn ghost sm" onClick={() => onEditDirection(direction)}>Изменить</button>}
        <span className="spacer" />
        <span className="saving">{busy ? "сохраняю…" : ""}</span>
        <button className="btn primary" onClick={() => createTask("backlog")}>+ Задача</button>
        {direction?.goal && <div className="goal">{direction.goal}</div>}
      </div>

      <div className="filters">
        <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
          Все <span className="n">{tasks.length}</span>
        </button>
        {STATUSES.map((s) => (
          <button key={s} className={`chip ${filter === s ? "on" : ""}`} onClick={() => setFilter(filter === s ? "all" : s)}>
            {STATUS_LABEL[s]} <span className="n">{counts[s]}</span>
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {filter === "all" && (
          <label className="chip" style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} /> скрыть готовые
          </label>
        )}
      </div>

      {tasks.length === 0 ? (
        <div className="state">
          <h3>{direction ? `В направлении «${direction.name}» пока нет задач` : "Задач пока нет"}</h3>
          <p>Добавьте первую — она появится в колонке «Бэклог».</p>
          <button className="btn primary" onClick={() => createTask("backlog")}>+ Задача</button>
        </div>
      ) : (
        <div className="board">
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
                  <button className="add" title="Добавить задачу сюда" aria-label="Добавить задачу" onClick={() => createTask(s)}>+</button>
                </header>
                <div className="col-body">
                  {items.length === 0 && <div className="col-empty">Перетащите задачу сюда</div>}
                  {items.map((t) => (
                    <TaskCard key={t.id} task={t} selected={t.id === selectedId} showDirs={!direction} onClick={() => onSelect(t.id)} />
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

function TaskCard({ task, selected, showDirs, onClick }: { task: Task; selected: boolean; showDirs: boolean; onClick: () => void }) {
  const [dragging, setDragging] = useState(false);
  const overdue = task.status !== "done" && isOverdue(task.deadline ? `${task.deadline}T23:59:59` : null);
  const checkDue = task.status !== "done" && isOverdue(task.next_check_at);
  return (
    <div
      role="button"
      tabIndex={0}
      className={`card ${selected ? "selected" : ""} ${task.status === "done" ? "done" : ""} ${dragging ? "dragging" : ""}`}
      draggable
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
        {task.deadline && <span className={`mono ${overdue ? "over" : ""}`}>{overdue ? "⚑ " : ""}до {showDate(task.deadline)}</span>}
        {task.next_check_at && <span className={`mono ${checkDue ? "warn" : ""}`}>⟳ {showDate(task.next_check_at)}</span>}
        {task.tools.length > 0 && <span className="tag">{task.tools.length} тул{task.tools.length === 1 ? "" : "а"}</span>}
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
