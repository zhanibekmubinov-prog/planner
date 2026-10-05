import { useEffect, useState } from "react";
import { canEdit, Direction, dirColor, isOverdue, MIND_COLOR, Project, projColor, showDate, STATUS_LABEL, Task } from "./api";
import { MindGlyph } from "./MindMaps";
import { UserChip } from "./Account";
import type { User } from "./api";
import { canDropTask, DRAG_PROJECT, DRAG_TASK, dragId, dropProjectOnProject, dropTaskOnTask, hasType, moveTaskToProject } from "./dnd";
import type { Store } from "./store";
import { Space, SPACE_LABEL } from "./spaces";

export type View =
  | { kind: "overview" }
  | { kind: "direction"; directionId: number }                                    // карта проектов направления
  | { kind: "board"; directionId: number | null; projectId?: number | "none"; orphans?: boolean }    // канбан: все / направление / проект / без проекта / без направления
  | { kind: "people" } | { kind: "tools" } | { kind: "shared" } | { kind: "tracker" }
  | { kind: "mindmaps"; directionId?: number | null } | { kind: "mindmap"; id: number } | { kind: "inbox" }
  | { kind: "archive" } | { kind: "trash" } | { kind: "guests" };

export type SidebarProps = {
  directions: Direction[]; projects: Project[]; tasks: Task[]; view: View; mindmapCount: number; inboxCount: number; sharedCount: number;
  trashCount: number;
  // v1.7: слой. Вкладки стоят под логотипом, над блоком разделов — видны всегда, переключение в один клик.
  space: Space; onSpace: (s: Space) => void; personalCount: number; orgCount: number;
  me: User | null; onProfile: () => void;
  onView: (v: View) => void; onNewDirection: () => void; onNewProject: (d: Direction) => void;
  onDirectionMenu: (d: Direction, e: React.MouseEvent) => void; onProjectMenu: (p: Project, e: React.MouseEvent) => void;
  // v1.6: задачи раскрываются под проектом, перетаскиваются между проектами и направлениями
  onOpenTask?: (t: Task) => void;
  store?: Store;                                   // нужен только для перетаскивания; без него панель работает как раньше
  onMoveProject?: (p: Project, to: Direction) => void;
};
type Props = SidebarProps;

const OPEN_KEY = "planner.dirs.open";
const EXP_KEY = "planner.dirs.expanded";
const EXP_PROJ_KEY = "planner.projects.expanded";
const TASKS_SHOWN = 10;   // сколько задач показываем под проектом, дальше — «ещё N»
const readOpen = () => { try { return localStorage.getItem(OPEN_KEY) !== "0"; } catch { return true; } };
const readIds = (key: string): number[] => { try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; } };

