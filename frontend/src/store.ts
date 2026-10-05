// Единое хранилище данных: загружает справочники и задачи, отдаёт функции перезагрузки.
import { useCallback, useEffect, useState } from "react";
import { api, Direction, errorText, MindMap, Person, Project, SharedWithMe, Task, Tool, TrashOut, User } from "./api";
import { filterForSpace, Space, useSpace } from "./spaces";

export type Store = {
  me: User | null; directions: Direction[]; projects: Project[]; tasks: Task[]; inbox: Task[]; people: Person[]; tools: Tool[]; mindmaps: MindMap[];
  shared: SharedWithMe[]; trash: TrashOut | null;
  // v1.7: слой. directions/projects/tasks/mindmaps/trash выше — уже отфильтрованы под него;
  // inbox («Мне поручено») и shared («Общие») не фильтруются: они всегда рабочие.
  space: Space; setSpace: (s: Space) => void;
  spaceCounts: { personal: number; org: number };   // сколько живых направлений в каждом слое — цифра на вкладке
  loading: boolean; error: string | null;
  reload: () => Promise<void>;
  refresh: () => Promise<void>;   // то же, что reload, но без экрана «загрузка…» — данные меняются на месте
  reloadTasks: () => Promise<void>;
  reloadDirections: () => Promise<void>;
  reloadProjects: () => Promise<void>;
  reloadShared: () => Promise<void>;
  reloadPeople: () => Promise<void>;
  reloadTools: () => Promise<void>;
  reloadMindmaps: () => Promise<void>;
  reloadTrash: () => Promise<void>;
  reloadMe: () => Promise<void>;
  setMe: (u: User) => void;
  patchMindmap: (m: MindMap) => void;
  patchTask: (t: Task) => void;
  patchProject: (p: Project) => void;      // v1.6: оптимистичная правка проекта (порядок при перетаскивании)
  setTasks: (ts: Task[]) => void;          // v1.6: принять список целиком (ответ /tasks/reorder)
  setProjects: (ps: Project[]) => void;    // v1.6: то же для проектов
  setError: (e: string | null) => void;
};

export function useStore(): Store {
  const [space, setSpace] = useSpace();
  const [directions, setDirections] = useState<Direction[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [shared, setShared] = useState<SharedWithMe[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [mindmaps, setMindmaps] = useState<MindMap[]>([]);
  const [trash, setTrash] = useState<TrashOut | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [allTasks, setAllTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ошибка показывается понятно (4xx — отказ сервера, иначе — связь) и гаснет после следующей удачной загрузки (Н2)
  const guard = useCallback(async (fn: () => Promise<void>) => {
    try { await fn(); setError(null); } catch (e) { setError(errorText(e)); }
  }, []);

  const reloadTasks = useCallback(() => guard(async () => setAllTasks(await api<Task[]>("/tasks"))), [guard]);
  const reloadMe = useCallback(() => guard(async () => setMe(await api<User>("/auth/me"))), [guard]);
  const reloadDirections = useCallback(() => guard(async () => setDirections(await api<Direction[]>("/directions"))), [guard]);
  const reloadProjects = useCallback(() => guard(async () => setProjects(await api<Project[]>("/projects"))), [guard]);
  const reloadShared = useCallback(() => guard(async () => setShared(await api<SharedWithMe[]>("/shares/with-me"))), [guard]);
  const reloadPeople = useCallback(() => guard(async () => setPeople(await api<Person[]>("/people"))), [guard]);
  const reloadTools = useCallback(() => guard(async () => setTools(await api<Tool[]>("/tools"))), [guard]);
  const reloadMindmaps = useCallback(() => guard(async () => setMindmaps(await api<MindMap[]>("/mindmaps"))), [guard]);
  // Корзина — вспомогательный раздел: если бэкенд её ещё не отдаёт, молчим, а не красим плашку
  const reloadTrash = useCallback(async () => { try { setTrash(await api<TrashOut>("/trash")); } catch { setTrash(null); } }, []);

  const refresh = useCallback(async () => {
    await Promise.all([reloadMe(), reloadDirections(), reloadProjects(), reloadTasks(), reloadPeople(), reloadTools(), reloadMindmaps(), reloadShared(), reloadTrash()]);
  }, [reloadMe, reloadDirections, reloadProjects, reloadTasks, reloadPeople, reloadTools, reloadMindmaps, reloadShared, reloadTrash]);
  const reload = useCallback(async () => {
    setLoading(true);
    await refresh();
    setLoading(false);
  }, [refresh]);

  useEffect(() => { void reload(); }, [reload]);

  const patchTask = useCallback((t: Task) => setAllTasks((prev) => prev.map((x) => (x.id === t.id ? t : x))), []);
  const patchProject = useCallback((p: Project) => setProjects((prev) => prev.map((x) => (x.id === p.id ? p : x))), []);
  // Ответ /reorder — это полный видимый список: кладём его как есть, чтобы порядок совпал с серверным
  const setTasksList = useCallback((ts: Task[]) => setAllTasks(ts), []);
  const setProjectsList = useCallback((ps: Project[]) => setProjects(ps), []);
  // На доске — мои задачи и те, что мне открыли (общие); порученные мне другими — во «входящих» (могут быть и там, и там)
  // порученная мне задача попадает и на доску, если она лежит в открытом мне направлении/проекте
  const sharedDirs = new Set(directions.filter((d) => d.access === "edit" || d.access === "view").map((d) => d.id));
  const sharedProjects = new Set(projects.filter((p) => p.access === "edit" || p.access === "view").map((p) => p.id));
  const tasks = allTasks.filter((t) => !me || !t.owner || t.owner.id === me.id || t.access === "edit" || t.access === "view"
    || (t.access === "assignee" && (t.directions.some((d) => sharedDirs.has(d.id)) || (t.project_id != null && sharedProjects.has(t.project_id)))));
  const inbox = allTasks.filter((t) => me && t.owner && t.owner.id !== me.id && (t.assigned_to_me || t.access === "assignee"));
  const patchMindmap = useCallback((m: MindMap) => setMindmaps((prev) => prev.map((x) => (x.id === m.id ? m : x))), []);

  // v1.7: единственное место, где применяется слой — дальше все экраны получают уже готовые списки
  const inSpace = filterForSpace(space, { directions, projects, tasks, mindmaps, trash });
  const live = directions.filter((d) => d.status !== "archived");
  const spaceCounts = { personal: live.filter((d) => d.space !== "org").length, org: live.filter((d) => d.space === "org").length };

  return { me, directions: inSpace.directions, projects: inSpace.projects, tasks: inSpace.tasks, inbox, people, tools,
    mindmaps: inSpace.mindmaps, shared, trash: inSpace.trash, space, setSpace, spaceCounts, loading, error, reload, refresh, reloadTasks, reloadDirections, reloadProjects, reloadShared, reloadPeople, reloadTools, reloadMindmaps, reloadTrash, reloadMe, setMe, patchTask, patchProject, setTasks: setTasksList, setProjects: setProjectsList, patchMindmap, setError };
}
