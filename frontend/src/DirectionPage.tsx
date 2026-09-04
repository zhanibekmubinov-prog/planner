// Страница направления — карта проектов: каждый проект карточкой со статистикой и шкалой внимания
// (та же формула, что у Карты направлений, но уровнем ниже), плюс блок «Без проекта».
// Задачи можно перетаскивать между проектами и «Без проекта» — как карточки между колонками на доске.
import { useMemo, useState } from "react";
import { canEdit, ChecklistItem, Direction, dirColor, isOverdue, Project, projColor, put, showDate, STATUS_LABEL, Task, TaskIn } from "./api";
import { checklistProgress } from "./Checklist";
import { createMindMap, MindButton } from "./MindMaps";
import { buildReport } from "./Overview";
import { Store } from "./store";

type Props = {
  store: Store; direction: Direction;
  onOpenBoard: (projectId?: number | "none") => void;
  onOpenTask: (projectId: number | "none" | undefined, taskId: number) => void;
  onNewProject: () => void; onEditDirection: () => void; onDirectionMenu: (e: React.MouseEvent) => void;
  onProjectMenu: (p: Project, e: React.MouseEvent) => void; onShare: () => void;
  onOpenMindmap: (id: number) => void; onMindmaps: () => void;
};

const DRAG_TYPE = "text/task-id";
const TOP = 5;

const toIn = (t: Task, projectId: number | null): TaskIn => ({
  title: t.title, description: t.description ?? null, status: t.status, priority: t.priority,
  deadline: t.deadline || null, next_check_at: t.next_check_at || null,
  direction_ids: t.directions.map((d) => d.id), tool_ids: t.tools.map((x) => x.id), project_id: projectId,
  checklist: (t.checklist ?? []) as ChecklistItem[],
});

