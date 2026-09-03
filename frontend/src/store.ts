// Единое хранилище данных: загружает справочники и задачи, отдаёт функции перезагрузки.
import { useCallback, useEffect, useState } from "react";
import { api, Direction, MindMap, Person, Project, SharedWithMe, Task, Tool, User } from "./api";

export type Store = {
  me: User | null; directions: Direction[]; projects: Project[]; tasks: Task[]; inbox: Task[]; people: Person[]; tools: Tool[]; mindmaps: MindMap[];
  shared: SharedWithMe[];
  loading: boolean; error: string | null;
  reload: () => Promise<void>;
  reloadTasks: () => Promise<void>;
  reloadDirections: () => Promise<void>;
  reloadProjects: () => Promise<void>;
  reloadShared: () => Promise<void>;
  reloadPeople: () => Promise<void>;
  reloadTools: () => Promise<void>;
  reloadMindmaps: () => Promise<void>;
  reloadMe: () => Promise<void>;
  setMe: (u: User) => void;
  patchMindmap: (m: MindMap) => void;
  patchTask: (t: Task) => void;
  setError: (e: string | null) => void;
};

export function useStore(): Store {
  const [directions, setDirections] = useState<Direction[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [shared, setShared] = useState<SharedWithMe[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [mindmaps, setMindmaps] = useState<MindMap[]>([]);
  const [me, setMe] = useState<User | null>(null);
  const [allTasks, setAllTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const guard = useCallback(async (fn: () => Promise<void>) => {
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  const reloadTasks = useCallback(() => guard(async () => setAllTasks(await api<Task[]>("/tasks"))), [guard]);
  const reloadMe = useCallback(() => guard(async () => setMe(await api<User>("/auth/me"))), [guard]);
  const reloadDirections = useCallback(() => guard(async () => setDirections(await api<Direction[]>("/directions"))), [guard]);
  const reloadProjects = useCallback(() => guard(async () => setProjects(await api<Project[]>("/projects"))), [guard]);
  const reloadShared = useCallback(() => guard(async () => setShared(await api<SharedWithMe[]>("/shares/with-me"))), [guard]);
  const reloadPeople = useCallback(() => guard(async () => setPeople(await api<Person[]>("/people"))), [guard]);
  const reloadTools = useCallback(() => guard(async () => setTools(await api<Tool[]>("/tools"))), [guard]);
  const reloadMindmaps = useCallback(() => guard(async () => setMindmaps(await api<MindMap[]>("/mindmaps"))), [guard]);

  const reload = useCallback(async () => {
    setLoading(true);
    await Promise.all([reloadMe(), reloadDirections(), reloadProjects(), reloadTasks(), reloadPeople(), reloadTools(), reloadMindmaps(), reloadShared()]);
    setLoading(false);
  }, [reloadMe, reloadDirections, reloadProjects, reloadTasks, reloadPeople, reloadTools, reloadMindmaps, reloadShared]);

  useEffect(() => { void reload(); }, [reload]);

  const patchTask = useCallback((t: Task) => setAllTasks((prev) => prev.map((x) => (x.id === t.id ? t : x))), []);
  // На доске — мои задачи и те, что мне открыли (общие); порученные мне другими — во «входящих» (могут быть и там, и там)
  // порученная мне задача попадает и на доску, если она лежит в открытом мне направлении/проекте
  const sharedDirs = new Set(directions.filter((d) => d.access === "edit" || d.access === "view").map((d) => d.id));
  const sharedProjects = new Set(projects.filter((p) => p.access === "edit" || p.access === "view").map((p) => p.id));
  const tasks = allTasks.filter((t) => !me || !t.owner || t.owner.id === me.id || t.access === "edit" || t.access === "view"
    || (t.access === "assignee" && (t.directions.some((d) => sharedDirs.has(d.id)) || (t.project_id != null && sharedProjects.has(t.project_id)))));
  const inbox = allTasks.filter((t) => me && t.owner && t.owner.id !== me.id && (t.assigned_to_me || t.access === "assignee"));
  const patchMindmap = useCallback((m: MindMap) => setMindmaps((prev) => prev.map((x) => (x.id === m.id ? m : x))), []);

  return { me, directions, projects, tasks, inbox, people, tools, mindmaps, shared, loading, error, reload, reloadTasks, reloadDirections, reloadProjects, reloadShared, reloadPeople, reloadTools, reloadMindmaps, reloadMe, setMe, patchTask, patchMindmap, setError };
}
