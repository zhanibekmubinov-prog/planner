// Раздел «Архив» (владелец, решение 4): направления со статусом archived (с их проектами) и архивные проекты живых направлений.
// Отсюда всё возвращается одной кнопкой; открыть можно как есть — доска покажет задачи.
import { useState } from "react";
import { canEdit, Direction, dirColor, errorText, nProjects, nTasks, Project, projColor, put } from "./api";
import { projectBody } from "./ProjectMenu";
import { Store } from "./store";
import { directionBody } from "./DirectionMenu";

type Props = { store: Store; onOpenDirection: (id: number) => void; onOpenProject: (p: Project) => void };

export default function ArchivePage({ store, onOpenDirection, onOpenProject }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const dirs = store.directions.filter((d) => d.status === "archived");
  const liveIds = new Set(store.directions.filter((d) => d.status !== "archived").map((d) => d.id));
  const looseProjects = store.projects.filter((p) => p.status === "archived" && liveIds.has(p.direction_id));
  const openIn = (pred: (t: (typeof store.tasks)[number]) => boolean) => store.tasks.filter((t) => t.status !== "done" && pred(t)).length;

  async function restoreDirection(d: Direction) {
    setBusy(`d${d.id}`);
    try { await put<Direction>(`/directions/${d.id}`, { ...directionBody(d), status: "active" }); await store.reloadDirections(); }
    catch (e) { store.setError(errorText(e)); } finally { setBusy(null); }
  }
  async function restoreProject(p: Project) {
    setBusy(`p${p.id}`);
    try { await put<Project>(`/projects/${p.id}`, { ...projectBody(p), status: "active" }); await store.reloadProjects(); }
    catch (e) { store.setError(errorText(e)); } finally { setBusy(null); }
  }

  const empty = dirs.length === 0 && looseProjects.length === 0;
  return (
    <div className="page archive-page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2><span className="swatch archive-swatch" />Архив</h2>
        <span className="spacer" />
        <span className="hint">{empty ? "" : `${dirs.length ? nDirections(dirs.length) : ""}${dirs.length && looseProjects.length ? " · " : ""}${looseProjects.length ? nProjects(looseProjects.length) : ""}`}</span>
      </div>
      <p className="hint">Сюда попадает то, что убрали с карты и из левой панели «В архив». Задачи никуда не делись — они внутри. «Вернуть» — и направление или проект снова в работе.</p>

      {empty ? (
        <div className="state" style={{ flex: "none", padding: "60px 20px" }}>
          <h3>Архив пуст</h3>
          <p>Убрать направление или проект в архив: правая кнопка или «⋯» → «В архив».</p>
        </div>
      ) : (
        <>
          {dirs.map((d) => {
            const ps = store.projects.filter((p) => p.direction_id === d.id);
            const open = openIn((t) => t.directions.some((x) => x.id === d.id));
            return (
              <section key={d.id} className="arch-group" style={{ ["--dir" as string]: dirColor(d) }}>
                <div className="arch-row head">
                  <button className="arch-name" onClick={() => onOpenDirection(d.id)} title="Открыть карту проектов"><span className="swatch" style={{ background: dirColor(d) }} />{d.name}</button>
                  <span className="hint">направление · {nProjects(ps.length)} · {open} откр. {nTasks(open).replace(/^\d+ /, "")}</span>
                  <span className="row">
                    <button className="btn sm" onClick={() => onOpenDirection(d.id)}>Открыть</button>
                    {canEdit(d.access) && d.access !== "via" && <button className="btn primary sm" disabled={busy === `d${d.id}`} onClick={() => restoreDirection(d)}>Вернуть из архива</button>}
                  </span>
                </div>
                {ps.map((p) => (
                  <div key={p.id} className="arch-row sub">
                    <button className="arch-name" onClick={() => onOpenProject(p)}><span className="swatch" style={{ background: projColor(p, store.directions) }} />{p.name}</button>
                    <span className="hint">{p.status === "archived" ? "проект в архиве вместе с направлением" : "проект"} · {openIn((t) => t.project_id === p.id)} откр.</span>
                    <span className="row"><button className="btn sm" onClick={() => onOpenProject(p)}>Открыть</button></span>
                  </div>
                ))}
              </section>
            );
          })}
          {looseProjects.length > 0 && (
            <section className="arch-group">
              <h3 className="arch-title">Проекты в архиве</h3>
              {looseProjects.map((p) => {
                const d = store.directions.find((x) => x.id === p.direction_id);
                return (
                  <div key={p.id} className="arch-row" style={{ ["--dir" as string]: projColor(p, store.directions) }}>
                    <button className="arch-name" onClick={() => onOpenProject(p)}><span className="swatch" style={{ background: projColor(p, store.directions) }} />{p.name}</button>
                    <span className="hint">{d ? `${d.name} · ` : ""}{openIn((t) => t.project_id === p.id)} откр.</span>
                    <span className="row">
                      <button className="btn sm" onClick={() => onOpenProject(p)}>Открыть</button>
                      {canEdit(p.access) && <button className="btn primary sm" disabled={busy === `p${p.id}`} onClick={() => restoreProject(p)}>Вернуть из архива</button>}
                    </span>
                  </div>
                );
              })}
            </section>
          )}
        </>
      )}
    </div>
  );
}

const nDirections = (n: number) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? "направление" : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? "направления" : "направлений"}`;
