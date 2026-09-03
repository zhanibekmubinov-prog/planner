// Единое хранилище данных: загружает справочники и задачи, отдаёт функции перезагрузки.
import { useCallback, useEffect, useState } from "react";
import { api, Direction, MindMap, Person, Task, Tool, User } from "./api";

export type Store = {
  me: User | null; directions: Direction[]; tasks: Task[]; inbox: Task[]; people: Person[]; tools: Tool[]; mindmaps: MindMap[];
  loading: boolean; error: string | null;
  reload: () => Promise<void>;
  reloadTasks: () => Promise<void>;
  reloadDirections: () => Promise<void>;
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
  const reloadPeople = useCallback(() => guard(async () => setPeople(await api<Person[]>("/people"))), [guard]);
  const reloadTools = useCallback(() => guard(async () => setTools(await api<Tool[]>("/tools"))), [guard]);
  const reloadMindmaps = useCallback(() => guard(async () => setMindmaps(await api<MindMap[]>("/mindmaps"))), [guard]);

  const reload = useCallback(async () => {
    setLoading(true);
    await Promise.all([reloadMe(), reloadDirections(), reloadTasks(), reloadPeople(), reloadTools(), reloadMindmaps()]);
    setLoading(false);
  }, [reloadMe, reloadDirections, reloadTasks, reloadPeople, reloadTools, reloadMindmaps]);

  useEffect(() => { void reload(); }, [reload]);

  const patchTask = useCallback((t: Task) => setAllTasks((prev) => prev.map((x) => (x.id === t.id ? t : x))), []);
  // Мои задачи — на доске; порученные мне другими — во «входящих»
  const tasks = allTasks.filter((t) => !me || !t.owner || t.owner.id === me.id);
  const inbox = allTasks.filter((t) => me && t.owner && t.owner.id !== me.id);
  const patchMindmap = useCallback((m: MindMap) => setMindmaps((prev) => prev.map((x) => (x.id === m.id ? m : x))), []);

  return { me, directions, tasks, inbox, people, tools, mindmaps, loading, error, reload, reloadTasks, reloadDirections, reloadPeople, reloadTools, reloadMindmaps, reloadMe, setMe, patchTask, patchMindmap, setError };
}
