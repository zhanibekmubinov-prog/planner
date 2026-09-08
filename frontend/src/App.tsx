import { useEffect, useMemo, useRef, useState } from "react";
import { LoginScreen, pickUpSession, ProfileModal } from "./Account";
import InboxPage from "./Inbox";
import { errorText, onUnauthorized, put } from "./api";
import { Direction, dirColor, Project, projColor, SharedWithMe } from "./api";
import ArchivePage from "./Archive";
import Board from "./Board";
import DirectionModal from "./DirectionModal";
import DirectionMenu, { anchorFromEvent, MenuAnchor, RenameModal } from "./DirectionMenu";
import DirectionPage from "./DirectionPage";
import { PeoplePage, ToolsPage } from "./Registry";
import MindMapEditor from "./MindMapEditor";
import MindMapsPage from "./MindMaps";
import Overview from "./Overview";
import ProjectMenu, { ProjectAnchor, projectAnchorFromEvent, projectBody, ProjectModal, RenameProjectModal } from "./ProjectMenu";
import ShareModal, { ShareTarget } from "./ShareModal";
import SharedPage from "./SharedPage";
import Sidebar, { SidebarProps, View } from "./Sidebar";
import MobileNav from "./MobileNav";
import { useIsMobile } from "./mobile";
import { useStore } from "./store";
import TaskPanel from "./TaskPanel";
import { useToast } from "./toast";
import TrashPage from "./Trash";
import GuestsPage from "./Guests";
import { applyUpdate, updatePending, useUpdateAvailable } from "./update";
import { PullIndicator, usePullToRefresh } from "./PullToRefresh";
import { hasDirtyForms } from "./layers";
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
  const toast = useToast();
  const updateReady = useUpdateAvailable();
  const mobile = useIsMobile();
  // Телефон: «потянуть сверху вниз» перечитывает данные на месте; если уже скачана новая версия сайта — применяет её (В3: не поверх несохранённого ввода)
  const mainRef = useRef<HTMLElement>(null);
  const pull = usePullToRefresh(mainRef, async () => {
    if (updatePending() && !hasDirtyForms()) { applyUpdate(); return; }
    await store.refresh();
  }, mobile);
  const openMenu = (d: Direction, e: React.MouseEvent) => setMenu(anchorFromEvent(d, e));
  const openTaskAnywhere = (id: number) => { setView({ kind: "board", directionId: null }); setSelectedId(id); };
  // В4: вернуть проект из архива прямо с карты проектов
  const restoreProject = async (p: Project) => {
    try { await put<Project>(`/projects/${p.id}`, { ...projectBody(p), status: "active" }); await store.reloadProjects(); }
    catch (e) { store.setError(errorText(e)); }
  };
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

  // Ссылки из уведомлений: /?task=ID — карточка задачи; /?project=ID — доска проекта; /?direction=ID — карта проектов
  useEffect(() => {
    if (store.loading) return;
    const q = new URLSearchParams(window.location.search);
    const taskId = Number(q.get("task")), projectId = Number(q.get("project")), directionId = Number(q.get("direction"));
    if (taskId && store.tasks.some((t) => t.id === taskId)) { setView({ kind: "board", directionId: null }); setSelectedId(taskId); }
    else if (taskId && store.inbox.some((t) => t.id === taskId)) { setView({ kind: "inbox" }); }
    else if (taskId) toast(`Задача #${taskId} недоступна: удалена, в корзине или доступ к ней закрыт.`);   // Н3
    else if (projectId) { const p = store.projects.find((x) => x.id === projectId); if (p) setView({ kind: "board", directionId: p.direction_id, projectId: p.id }); }
    else if (directionId && store.directions.some((d) => d.id === directionId)) setView({ kind: "direction", directionId });
    if (taskId || projectId || directionId) window.history.replaceState(null, "", window.location.pathname);
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

  const navProps: SidebarProps = {
    directions: store.directions, projects: store.projects, tasks: store.tasks, view, mindmapCount: store.mindmaps.length,
    inboxCount: store.inbox.filter((t) => t.status !== "done").length, sharedCount: sharedOpen, me: store.me, onProfile: () => setProfile(true),
    trashCount: store.trash ? store.trash.directions.length + store.trash.projects.length + store.trash.tasks.length : 0,
    onView: (v) => { setView(v); if (v.kind !== "board") setSelectedId(null); },
    onNewDirection: () => setDirModal({ open: true, direction: null }), onNewProject: (d) => setProjModal({ direction: d, project: null }),
    onDirectionMenu: openMenu, onProjectMenu: openProjectMenu,
  };

  return (
    <div className={`shell ${mobile ? "mobile" : ""}`}>
      {/* Телефон: нижняя панель вкладок вместо левой панели (v0.11) */}
      {mobile ? <MobileNav {...navProps} /> : <Sidebar {...navProps} />}

      <main className="main" ref={mainRef}>
        {mobile && <PullIndicator state={pull} />}
        {updateReady && (
          <div className="update-bar" role="status">
            <span>Доступна новая версия Planner.</span>
            <button className="btn sm primary" onClick={applyUpdate}>Обновить</button>
          </div>
        )}
        {store.error && (
          <div className="error-bar" role="alert">
            <span>{store.error}</span>
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
            onOrphans={() => setView({ kind: "board", directionId: null, orphans: true })}
          />
        ) : view.kind === "direction" && direction ? (
          <DirectionPage key={direction.id} store={store} direction={direction}
            onOpenBoard={(pid) => setView({ kind: "board", directionId: direction.id, projectId: pid })}
            onOpenTask={(pid, taskId) => { setView({ kind: "board", directionId: direction.id, projectId: pid }); setSelectedId(taskId); }}
            onNewProject={() => setProjModal({ direction, project: null })} onEditDirection={() => setDirModal({ open: true, direction })}
            onDirectionMenu={(e) => openMenu(direction, e)} onProjectMenu={openProjectMenu} onShare={() => shareDirection(direction)}
            onOpenMindmap={(id) => setView({ kind: "mindmap", id })} onMindmaps={() => setView({ kind: "mindmaps", directionId: direction.id })}
            onRestoreProject={restoreProject} />
        ) : view.kind === "archive" ? (
          <ArchivePage store={store} onOpenDirection={(id) => setView({ kind: "direction", directionId: id })} onOpenProject={(p) => setView({ kind: "board", directionId: p.direction_id, projectId: p.id })} />
        ) : view.kind === "guests" ? (
          <GuestsPage store={store} />
        ) : view.kind === "trash" ? (
          <TrashPage store={store} />
        ) : view.kind === "shared" ? (
          <SharedPage store={store} onOpen={openShared} />
        ) : view.kind === "mindmaps" ? (
          <MindMapsPage store={store} filterDirection={view.directionId ?? null} onOpen={(id) => setView({ kind: "mindmap", id })} onOpenTask={openTaskAnywhere} />
        ) : view.kind === "mindmap" ? (
          (() => {
            const m = store.mindmaps.find((x) => x.id === view.id);
            return m ? (
              <MindMapEditor key={m.id} store={store} map={m}
                onBack={() => setView(m.direction_id ? { kind: "direction", directionId: m.direction_id } : { kind: "mindmaps" })}
                onDeleted={() => setView({ kind: "mindmaps" })}
                onOpenTask={openTaskAnywhere} />
            ) : <div className="state"><h3>Майндмап не найден</h3><button className="btn" onClick={() => setView({ kind: "mindmaps" })}>К списку</button></div>;
          })()
        ) : view.kind === "inbox" ? (
          <InboxPage store={store} />
        ) : view.kind === "people" ? (
          <PeoplePage store={store} onOpenTask={openTaskAnywhere} />
        ) : view.kind === "tools" ? (
          <ToolsPage store={store} />
        ) : store.directions.length === 0 && store.tasks.length === 0 ? (
          <div className="state">
            <h3>Начнём с направления</h3>
            <p>Направление — это область, которую вы ведёте: закуп, команда, техника. Внутри — проекты, а в них задачи.</p>
            <button className="btn primary" onClick={() => setDirModal({ open: true, direction: null })}>+ Первое направление</button>
          </div>
        ) : (
          <Board store={store} direction={direction} project={project} looseOnly={view.kind === "board" && view.projectId === "none"} orphans={view.kind === "board" && !!view.orphans} selectedId={selectedId} onSelect={setSelectedId}
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