export default function Sidebar({ directions, projects, tasks, view, mindmapCount, inboxCount, sharedCount, trashCount, space, onSpace, personalCount, orgCount, me, onProfile, onView, onNewDirection, onNewProject, onDirectionMenu, onProjectMenu, onOpenTask, store, onMoveProject }: Props) {
  const [open, setOpen] = useState(readOpen);
  const [expanded, setExpanded] = useState<number[]>(() => readIds(EXP_KEY));
  const [expProjects, setExpProjects] = useState<number[]>(() => readIds(EXP_PROJ_KEY));
  const [allTasks, setAllTasks] = useState<number[]>([]);      // проекты, у которых раскрыт полный список задач
  const [filter, setFilter] = useState("");
  const [dropOn, setDropOn] = useState<string | null>(null);   // подсветка цели переноса: "d12" | "p7" | "t93"
  useEffect(() => { try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch { /* приватный режим */ } }, [open]);
  useEffect(() => { try { localStorage.setItem(EXP_KEY, JSON.stringify(expanded)); } catch { /* приватный режим */ } }, [expanded]);
  useEffect(() => { try { localStorage.setItem(EXP_PROJ_KEY, JSON.stringify(expProjects)); } catch { /* приватный режим */ } }, [expProjects]);
  // Н8: чистим id направлений, которых больше нет (после первой загрузки)
  useEffect(() => {
    if (!directions.length) return;
    setExpanded((xs) => { const ys = xs.filter((id) => directions.some((d) => d.id === id)); return ys.length === xs.length ? xs : ys; });
  }, [directions]);
  useEffect(() => {
    if (!projects.length) return;
    setExpProjects((xs) => { const ys = xs.filter((id) => projects.some((p) => p.id === id)); return ys.length === xs.length ? xs : ys; });
  }, [projects]);

  const openTasks = tasks.filter((t) => t.status !== "done");
  // В5: задачи архивных проектов в счётчик направления не входят — как и на карте проектов
  const archivedProjectIds = new Set(projects.filter((p) => p.status === "archived").map((p) => p.id));
  const countFor = (id: number) => openTasks.filter((t) => t.directions.some((d) => d.id === id) && !(t.project_id != null && archivedProjectIds.has(t.project_id))).length;
  const projectTasks = (id: number) => openTasks.filter((t) => t.project_id === id)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.priority - b.priority || (a.deadline || "9").localeCompare(b.deadline || "9"));
  const orphans = openTasks.filter((t) => t.directions.length === 0).length;
  // Доля закрытых задач направления — тонкая шкала под названием
  const doneRatio = (id: number) => {
    const all = tasks.filter((t) => t.directions.some((d) => d.id === id));
    return all.length ? all.filter((t) => t.status === "done").length / all.length : 0;
  };
  const isAllTasks = view.kind === "board" && view.directionId === null && !view.orphans;
  const isOrphans = view.kind === "board" && view.directionId === null && !!view.orphans;
  const isDir = (id: number) => (view.kind === "direction" && view.directionId === id) || (view.kind === "board" && view.directionId === id && view.projectId === undefined);
  const isProject = (id: number) => view.kind === "board" && view.projectId === id;
  const inDir = (id: number) => (view.kind === "direction" || view.kind === "board") && view.directionId === id;
  const visible = directions.filter((d) => d.status !== "archived");
  const archived = directions.filter((d) => d.status === "archived").length + projects.filter((p) => p.status === "archived" && directions.some((d) => d.id === p.direction_id && d.status !== "archived")).length;
  const q = filter.trim().toLowerCase();
  const shown = q ? visible.filter((d) => d.name.toLowerCase().includes(q) || projects.some((p) => p.direction_id === d.id && p.name.toLowerCase().includes(q))) : visible;
  const activeDir = (view.kind === "board" || view.kind === "direction") && view.directionId ? directions.find((d) => d.id === view.directionId) : null;
  // Список свёрнут, но открыто направление — покажем его одной строкой, чтобы было видно, где мы
  const collapsedShown = !open && activeDir && activeDir.status !== "archived" ? [activeDir] : [];
  const toggle = (set: React.Dispatch<React.SetStateAction<number[]>>) => (id: number, e: React.MouseEvent) => {
    e.stopPropagation(); set((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
  };
  const toggleExpanded = toggle(setExpanded);
  const toggleProject = toggle(setExpProjects);
  const openDirection = (d: Direction) => onView({ kind: "direction", directionId: d.id });

  // ── Перетаскивание (v1.6). Без store панель ведёт себя как раньше: ничего не тянется. ──
  const dnd = !!store;
  const onDirection = (d: Direction) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!dnd) return;
      const task = hasType(e, DRAG_TASK) && canDropTask(store!, d, null);
      const proj = hasType(e, DRAG_PROJECT) && canEdit(d.access) && d.access !== "via";
      if (!task && !proj) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropOn(`d${d.id}`);
    },
    onDragLeave: () => setDropOn((v) => (v === `d${d.id}` ? null : v)),
    onDrop: (e: React.DragEvent) => {
      setDropOn(null); if (!dnd) return;
      const tid = dragId(e, DRAG_TASK);
      if (tid) { e.preventDefault(); void moveTaskToProject(store!, tid, null, d.id); return; }
      const pid = dragId(e, DRAG_PROJECT);
      const p = pid ? projects.find((x) => x.id === pid) : null;
      if (p && p.direction_id !== d.id && onMoveProject) { e.preventDefault(); onMoveProject(p, d); }
    },
  });
  const onProject = (p: Project) => ({
    draggable: dnd && canEdit(p.access),
    onDragStart: (e: React.DragEvent) => { e.dataTransfer.setData(DRAG_PROJECT, String(p.id)); e.dataTransfer.effectAllowed = "move"; },
    onDragOver: (e: React.DragEvent) => {
      if (!dnd) return;
      const task = hasType(e, DRAG_TASK) && canEdit(p.access);
      const proj = hasType(e, DRAG_PROJECT) && canEdit(p.access);
      if (!task && !proj) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropOn(`p${p.id}`);
    },
    onDragLeave: () => setDropOn((v) => (v === `p${p.id}` ? null : v)),
    onDrop: (e: React.DragEvent) => {
      setDropOn(null); if (!dnd) return;
      const tid = dragId(e, DRAG_TASK);
      if (tid) { e.preventDefault(); void moveTaskToProject(store!, tid, p.id); return; }
      const pid = dragId(e, DRAG_PROJECT);
      if (pid && pid !== p.id) {
        e.preventDefault();
        const moved = projects.find((x) => x.id === pid);
        if (moved && moved.direction_id !== p.direction_id) { const to = directions.find((d) => d.id === p.direction_id); if (to && onMoveProject) onMoveProject(moved, to); }
        else void dropProjectOnProject(store!, pid, p);
      }
    },
  });
  const onTask = (t: Task) => ({
    draggable: dnd && canEdit(t.access),
    onDragStart: (e: React.DragEvent) => { e.stopPropagation(); e.dataTransfer.setData(DRAG_TASK, String(t.id)); e.dataTransfer.effectAllowed = "move"; },
    onDragOver: (e: React.DragEvent) => {
      if (!dnd || !hasType(e, DRAG_TASK)) return;
      e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = "move"; setDropOn(`t${t.id}`);
    },
    onDragLeave: () => setDropOn((v) => (v === `t${t.id}` ? null : v)),
    onDrop: (e: React.DragEvent) => {
      setDropOn(null); if (!dnd) return;
      const tid = dragId(e, DRAG_TASK);
      if (tid && tid !== t.id) { e.preventDefault(); e.stopPropagation(); void dropTaskOnTask(store!, tid, t); }
    },
  });

  return (
    <aside className="side">
      <div className="brand"><h1><img className="brand-mark" src="/cis-mark.png" alt="CIS" /><span className="brand-name">Planner</span></h1><span className="ver">v1.7</span></div>
      {me && <UserChip me={me} onClick={onProfile} />}

      <div className="space-tabs" role="tablist" aria-label="Слой">
        {(["personal", "org"] as Space[]).map((s) => (
          <button key={s} role="tab" aria-selected={space === s} className={`space-tab ${space === s ? "on" : ""}`}
            onClick={() => onSpace(s)}
            title={s === "personal" ? "Мои направления — то, чем никто не занимается кроме меня" : "Рабочее: то, чем я поделился, что открыли мне и что я поручаю"}>
            {SPACE_LABEL[s]}
            <span className="n">{s === "personal" ? personalCount : orgCount}</span>
          </button>
        ))}
      </div>

      <div className="side-list side-top">
        <button className={`side-item ${view.kind === "overview" ? "active" : ""}`} onClick={() => onView({ kind: "overview" })}>
          <span className="swatch map" />
          <span className="name">Карта направлений</span>
          <span className="count" />
        </button>
        <button className={`side-item tracker-item ${view.kind === "tracker" ? "active" : ""}`} onClick={() => onView({ kind: "tracker" })}
          title="Все проекты и задачи одной таблицей: ответственный, срок, статус">
          <span className="swatch tracker" aria-hidden="true" />
          <span className="name">Action Tracker</span>
          <span className="count">{openTasks.length || ""}</span>
        </button>
        <button className={`side-item inbox-nav ${view.kind === "inbox" ? "active" : ""}`} onClick={() => onView({ kind: "inbox" })}>
          <span className="swatch inbox" />
          <span className="name">Мне поручено</span>
          <span className={`count ${inboxCount ? "hot" : ""}`}>{inboxCount || ""}</span>
        </button>
        <button className={`side-item ${view.kind === "shared" ? "active" : ""}`} onClick={() => onView({ kind: "shared" })}>
          <span className="swatch shared" />
          <span className="name">Общие</span>
          <span className="count">{sharedCount || ""}</span>
        </button>
        <button className={`side-item ${isAllTasks ? "active" : ""}`} onClick={() => onView({ kind: "board", directionId: null })}>
          <span className="swatch" style={{ background: "linear-gradient(135deg,#2F6FED,#0E9F6E,#D97706)" }} />
          <span className="name">Все задачи</span>
          <span className="count">{openTasks.length}</span>
        </button>
        <button className={`side-item mind-item ${view.kind === "mindmaps" || view.kind === "mindmap" ? "active" : ""}`} onClick={() => onView({ kind: "mindmaps" })} style={{ ["--mind" as string]: MIND_COLOR }}>
          <span className="swatch mind"><MindGlyph size={12} /></span>
          <span className="name">Майндмапы</span>
          <span className="count">{mindmapCount}</span>
        </button>
        <button className={`side-item ${view.kind === "people" ? "active" : ""}`} onClick={() => onView({ kind: "people" })}>
          <span className="swatch people" />
          <span className="name">Люди</span>
          <span className="count" />
        </button>
        <button className={`side-item ${view.kind === "tools" ? "active" : ""}`} onClick={() => onView({ kind: "tools" })}>
          <span className="swatch tools" />
          <span className="name">Тулы</span>
          <span className="count" />
        </button>
      </div>

      <div className={`side-group ${open ? "open" : ""}`}>
        <div className="side-group-head">
          <button className="side-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open} title={open ? "Свернуть список направлений" : "Развернуть список направлений"}>
            <span className="chev" aria-hidden="true">▸</span>
            <span className="name">Направления</span>
            <span className="count mono">{visible.length}</span>
          </button>
          <button className="plus" onClick={onNewDirection} title="Новое направление" aria-label="Новое направление">+</button>
        </div>
        {open && (visible.length > 8 || projects.length > 12) && (
          <input className="side-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="найти направление или проект…" aria-label="Фильтр направлений" />
        )}
        <div className="side-list side-dirs">
          {(open ? shown : collapsedShown).map((d) => {
            const ps = projects.filter((p) => p.direction_id === d.id && p.status !== "archived" && (!q || d.name.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)))
              .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id);
            const isExp = expanded.includes(d.id) || (!!q && ps.length > 0) || (inDir(d.id) && view.kind === "board" && view.projectId !== undefined);
            const shared = d.access === "edit" || d.access === "view";
            return (
              <div key={d.id} className={`side-dir ${isExp ? "expanded" : ""}`}>
                <div className={`side-item dir ${isDir(d.id) ? "active" : ""} ${d.status === "paused" ? "paused" : ""} ${shared ? "shared-item" : ""} ${dropOn === `d${d.id}` ? "drop-here" : ""}`}
                  role="button" tabIndex={0}
                  onClick={() => openDirection(d)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDirection(d); } if (e.key === "ArrowRight" && !isExp) toggleExpanded(d.id, e as unknown as React.MouseEvent); if (e.key === "ArrowLeft" && isExp) toggleExpanded(d.id, e as unknown as React.MouseEvent); }}
                  onContextMenu={(e) => onDirectionMenu(d, e)}
                  {...onDirection(d)}
                  title={`${d.name}${d.status === "paused" ? " · на паузе" : ""}${shared ? ` · открыл ${d.owner?.name ?? "коллега"}` : ""}`}>
                  <button className={`chev-btn ${isExp ? "open" : ""} ${ps.length === 0 && d.access === "view" ? "empty" : ""}`} onClick={(e) => toggleExpanded(d.id, e)} tabIndex={-1}
                    aria-label={isExp ? "Свернуть проекты" : "Показать проекты"} title={ps.length ? `${ps.length} проект${ps.length === 1 ? "" : ps.length < 5 ? "а" : "ов"}` : "Проектов нет"}>▸</button>
                  <span className="swatch" style={{ background: dirColor(d) }} />
                  <span className="name">{d.name}{shared && <span className="shared-mark" aria-label="общее">⇄</span>}</span>
                  <span className="count">{countFor(d.id)}</span>
                  <button className="more" onClick={(e) => onDirectionMenu(d, e)} title="Действия с направлением" aria-label={`Действия: ${d.name}`}>⋯</button>
                  <span className="meter" aria-hidden="true"><span style={{ width: `${Math.round(doneRatio(d.id) * 100)}%`, background: dirColor(d) }} /></span>
                </div>
                {isExp && (
                  <div className="side-projects" style={{ ["--dir" as string]: dirColor(d) }}>
                    {ps.map((p) => {
                      const pts = projectTasks(p.id);
                      const openList = expProjects.includes(p.id) || (view.kind === "board" && view.projectId === p.id);
                      const showAll = allTasks.includes(p.id);
                      const list = showAll ? pts : pts.slice(0, TASKS_SHOWN);
                      return (
                        <div key={p.id} className={`side-proj ${openList ? "expanded" : ""}`}>
                          <div className={`side-item proj ${isProject(p.id) ? "active" : ""} ${p.status === "paused" ? "paused" : ""} ${dropOn === `p${p.id}` ? "drop-here" : ""}`}
                            role="button" tabIndex={0}
                            onClick={() => onView({ kind: "board", directionId: d.id, projectId: p.id })}
                            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onView({ kind: "board", directionId: d.id, projectId: p.id }); } if (e.key === "ArrowRight" && !openList) toggleProject(p.id, e as unknown as React.MouseEvent); if (e.key === "ArrowLeft" && openList) toggleProject(p.id, e as unknown as React.MouseEvent); }}
                            onContextMenu={(e) => onProjectMenu(p, e)}
                            {...onProject(p)}
                            title={p.status === "paused" ? `${p.name} · на паузе` : p.name}>
                            <button className={`chev-btn ${openList ? "open" : ""} ${pts.length === 0 ? "empty" : ""}`} onClick={(e) => toggleProject(p.id, e)} tabIndex={-1}
                              aria-label={openList ? `Свернуть задачи: ${p.name}` : `Показать задачи: ${p.name}`}
                              title={pts.length ? `${pts.length} открытых задач` : "Открытых задач нет"}>▸</button>
                            <span className="swatch" style={{ background: projColor(p, directions) }} />
                            <span className="name">{p.name}</span>
                            <span className="count">{pts.length || ""}</span>
                            <button className="more" onClick={(e) => onProjectMenu(p, e)} title="Действия с проектом" aria-label={`Действия: ${p.name}`}>⋯</button>
                          </div>
                          {openList && (
                            <div className="side-tasks">
                              {list.map((t) => (
                                <div key={t.id} className={`side-item task ${dropOn === `t${t.id}` ? "drop-here" : ""}`}
                                  role="button" tabIndex={0}
                                  onClick={() => onOpenTask?.(t)}
                                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpenTask?.(t); } }}
                                  {...onTask(t)}
                                  title={`${t.title} · ${STATUS_LABEL[t.status]}${t.deadline ? ` · до ${showDate(t.deadline)}` : ""}`}>
                                  <span className={`st st-${t.status}`} aria-hidden="true" />
                                  <span className="name">{t.title}</span>
                                  <span className={`count mono ${t.deadline && isOverdue(`${t.deadline}T23:59:59`) ? "over" : ""}`}>{t.deadline ? showDate(t.deadline) : ""}</span>
                                </div>
                              ))}
                              {pts.length > list.length && (
                                <button className="side-item task more-tasks" onClick={() => setAllTasks((xs) => [...xs, p.id])}>
                                  <span className="st hollow" aria-hidden="true" />
                                  <span className="name">ещё {pts.length - list.length}</span>
                                  <span className="count" />
                                </button>
                              )}
                              {pts.length === 0 && <span className="side-empty small">открытых задач нет</span>}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {d.access !== "view" && d.access !== "via" && (
                      <button className="side-item proj add-proj" onClick={() => onNewProject(d)} title="Новый проект в этом направлении">
                        <span className="swatch plus-swatch">+</span>
                        <span className="name">{ps.length ? "проект" : "первый проект"}</span>
                        <span className="count" />
                      </button>
                    )}
                    {ps.length === 0 && (d.access === "view" || d.access === "via") && <span className="side-empty small">проектов нет</span>}
                  </div>
                )}
              </div>
            );
          })}
          {open && visible.length === 0 && <p className="side-empty">Пока нет направлений — нажмите «+».</p>}
          {open && q && shown.length === 0 && <p className="side-empty">Ничего не найдено.</p>}
        </div>
      </div>

      {/* Служебные разделы (v0.8): сироты, архив, корзина — тише основных, но всегда под рукой */}
      <div className="side-list side-foot">
        {orphans > 0 && (
          <button className={`side-item aux ${isOrphans ? "active" : ""}`} onClick={() => onView({ kind: "board", directionId: null, orphans: true })} title="Задачи, у которых нет ни одного направления">
            <span className="swatch hollow-swatch" />
            <span className="name">Без направления</span>
            <span className="count">{orphans}</span>
          </button>
        )}
        <button className={`side-item aux ${view.kind === "archive" ? "active" : ""}`} onClick={() => onView({ kind: "archive" })} title="Направления и проекты в архиве">
          <span className="swatch archive-swatch" />
          <span className="name">Архив</span>
          <span className="count">{archived || ""}</span>
        </button>
        {me?.is_admin && (
          <button className={`side-item aux ${view.kind === "guests" ? "active" : ""}`} onClick={() => onView({ kind: "guests" })} title="Внешние участники: подрядчики и партнёры, которых вы пригласили">
            <span className="swatch hollow-swatch" />
            <span className="name">Гости</span>
          </button>
        )}
        <button className={`side-item aux ${view.kind === "trash" ? "active" : ""}`} onClick={() => onView({ kind: "trash" })} title="Удалённое — можно вернуть в течение 30 дней">
          <span className="swatch trash-swatch" />
          <span className="name">Корзина</span>
          <span className="count">{trashCount || ""}</span>
        </button>
      </div>
    </aside>
  );
}
