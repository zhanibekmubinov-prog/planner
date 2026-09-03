import { useEffect, useMemo, useState } from "react";
import { LoginScreen, pickUpSession, ProfileModal } from "./Account";
import InboxPage from "./Inbox";
import { onUnauthorized } from "./api";
import { Direction, dirColor, Project, projColor, SharedWithMe } from "./api";
import Board from "./Board";
import DirectionModal from "./DirectionModal";
import DirectionMenu, { anchorFromEvent, MenuAnchor, RenameModal } from "./DirectionMenu";
import DirectionPage from "./DirectionPage";
import { PeoplePage, ToolsPage } from "./Registry";
import MindMapEditor from "./MindMapEditor";
import MindMapsPage from "./MindMaps";
import Overview from "./Overview";
import ProjectMenu, { ProjectAnchor, projectAnchorFromEvent, ProjectModal, RenameProjectModal } from "./ProjectMenu";
import ShareModal, { ShareTarget } from "./ShareModal";
import SharedPage from "./SharedPage";
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
  const [menu, setMenu] = useState<MenuAnchor | null>(null);            // контекстное меню направления
  const [pmenu, setPmenu] = useState<ProjectAnchor | null>(null);       // контекстное меню проекта
  const [renaming, setRenaming] = useState<Direction | null>(null);
  const [prenaming, setPrenaming] = useState<Project | null>(null);
  const [projModal, setProjModal] = useState<{ direction: Direction; project: Project | null } | null>(null);
  const [share, setShare] = useState<ShareTarget | null>(null);
  const openMenu = (d: Direction, e: React.MouseEvent) => setMenu(anchorFromEvent(d, e));
  const openProjectMenu = (p: Project, e: React.MouseEvent) => setPmenu(projectAnchorFromEvent(p, e));

  const direction = useMemo(
    () => ((view.kind === "board" || view.kind === "direction") && view.directionId ? store.directions.find((d) => d.id === view.directionId) ?? null : null),
    [view, store.directions],
  );
  const project = useMemo(
    () => (view.kind === "board" && typeof view.projectId === "number" ? store.projects.find((p) => p.id === view.projectId) ?? null : null),
    [view, store.projects],
  );
  const selected = useMemo(() => store.tasks.find((t) => t.id === selectedId) ?? null, [store.tasks, selectedId]);
  // Задача из «Мне поручено» (не моя) — открываем раздел входящих
  useEffect(() => {
    if (selectedId && !selected && store.inbox.some((t) => t.id === selectedId)) { setView({ kind: "inbox" }); setSelectedId(null); }
  }, [selectedId, selected, store.inbox]);

  // Направление или проект удалили / заархивировали — уходим уровнем выше
  useEffect(() => {
    if (store.loading) return;
    if ((view.kind === "board" || view.kind === "direction") && view.directionId && !store.directions.some((d) => d.id === view.directionId)) {
      setView({ kind: "board", directionId: null });
    } else if (view.kind === "board" && typeof view.projectId === "number" && !store.projects.some((p) => p.id === view.projectId)) {
      setView({ kind: "direction", directionId: view.directionId! });
    }
  }, [view, store.directions, store.projects, store.loading]);

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
  const shareDirection = (d: Direction) => setShare({ type: "direction", id: d.id, name: d.name, color: dirColor(d) });
  const shareProject = (p: Project) => setShare({ type: "project", id: p.id, name: p.name, color: projColor(p, store.directions) });
  const openShared = (s: SharedWithMe) => {
    if (s.entity_type === "direction") setView({ kind: "direction", directionId: s.entity_id });
    else if (s.entity_type === "project") { const p = store.projects.find((x) => x.id === s.entity_id); setView({ kind: "board", directionId: p?.direction_id ?? s.direction_id ?? null, projectId: s.entity_id }); }
    else { setView({ kind: "board", directionId: null }); setSelectedId(s.entity_id); }
  };
  const sharedOpen = store.shared.length;

  return (
    <div className="shell">
      <Sidebar
        directions={store.directions} projects={store.projects} tasks={store.tasks} view={view} mindmapCount={store.mindmaps.length}
        inboxCount={store.inbox.filter((t) => t.status !== "done").length} sharedCount={sharedOpen} me={store.me} onProfile={() => setProfile(true)}
        onView={(v) => { setView(v); if (v.kind !== "board") setSelectedId(null); }}
        onNewDirection={() => setDirModal({ open: true, direction: null })} onNewProject={(d) => setProjModal({ direction: d, project: null })}
        onDirectionMenu={openMenu} onProjectMenu={openProjectMenu}
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
            onOpenDirection={(id) => setView({ kind: "direction", directionId: id })}
            onOpenTask={(dirId, taskId) => { setView({ kind: "board", directionId: dirId }); setSelectedId(taskId); }}
            onNewDirection={() => setDirModal({ open: true, direction: null })} onDirectionMenu={openMenu}
          />
        ) : view.kind === "direction" && direction ? (
          <DirectionPage key={direction.id} store={store} direction={direction}
            onOpenBoard={(pid) => setView({ kind: "board", directionId: direction.id, projectId: pid })}
            onOpenTask={(pid, taskId) => { setView({ kind: "board", directionId: direction.id, projectId: pid }); setSelectedId(taskId); }}
            onNewProject={() => setProjModal({ direction, project: null })} onEditDirection={() => setDirModal({ open: true, direction })}
            onDirectionMenu={(e) => openMenu(direction, e)} onProjectMenu={openProjectMenu} onShare={() => shareDirection(direction)}
            onOpenMindmap={(id) => setView({ kind: "mindmap", id })} onMindmaps={() => setView({ kind: "mindmaps", directionId: direction.id })} />
        ) : view.kind === "shared" ? (
          <SharedPage store={store} onOpen={openShared} />
        ) : view.kind === "mindmaps" ? (
          <MindMapsPage store={store} filterDirection={view.directionId ?? null} onOpen={(id) => setView({ kind: "mindmap", id })} onOpenTask={(id) => { setView({ kind: "board", directionId: null }); setSelectedId(id); }} />
        ) : view.kind === "mindmap" ? (
          (() => {
            const m = store.mindmaps.find((x) => x.id === view.id);
            return m ? (
              <MindMapEditor key={m.id} store={store} map={m}
                onBack={() => setView(m.direction_id ? { kind: "direction", directionId: m.direction_id } : { kind: "mindmaps" })}
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
            <p>Направление — это область, которую вы ведёте: закуп, команда, техника. Внутри — проекты, а в них задачи.</p>
            <button className="btn primary" onClick={() => setDirModal({ open: true, direction: null })}>+ Первое направление</button>
          </div>
        ) : (
          <Board store={store} direction={direction} project={project} looseOnly={view.kind === "board" && view.projectId === "none"} selectedId={selectedId} onSelect={setSelectedId}
            onEditDirection={(d) => setDirModal({ open: true, direction: d })} onOpenDirection={(d) => setView({ kind: "direction", directionId: d.id })}
            onEditProject={(p) => setProjModal({ direction: store.directions.find((d) => d.id === p.direction_id)!, project: p })}
            onShare={() => (project ? shareProject(project) : direction && shareDirection(direction))}
            onOpenMindmap={(id) => setView({ kind: "mindmap", id })} onMindmaps={(dirId) => setView({ kind: "mindmaps", directionId: dirId })} />
        )}
      </main>

      {showPanel && selected && (
        <TaskPanel key={selected.id} store={store} task={selected} onClose={() => setSelectedId(null)} onDeleted={() => setSelectedId(null)}
          onOpenMindmap={(id) => { setSelectedId(null); setView({ kind: "mindmap", id }); }}
          onShare={() => setShare({ type: "task", id: selected.id, name: selected.title, color: selected.directions[0] ? dirColor(selected.directions[0]) : undefined })} />
      )}

      {profile && store.me && <ProfileModal store={store} onClose={() => setProfile(false)} />}

      {menu && (
        <DirectionMenu store={store} anchor={menu} onClose={() => setMenu(null)}
          onOpen={(d) => { setView({ kind: "direction", directionId: d.id }); setSelectedId(null); }}
          onBoard={(d) => { setView({ kind: "board", directionId: d.id }); setSelectedId(null); }}
          onNewProject={(d) => setProjModal({ direction: d, project: null })}
          onShare={shareDirection}
          onMindmaps={(d) => { setView({ kind: "mindmaps", directionId: d.id }); setSelectedId(null); }}
          onEdit={(d) => setDirModal({ open: true, direction: d })}
          onRename={(d) => setRenaming(d)}
          onDeleted={(d) => { if ((view.kind === "board" || view.kind === "direction") && view.directionId === d.id) setView({ kind: "board", directionId: null }); }} />
      )}
      {pmenu && (
        <ProjectMenu store={store} anchor={pmenu} onClose={() => setPmenu(null)}
          onOpen={(p) => { setView({ kind: "board", directionId: p.direction_id, projectId: p.id }); setSelectedId(null); }}
          onEdit={(p) => setProjModal({ direction: store.directions.find((d) => d.id === p.direction_id)!, project: p })}
          onRename={(p) => setPrenaming(p)} onShare={shareProject}
          onDeleted={(p) => { if (view.kind === "board" && view.projectId === p.id) setView({ kind: "direction", directionId: p.direction_id }); }} />
      )}
      {renaming && <RenameModal store={store} direction={renaming} onClose={() => setRenaming(null)} />}
      {prenaming && <RenameProjectModal store={store} project={prenaming} onClose={() => setPrenaming(null)} />}
      {projModal && (
        <ProjectModal store={store} direction={projModal.direction} project={projModal.project} onClose={() => setProjModal(null)}
          onSaved={(p) => { setProjModal(null); if (!projModal.project) { setView({ kind: "board", directionId: p.direction_id, projectId: p.id }); setSelectedId(null); } }} />
      )}
      {share && <ShareModal store={store} target={share} onClose={() => setShare(null)} />}

      {dirModal.open && (
        <DirectionModal
          store={store} direction={dirModal.direction}
          onClose={() => setDirModal({ open: false, direction: null })}
          onSaved={(d) => { setDirModal({ open: false, direction: null }); setView({ kind: "direction", directionId: d.id }); }}
          onDeleted={() => { setDirModal({ open: false, direction: null }); setView({ kind: "board", directionId: null }); }}
        />
      )}
    </div>
  );
}
