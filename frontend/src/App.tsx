import { useEffect, useMemo, useState } from "react";
import { LoginScreen, pickUpSession, ProfileModal } from "./Account";
import InboxPage from "./Inbox";
import { onUnauthorized } from "./api";
import { Direction } from "./api";
import Board from "./Board";
import DirectionModal from "./DirectionModal";
import { PeoplePage, ToolsPage } from "./Registry";
import MindMapEditor from "./MindMapEditor";
import MindMapsPage from "./MindMaps";
import Overview from "./Overview";
import Sidebar, { View } from "./Sidebar";
import { useStore } from "./store";
import TaskPanel from "./TaskPanel";
import "./styles.css";

export default function App() {
  const [authed, setAuthed] = useState<boolean>(() => pickUpSession());
  useEffect(() => onUnauthorized(() => setAuthed(false)), []);
  if (!authed) return <LoginScreen />;
  return <Workspace />;
}

function Workspace() {
  const store = useStore();
  const [profile, setProfile] = useState(false);
  const [view, setView] = useState<View>({ kind: "overview" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dirModal, setDirModal] = useState<{ open: boolean; direction: Direction | null }>({ open: false, direction: null });

  const direction = useMemo(
    () => (view.kind === "board" && view.directionId ? store.directions.find((d) => d.id === view.directionId) ?? null : null),
    [view, store.directions],
  );
  const selected = useMemo(() => store.tasks.find((t) => t.id === selectedId) ?? null, [store.tasks, selectedId]);
  // Задача из «Мне поручено» (не моя) — открываем раздел входящих
  useEffect(() => {
    if (selectedId && !selected && store.inbox.some((t) => t.id === selectedId)) { setView({ kind: "inbox" }); setSelectedId(null); }
  }, [selectedId, selected, store.inbox]);

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

  // Ссылка из напоминания: /?task=ID — открыть доску с этой задачей
  useEffect(() => {
    if (store.loading) return;
    const id = Number(new URLSearchParams(window.location.search).get("task"));
    if (id && store.tasks.some((t) => t.id === id)) {
      setView({ kind: "board", directionId: null }); setSelectedId(id);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [store.loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const showPanel = view.kind === "board" && selected !== null;

  return (
    <div className="shell">
      <Sidebar
        directions={store.directions} tasks={store.tasks} view={view} mindmapCount={store.mindmaps.length}
        inboxCount={store.inbox.filter((t) => t.status !== "done").length} me={store.me} onProfile={() => setProfile(true)}
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
        ) : view.kind === "overview" ? (
          <Overview
            store={store}
            onOpenDirection={(id) => setView({ kind: "board", directionId: id })}
            onOpenTask={(dirId, taskId) => { setView({ kind: "board", directionId: dirId }); setSelectedId(taskId); }}
            onNewDirection={() => setDirModal({ open: true, direction: null })}
          />
        ) : view.kind === "mindmaps" ? (
          <MindMapsPage store={store} filterDirection={view.directionId ?? null} onOpen={(id) => setView({ kind: "mindmap", id })} onOpenTask={(id) => { setView({ kind: "board", directionId: null }); setSelectedId(id); }} />
        ) : view.kind === "mindmap" ? (
          (() => {
            const m = store.mindmaps.find((x) => x.id === view.id);
            return m ? (
              <MindMapEditor key={m.id} store={store} map={m}
                onBack={() => setView(m.direction_id ? { kind: "board", directionId: m.direction_id } : { kind: "mindmaps" })}
                onDeleted={() => setView({ kind: "mindmaps" })}
                onOpenTask={(id) => { setView({ kind: "board", directionId: null }); setSelectedId(id); }} />
            ) : <div className="state"><h3>Майндмап не найден</h3><button className="btn" onClick={() => setView({ kind: "mindmaps" })}>К списку</button></div>;
          })()
        ) : view.kind === "inbox" ? (
          <InboxPage store={store} />
        ) : view.kind === "people" ? (
          <PeoplePage store={store} onOpenTask={(id) => { setView({ kind: "board", directionId: null }); setSelectedId(id); }} />
        ) : view.kind === "tools" ? (
          <ToolsPage store={store} />
        ) : store.directions.length === 0 && store.tasks.length === 0 ? (
          <div className="state">
            <h3>Начнём с направления</h3>
            <p>Направление — это область, которую вы ведёте: закуп, команда, техника. Под ним живут задачи.</p>
            <button className="btn primary" onClick={() => setDirModal({ open: true, direction: null })}>+ Первое направление</button>
          </div>
        ) : (
          <Board store={store} direction={direction} selectedId={selectedId} onSelect={setSelectedId} onEditDirection={(d) => setDirModal({ open: true, direction: d })}
            onOpenMindmap={(id) => setView({ kind: "mindmap", id })} onMindmaps={(dirId) => setView({ kind: "mindmaps", directionId: dirId })} />
        )}
      </main>

      {showPanel && selected && (
        <TaskPanel key={selected.id} store={store} task={selected} onClose={() => setSelectedId(null)} onDeleted={() => setSelectedId(null)}
          onOpenMindmap={(id) => { setSelectedId(null); setView({ kind: "mindmap", id }); }} />
      )}

      {profile && store.me && <ProfileModal store={store} onClose={() => setProfile(false)} />}

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
