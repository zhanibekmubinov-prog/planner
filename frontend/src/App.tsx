import { useEffect, useMemo, useState } from "react";
import { Direction } from "./api";
import Board from "./Board";
import DirectionModal from "./DirectionModal";
import { PeoplePage, ToolsPage } from "./Registry";
import Sidebar, { View } from "./Sidebar";
import { useStore } from "./store";
import TaskPanel from "./TaskPanel";
import "./styles.css";

export default function App() {
  const store = useStore();
  const [view, setView] = useState<View>({ kind: "board", directionId: null });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dirModal, setDirModal] = useState<{ open: boolean; direction: Direction | null }>({ open: false, direction: null });

  const direction = useMemo(
    () => (view.kind === "board" && view.directionId ? store.directions.find((d) => d.id === view.directionId) ?? null : null),
    [view, store.directions],
  );
  const selected = useMemo(() => store.tasks.find((t) => t.id === selectedId) ?? null, [store.tasks, selectedId]);

  // Направление удалили / заархивировали — уходим на «Все задачи»
  useEffect(() => {
    if (view.kind === "board" && view.directionId && !store.loading && !store.directions.some((d) => d.id === view.directionId)) {
      setView({ kind: "board", directionId: null });
    }
  }, [view, store.directions, store.loading]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSelectedId(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const showPanel = view.kind === "board" && selected !== null;

  return (
    <div className={`shell ${showPanel ? "with-panel" : ""}`}>
      <Sidebar
        directions={store.directions} tasks={store.tasks} view={view}
        onView={(v) => { setView(v); if (v.kind !== "board") setSelectedId(null); }}
        onNewDirection={() => setDirModal({ open: true, direction: null })}
      />

      <main className="main">
        {store.error && (
          <div className="error-bar" role="alert">
            <span>Не получилось связаться с сервером: {store.error}</span>
            <button className="btn sm" onClick={() => { store.setError(null); void store.reload(); }}>Повторить</button>
            <button className="btn ghost sm" onClick={() => store.setError(null)} aria-label="Скрыть">×</button>
          </div>
        )}
        {store.loading ? (
          <div className="state"><span className="mono">загрузка…</span></div>
        ) : view.kind === "people" ? (
          <PeoplePage store={store} />
        ) : view.kind === "tools" ? (
          <ToolsPage store={store} />
        ) : store.directions.length === 0 && store.tasks.length === 0 ? (
          <div className="state">
            <h3>Начнём с направления</h3>
            <p>Направление — это область, которую вы ведёте: закуп, команда, техника. Под ним живут задачи.</p>
            <button className="btn primary" onClick={() => setDirModal({ open: true, direction: null })}>+ Первое направление</button>
          </div>
        ) : (
          <Board store={store} direction={direction} selectedId={selectedId} onSelect={setSelectedId} onEditDirection={(d) => setDirModal({ open: true, direction: d })} />
        )}
      </main>

      {showPanel && selected && (
        <TaskPanel key={selected.id} store={store} task={selected} onClose={() => setSelectedId(null)} onDeleted={() => setSelectedId(null)} />
      )}

      {dirModal.open && (
        <DirectionModal
          store={store} direction={dirModal.direction}
          onClose={() => setDirModal({ open: false, direction: null })}
          onSaved={(d) => { setDirModal({ open: false, direction: null }); setView({ kind: "board", directionId: d.id }); }}
          onDeleted={() => { setDirModal({ open: false, direction: null }); setView({ kind: "board", directionId: null }); }}
        />
      )}
    </div>
  );
}
