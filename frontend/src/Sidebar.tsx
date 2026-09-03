import { useEffect, useState } from "react";
import { Direction, dirColor, MIND_COLOR, Project, projColor, Task } from "./api";
import { MindGlyph } from "./MindMaps";
import { UserChip } from "./Account";
import type { User } from "./api";

export type View =
  | { kind: "overview" }
  | { kind: "direction"; directionId: number }                                    // карта проектов направления
  | { kind: "board"; directionId: number | null; projectId?: number | "none" }    // канбан: все / направление / проект / без проекта
  | { kind: "people" } | { kind: "tools" } | { kind: "shared" }
  | { kind: "mindmaps"; directionId?: number | null } | { kind: "mindmap"; id: number } | { kind: "inbox" };

type Props = {
  directions: Direction[]; projects: Project[]; tasks: Task[]; view: View; mindmapCount: number; inboxCount: number; sharedCount: number;
  me: User | null; onProfile: () => void;
  onView: (v: View) => void; onNewDirection: () => void; onNewProject: (d: Direction) => void;
  onDirectionMenu: (d: Direction, e: React.MouseEvent) => void; onProjectMenu: (p: Project, e: React.MouseEvent) => void;
};

const OPEN_KEY = "planner.dirs.open";
const EXP_KEY = "planner.dirs.expanded";
const readOpen = () => { try { return localStorage.getItem(OPEN_KEY) !== "0"; } catch { return true; } };
const readExpanded = (): number[] => { try { return JSON.parse(localStorage.getItem(EXP_KEY) || "[]"); } catch { return []; } };

export default function Sidebar({ directions, projects, tasks, view, mindmapCount, inboxCount, sharedCount, me, onProfile, onView, onNewDirection, onNewProject, onDirectionMenu, onProjectMenu }: Props) {
  const [open, setOpen] = useState(readOpen);
  const [expanded, setExpanded] = useState<number[]>(readExpanded);
  const [filter, setFilter] = useState("");
  useEffect(() => { try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch { /* приватный режим */ } }, [open]);
  useEffect(() => { try { localStorage.setItem(EXP_KEY, JSON.stringify(expanded)); } catch { /* приватный режим */ } }, [expanded]);

  const openTasks = tasks.filter((t) => t.status !== "done");
  const countFor = (id: number) => openTasks.filter((t) => t.directions.some((d) => d.id === id)).length;
  const countProject = (id: number) => openTasks.filter((t) => t.project_id === id).length;
  // Доля закрытых задач направления — тонкая шкала под названием
  const doneRatio = (id: number) => {
    const all = tasks.filter((t) => t.directions.some((d) => d.id === id));
    return all.length ? all.filter((t) => t.status === "done").length / all.length : 0;
  };
  const isAllTasks = view.kind === "board" && view.directionId === null;
  const isDir = (id: number) => (view.kind === "direction" && view.directionId === id) || (view.kind === "board" && view.directionId === id && view.projectId === undefined);
  const isProject = (id: number) => view.kind === "board" && view.projectId === id;
  const inDir = (id: number) => (view.kind === "direction" || view.kind === "board") && view.directionId === id;
  const visible = directions.filter((d) => d.status !== "archived");
  const q = filter.trim().toLowerCase();
  const shown = q ? visible.filter((d) => d.name.toLowerCase().includes(q) || projects.some((p) => p.direction_id === d.id && p.name.toLowerCase().includes(q))) : visible;
  const activeDir = (view.kind === "board" || view.kind === "direction") && view.directionId ? directions.find((d) => d.id === view.directionId) : null;
  // Список свёрнут, но открыто направление — покажем его одной строкой, чтобы было видно, где мы
  const collapsedShown = !open && activeDir && activeDir.status !== "archived" ? [activeDir] : [];
  const toggleExpanded = (id: number, e: React.MouseEvent) => { e.stopPropagation(); setExpanded((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id])); };
  const openDirection = (d: Direction) => onView({ kind: "direction", directionId: d.id });

  return (
    <aside className="side">
      <div className="brand"><h1><img className="brand-mark" src="/cis-mark.png" alt="CIS" /><span className="brand-name">Planner</span></h1><span className="ver">v0.6</span></div>
      {me && <UserChip me={me} onClick={onProfile} />}

      <div className="side-list side-top">
        <button className={`side-item ${view.kind === "overview" ? "active" : ""}`} onClick={() => onView({ kind: "overview" })}>
          <span className="swatch map" />
          <span className="name">Карта направлений</span>
          <span className="count" />
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
            const ps = projects.filter((p) => p.direction_id === d.id && p.status !== "archived" && (!q || d.name.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)));
            const isExp = expanded.includes(d.id) || (!!q && ps.length > 0) || (inDir(d.id) && view.kind === "board" && view.projectId !== undefined);
            const shared = d.access === "edit" || d.access === "view";
            return (
              <div key={d.id} className={`side-dir ${isExp ? "expanded" : ""}`}>
                <div className={`side-item dir ${isDir(d.id) ? "active" : ""} ${d.status === "paused" ? "paused" : ""} ${shared ? "shared-item" : ""}`}
                  role="button" tabIndex={0}
                  onClick={() => openDirection(d)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDirection(d); } if (e.key === "ArrowRight" && !isExp) toggleExpanded(d.id, e as unknown as React.MouseEvent); if (e.key === "ArrowLeft" && isExp) toggleExpanded(d.id, e as unknown as React.MouseEvent); }}
                  onContextMenu={(e) => onDirectionMenu(d, e)}
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
                    {ps.map((p) => (
                      <div key={p.id} className={`side-item proj ${isProject(p.id) ? "active" : ""} ${p.status === "paused" ? "paused" : ""}`}
                        role="button" tabIndex={0}
                        onClick={() => onView({ kind: "board", directionId: d.id, projectId: p.id })}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onView({ kind: "board", directionId: d.id, projectId: p.id }); } }}
                        onContextMenu={(e) => onProjectMenu(p, e)}
                        title={p.status === "paused" ? `${p.name} · на паузе` : p.name}>
                        <span className="swatch" style={{ background: projColor(p, directions) }} />
                        <span className="name">{p.name}</span>
                        <span className="count">{countProject(p.id) || ""}</span>
                        <button className="more" onClick={(e) => onProjectMenu(p, e)} title="Действия с проектом" aria-label={`Действия: ${p.name}`}>⋯</button>
                      </div>
                    ))}
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
    </aside>
  );
}
