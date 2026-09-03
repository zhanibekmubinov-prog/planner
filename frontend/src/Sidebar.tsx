import { useEffect, useState } from "react";
import { Direction, dirColor, MIND_COLOR, Task } from "./api";
import { MindGlyph } from "./MindMaps";
import { UserChip } from "./Account";
import type { User } from "./api";

export type View =
  | { kind: "overview" } | { kind: "board"; directionId: number | null } | { kind: "people" } | { kind: "tools" }
  | { kind: "mindmaps"; directionId?: number | null } | { kind: "mindmap"; id: number } | { kind: "inbox" };

type Props = {
  directions: Direction[]; tasks: Task[]; view: View; mindmapCount: number; inboxCount: number; me: User | null; onProfile: () => void;
  onView: (v: View) => void; onNewDirection: () => void; onDirectionMenu: (d: Direction, e: React.MouseEvent) => void;
};

const OPEN_KEY = "planner.dirs.open";
const readOpen = () => { try { return localStorage.getItem(OPEN_KEY) !== "0"; } catch { return true; } };

export default function Sidebar({ directions, tasks, view, mindmapCount, inboxCount, me, onProfile, onView, onNewDirection, onDirectionMenu }: Props) {
  const [open, setOpen] = useState(readOpen);
  const [filter, setFilter] = useState("");
  useEffect(() => { try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch { /* приватный режим */ } }, [open]);

  const openTasks = tasks.filter((t) => t.status !== "done");
  const countFor = (id: number) => openTasks.filter((t) => t.directions.some((d) => d.id === id)).length;
  // Доля закрытых задач направления — тонкая шкала под названием
  const doneRatio = (id: number) => {
    const all = tasks.filter((t) => t.directions.some((d) => d.id === id));
    return all.length ? all.filter((t) => t.status === "done").length / all.length : 0;
  };
  const isBoard = (id: number | null) => view.kind === "board" && view.directionId === id;
  const visible = directions.filter((d) => d.status !== "archived");
  const q = filter.trim().toLowerCase();
  const shown = q ? visible.filter((d) => d.name.toLowerCase().includes(q)) : visible;
  const activeDir = view.kind === "board" && view.directionId ? directions.find((d) => d.id === view.directionId) : null;
  // Список свёрнут, но открыто направление — покажем его одной строкой, чтобы было видно, где мы
  const collapsedShown = !open && activeDir && activeDir.status !== "archived" ? [activeDir] : [];

  return (
    <aside className="side">
      <div className="brand"><h1><img className="brand-mark" src="/cis-mark.png" alt="CIS" /><span className="brand-name">Planner</span></h1><span className="ver">v0.4</span></div>
      {me && <UserChip me={me} onClick={onProfile} />}

      <div className="side-list side-top">
        <button className={`side-item ${view.kind === "overview" ? "active" : ""}`} onClick={() => onView({ kind: "overview" })}>
          <span className="swatch map" />
          <span className="name">Карта направлений</span>
          <span className="count" />
        </button>
        <button className={`side-item inbox-item ${view.kind === "inbox" ? "active" : ""}`} onClick={() => onView({ kind: "inbox" })}>
          <span className="swatch inbox" />
          <span className="name">Мне поручено</span>
          <span className={`count ${inboxCount ? "hot" : ""}`}>{inboxCount || ""}</span>
        </button>
        <button className={`side-item ${isBoard(null) ? "active" : ""}`} onClick={() => onView({ kind: "board", directionId: null })}>
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
        {open && visible.length > 8 && (
          <input className="side-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="найти направление…" aria-label="Фильтр направлений" />
        )}
        <div className="side-list side-dirs">
          {(open ? shown : collapsedShown).map((d) => (
            <div key={d.id} className={`side-item dir ${isBoard(d.id) ? "active" : ""} ${d.status === "paused" ? "paused" : ""}`}
              role="button" tabIndex={0}
              onClick={() => onView({ kind: "board", directionId: d.id })}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onView({ kind: "board", directionId: d.id }); } }}
              onContextMenu={(e) => onDirectionMenu(d, e)}
              title={d.status === "paused" ? `${d.name} · на паузе` : d.name}>
              <span className="swatch" style={{ background: dirColor(d) }} />
              <span className="name">{d.name}</span>
              <span className="count">{countFor(d.id)}</span>
              <button className="more" onClick={(e) => onDirectionMenu(d, e)} title="Действия с направлением" aria-label={`Действия: ${d.name}`}>⋯</button>
              <span className="meter" aria-hidden="true"><span style={{ width: `${Math.round(doneRatio(d.id) * 100)}%`, background: dirColor(d) }} /></span>
            </div>
          ))}
          {open && visible.length === 0 && <p className="side-empty">Пока нет направлений — нажмите «+».</p>}
          {open && q && shown.length === 0 && <p className="side-empty">Ничего не найдено.</p>}
        </div>
      </div>
    </aside>
  );
}