export default function DirectionPage({ store, direction, onOpenBoard, onOpenTask, onNewProject, onEditDirection, onDirectionMenu, onProjectMenu, onShare, onOpenMindmap, onMindmaps }: Props) {
  const color = dirColor(direction);
  const editable = canEdit(direction.access);
  const tasks = useMemo(() => store.tasks.filter((t) => t.directions.some((d) => d.id === direction.id)), [store.tasks, direction.id]);
  const projects = useMemo(
    () => store.projects.filter((p) => p.direction_id === direction.id && p.status !== "archived")
      .map((p) => ({ project: p, report: buildReport({ ...direction, status: p.status }, tasks.filter((t) => t.project_id === p.id)) }))
      .sort((a, b) => (a.project.status === "paused" ? 1 : 0) - (b.project.status === "paused" ? 1 : 0) || b.report.score - a.report.score),
    [store.projects, direction, tasks],
  );
  const loose = tasks.filter((t) => !t.project_id);
  const looseOpen = loose.filter((t) => t.status !== "done");
  const whole = buildReport(direction, tasks);
  const open = tasks.filter((t) => t.status !== "done");
  const maps = store.mindmaps.filter((m) => m.direction_id === direction.id && !m.task_id);
  const shared = direction.access === "edit" || direction.access === "view";

  // Перенос задачи между проектами: PUT всей карточки с новым project_id; направление проекта бэкенд добавит сам.
  const [moving, setMoving] = useState<number | null>(null);
  async function moveTask(taskId: number, projectId: number | null) {
    const t = store.tasks.find((x) => x.id === taskId);
    if (!t || (t.project_id ?? null) === projectId || !canEdit(t.access)) return;
    const target = projectId ? store.projects.find((p) => p.id === projectId) : null;
    if (projectId && (!target || !canEdit(target.access))) return;
    setMoving(taskId);
    try {
      store.patchTask({ ...t, project_id: projectId });   // оптимистично — карточка сразу в новом проекте
      store.patchTask(await put<Task>(`/tasks/${t.id}`, toIn(t, projectId)));
    } catch (e) { store.patchTask(t); store.setError(String(e)); } finally { setMoving(null); }
  }
  const canDrop = (projectId: number | null) => editable && (projectId === null || canEdit(store.projects.find((p) => p.id === projectId)?.access));

  return (
    <div className="overview dir-page" style={{ ["--dir" as string]: color }} onContextMenu={onDirectionMenu}>
      <header className="ov-head">
        <div className="dir-head">
          <div className="dir-crumb">Направление{shared && <span className="tag shared-tag">открыл {direction.owner?.name ?? "коллега"} · {direction.access === "edit" ? "редактирование" : "просмотр"}</span>}</div>
          <h2><span className="swatch" style={{ background: color }} />{direction.name}</h2>
          {direction.goal && <p className="ov-goal">{direction.goal}</p>}
          <p className="ov-sub">
            {projects.length} {plural(projects.length, "проект", "проекта", "проектов")} · {open.length} открытых задач
            {whole.overdue.length > 0 && <> · <span className="over">{whole.overdue.length} просрочено</span></>}
            {looseOpen.length > 0 && <> · {looseOpen.length} без проекта</>}
          </p>
        </div>
        <div className="dir-actions">
          {editable && <button className="btn primary" onClick={onNewProject}>+ Проект</button>}
          <button className="btn" onClick={() => onOpenBoard(undefined)}>Все задачи направления</button>
          {editable && <button className="btn ghost sm" onClick={onEditDirection}>Изменить</button>}
          {direction.access === "owner" && <button className="btn ghost sm" onClick={onShare}>Поделиться…</button>}
          {direction.access !== "via" && (
            <MindButton count={maps.length} onClick={async () => {
              if (maps.length === 1) onOpenMindmap(maps[0].id);
              else if (maps.length > 1) onMindmaps();
              else if (editable) { try { const m = await createMindMap(store, direction.name, { direction_id: direction.id }); onOpenMindmap(m.id); } catch (e) { store.setError(String(e)); } }
            }} />
          )}
        </div>
      </header>

      {projects.length === 0 && loose.length === 0 ? (
        <div className="state" style={{ flex: "none", padding: "48px 20px" }}>
          <h3>В направлении пока пусто</h3>
          <p>Проект — это крупная часть направления: договор, объект, кампания. Внутри проекта живут задачи.<br />Мелкие задачи можно вести и без проекта — прямо в направлении.</p>
          {editable && (
            <div className="row">
              <button className="btn primary" onClick={onNewProject}>+ Первый проект</button>
              <button className="btn" onClick={() => onOpenBoard("none")}>Просто добавить задачу</button>
            </div>
          )}
        </div>
      ) : (
        <div className="ov-grid">
          {projects.map(({ project, report }) => (
            <ProjectCard key={project.id} p={project} r={report} color={projColor(project, store.directions)}
              onOpen={() => onOpenBoard(project.id)} onTask={(id) => onOpenTask(project.id, id)} onMenu={(e) => onProjectMenu(project, e)}
              dropTarget={canDrop(project.id) ? project.id : undefined} onDropTask={(id) => moveTask(id, project.id)} dragEnabled={editable} movingId={moving} />
          ))}
          <DropCard className={`ov-card loose ${loose.length === 0 ? "empty" : ""}`} style={{ ["--dir" as string]: color }}
            enabled={canDrop(null)} onDropTask={(id) => moveTask(id, null)}>
            <header className="ov-card-head">
              <button className="ov-name" onClick={() => onOpenBoard("none")}>
                <span className="swatch hollow" style={{ borderColor: color }} />
                <span>Без проекта</span>
              </button>
              <span className="lvl lvl-ok">{looseOpen.length} откр.</span>
            </header>
            <p className="ov-goal">Задачи направления, не привязанные к проекту.{editable && projects.length > 0 && " Перетащите задачу на проект, чтобы перенести."}</p>
            {looseOpen.length > 0 ? (
              <TaskList tasks={[...looseOpen].sort((a, b) => a.priority - b.priority)} onTask={(id) => onOpenTask("none", id)} onBoard={() => onOpenBoard("none")} dragEnabled={editable} movingId={moving} />
            ) : (
              <p className="ov-empty">{loose.length ? "Все закрыты." : "Пусто — сюда попадают задачи без проекта."}</p>
            )}
            {editable && <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => onOpenBoard("none")}>+ Задача без проекта</button>}
          </DropCard>
        </div>
      )}
    </div>
  );
}

/** Карточка-цель для перетаскивания: подсвечивается, пока над ней тянут задачу. */
function DropCard({ enabled, onDropTask, className, children, ...rest }: { enabled: boolean; onDropTask: (taskId: number) => void; className: string; children: React.ReactNode } & React.HTMLAttributes<HTMLElement>) {
  const [over, setOver] = useState(false);
  return (
    <article
      {...rest}
      className={`${className} ${over ? "drop-over" : ""}`}
      onDragOver={(e) => { if (!enabled || !e.dataTransfer.types.includes(DRAG_TYPE)) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (!over) setOver(true); }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); }}
      onDrop={(e) => { setOver(false); if (!enabled) return; const id = Number(e.dataTransfer.getData(DRAG_TYPE)); if (id) { e.preventDefault(); onDropTask(id); } }}
    >
      {children}
    </article>
  );
}

