// Единое хранилище данных: загружает справочники и задачи, отдаёт функции перезагрузки.
import { useCallback, useEffect, useState } from "react";
import { api, Direction, MindMap, Person, Task, Tool } from "./api";

export type Store = {
  directions: Direction[]; tasks: Task[]; people: Person[]; tools: Tool[]; mindmaps: MindMap[];
  loading: boolean; error: string | null;
  reload: () => Promise<void>;
  reloadTasks: () => Promise<void>;
  reloadDirections: () => Promise<void>;
  reloadPeople: () => Promise<void>;
  reloadTools: () => Promise<void>;
  reloadMindmaps: () => Promise<void>;
  patchMindmap: (m: MindMap) => void;
  patchTask: (t: Task) => void;
  setError: (e: string | null) => void;
};

export function useStore(): Store {
  const [directions, setDirections] = useState<Direction[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [mindmaps, setMindmaps] = useState<MindMap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const guard = useCallback(async (fn: () => Promise<void>) => {
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  const reloadTasks = useCallback(() => guard(async () => setTasks(await api<Task[]>("/tasks"))), [guard]);
  const reloadDirections = useCallback(() => guard(async () => setDirections(await api<Direction[]>("/directions"))), [guard]);
  const reloadPeople = useCallback(() => guard(async () => setPeople(await api<Person[]>("/people"))), [guard]);
  const reloadTools = useCallback(() => guard(async () => setTools(await api<Tool[]>("/tools"))), [guard]);
  const reloadMindmaps = useCallback(() => guard(async () => setMindmaps(await api<MindMap[]>("/mindmaps"))), [guard]);

  const reload = useCallback(async () => {
    setLoading(true);
    await Promise.all([reloadDirections(), reloadTasks(), reloadPeople(), reloadTools(), reloadMindmaps()]);
    setLoading(false);
  }, [reloadDirections, reloadTasks, reloadPeople, reloadTools, reloadMindmaps]);

  useEffect(() => { void reload(); }, [reload]);

  const patchTask = useCallback((t: Task) => setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x))), []);
  const patchMindmap = useCallback((m: MindMap) => setMindmaps((prev) => prev.map((x) => (x.id === m.id ? m : x))), []);

  return { directions, tasks, people, tools, mindmaps, loading, error, reload, reloadTasks, reloadDirections, reloadPeople, reloadTools, reloadMindmaps, patchTask, patchMindmap, setError };
}
