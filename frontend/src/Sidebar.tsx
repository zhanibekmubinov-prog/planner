import { Direction, dirColor, MIND_COLOR, Task } from "./api";
import { MindGlyph } from "./MindMaps";

export type View =
  | { kind: "overview" } | { kind: "board"; directionId: number | null } | { kind: "people" } | { kind: "tools" }
  | { kind: "mindmaps"; directionId?: number | null } | { kind: "mindmap"; id: number };

type Props = {
  directions: Direction[]; tasks: Task[]; view: View; mindmapCount: number;
  onView: (v: View) => void; onNewDirection: () => void;
};

export default function Sidebar({ directions, tasks, view, mindmapCount, onView, onNewDirection }: Props) {
  const open = tasks.filter((t) => t.status !== "done");
  const countFor = (id: number) => open.filter((t) => t.directions.some((d) => d.id === id)).length;
  // Доля закрытых задач направления — тонкая шкала под названием
  const doneRatio = (id: number) => {
    const all = tasks.filter((t) => t.directions.some((d) => d.id === id));
    return all.length ? all.filter((t) => t.status === "done").length / all.length : 0;
  };
  const isBoard = (id: number | null) => view.kind === "board" && view.directionId === id;
  const visible = directions.filter((d) => d.status !== "archived");

  return (
    <aside className="side">
      <div className="brand"><h1>Planner</h1><span className="ver">v0.2</span></div>

      <div className="side-section">
        <span>Направления</span>
        <button onClick={onNewDirection} title="Новое направление" aria-label="Новое направление">+</button>
      </div>
      <div className="side-list">
        <button className={`side-item ${view.kind === "overview" ? "active" : ""}`} onClick={() => onView({ kind: "overview" })}>
          <span className="swatch map" />
          <span className="name">Карта направлений</span>
          <span className="count" />
        </button>
        <button className={`side-item ${isBoard(null) ? "active" : ""}`} onClick={() => onView({ kind: "board", directionId: null })}>
          <span className="swatch" style={{ background: "linear-gradient(135deg,#2F6FED,#0E9F6E,#D97706)" }} />
          <span className="name">Все задачи</span>
          <span className="count">{open.length}</span>
        </button>
        {visible.map((d) => (
          <button
            key={d.id}
            className={`side-item ${isBoard(d.id) ? "active" : ""} ${d.status === "paused" ? "paused" : ""}`}
            onClick={() => onView({ kind: "board", directionId: d.id })}
          >
            <span className="swatch" style={{ background: dirColor(d) }} />
            <span className="name">{d.name}</span>
            <span className="count">{countFor(d.id)}</span>
            <span className="meter" aria-hidden="true"><span style={{ width: `${Math.round(doneRatio(d.id) * 100)}%`, background: dirColor(d) }} /></span>
          </button>
        ))}
      </div>

      <nav className="side-nav">
        <button className={`side-item mind-item ${view.kind === "mindmaps" || view.kind === "mindmap" ? "active" : ""}`} onClick={() => onView({ kind: "mindmaps" })} style={{ ["--mind" as string]: MIND_COLOR }}>
          <span className="name"><span className="mind-ico"><MindGlyph size={13} /></span>Майндмапы</span>
          <span className="count">{mindmapCount}</span>
        </button>
        <button className={`side-item ${view.kind === "people" ? "active" : ""}`} onClick={() => onView({ kind: "people" })}>
          <span className="name">Люди</span>
        </button>
        <button className={`side-item ${view.kind === "tools" ? "active" : ""}`} onClick={() => onView({ kind: "tools" })}>
          <span className="name">Тулы</span>
        </button>
      </nav>
    </aside>
  );
}