function ProjectCard({ p, r, color, onOpen, onTask, onMenu, dropTarget, onDropTask, dragEnabled, movingId }: {
  p: Project; r: ReturnType<typeof buildReport>; color: string; onOpen: () => void; onTask: (id: number) => void; onMenu: (e: React.MouseEvent) => void;
  dropTarget?: number; onDropTask: (taskId: number) => void; dragEnabled: boolean; movingId: number | null;
}) {
  const total = r.tasks.length;
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  const paused = p.status === "paused";
  const sorted = [...r.open].sort((a, b) => a.priority - b.priority || (a.deadline || "9").localeCompare(b.deadline || "9"));
  return (
    <DropCard className={`ov-card proj-card ${paused ? "paused" : ""} state-${r.level.key}`} style={{ ["--dir" as string]: color }}
      enabled={dropTarget !== undefined} onDropTask={onDropTask} onContextMenu={(e) => { e.stopPropagation(); onMenu(e); }}>
      <header className="ov-card-head">
        <button className="ov-name" onClick={onOpen}><span className="swatch" style={{ background: color }} /><span>{p.name}</span></button>
        <span className={`lvl lvl-${r.level.key}`} title={r.level.hint}>{paused ? "На паузе" : total === 0 ? "Пусто" : r.level.label}</span>
        <button className="more" onClick={onMenu} title="Действия с проектом" aria-label={`Действия: ${p.name}`}>⋯</button>
      </header>
      {p.goal && <p className="ov-goal">{p.goal}</p>}
      <div className="stack" title="Состав задач">
        <span style={{ width: `${pct(r.done)}%`, background: "var(--ok)" }} />
        <span style={{ width: `${pct(r.inProgress)}%`, background: color }} />
        <span style={{ width: `${pct(r.waiting)}%`, background: "var(--warn)" }} />
        <span style={{ width: `${pct(r.backlog)}%`, background: "var(--line-strong)" }} />
      </div>
      <dl className="stats">
        <div><dt>Всего</dt><dd className="mono">{total}</dd></div>
        <div><dt>Готово</dt><dd className="mono">{r.done}</dd></div>
        <div><dt>В работе</dt><dd className="mono">{r.inProgress}</dd></div>
        <div><dt>Ждём</dt><dd className="mono">{r.waiting}</dd></div>
        <div className={r.overdue.length ? "bad" : ""}><dt>Просрочено</dt><dd className="mono">{r.overdue.length}</dd></div>
      </dl>
      {total > 0 && <p className="ov-reasons">{r.reasons.length ? r.reasons.join(" · ") : "движение есть, сроки соблюдаются"}</p>}
      {sorted.length > 0 ? (
        <TaskList tasks={sorted} onTask={onTask} onBoard={onOpen} dragEnabled={dragEnabled} movingId={movingId} />
      ) : (
        <p className="ov-empty drop-hint">{total === 0 ? (dropTarget !== undefined ? "Задач нет — перетащите сюда или откройте доску проекта." : "Задач нет — откройте доску проекта и добавьте первую.") : "Все задачи закрыты."}</p>
      )}
    </DropCard>
  );
}

/** Список открытых задач карточки: первые пять, остальные раскрываются на месте — чтобы любую можно было перетащить. */
function TaskList({ tasks, onTask, onBoard, dragEnabled, movingId }: { tasks: Task[]; onTask: (id: number) => void; onBoard: () => void; dragEnabled: boolean; movingId: number | null }) {
  const [all, setAll] = useState(false);
  const shown = all ? tasks : tasks.slice(0, TOP);
  const rest = tasks.length - shown.length;
  return (
    <ul className="ov-tasks">
      {shown.map((t) => <TaskRow key={t.id} t={t} onClick={() => onTask(t.id)} draggable={dragEnabled && canEdit(t.access)} moving={movingId === t.id} />)}
      {rest > 0 && <li className="more"><button onClick={() => setAll(true)}>ещё {rest} — показать все</button></li>}
      {all && tasks.length > TOP && <li className="more"><button onClick={() => setAll(false)}>свернуть</button> <button onClick={onBoard}>на доску →</button></li>}
    </ul>
  );
}

function TaskRow({ t, onClick, draggable, moving }: { t: Task; onClick: () => void; draggable: boolean; moving: boolean }) {
  const late = t.deadline && isOverdue(`${t.deadline}T23:59:59`);
  const [dragging, setDragging] = useState(false);
  const ck = checklistProgress(t.checklist);
  return (
    <li className={`${dragging ? "dragging" : ""} ${moving ? "moving" : ""}`}
      draggable={draggable}
      onDragStart={(e) => { e.dataTransfer.setData(DRAG_TYPE, String(t.id)); e.dataTransfer.effectAllowed = "move"; setDragging(true); }}
      onDragEnd={() => setDragging(false)}>
      <button onClick={onClick} title={draggable ? "Открыть · перетащите на другой проект, чтобы перенести" : undefined}>
        {draggable && <span className="grip" aria-hidden="true">⋮⋮</span>}
        <span className={`st st-${t.status}`} title={STATUS_LABEL[t.status]} />
        <span className="tt">{t.title}</span>
        {ck.total > 0 && <span className={`mono ck ${ck.done === ck.total ? "full" : ""}`} title="Чеклист">{ck.done}/{ck.total}</span>}
        <span className={`mono td ${late ? "over" : ""}`}>{t.deadline ? showDate(t.deadline) : ""}</span>
      </button>
    </li>
  );
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}
