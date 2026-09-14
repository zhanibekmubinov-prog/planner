// v1.6: перетаскивание задач и проектов — общий код для сайдбара и карты проектов.
//
// Правила (решение владельца 2026-09-14):
//   задача → проект            — переносится в этот проект;
//   задача → направление       — выходит из проекта («Без проекта») и получает это направление;
//   задача → другая задача     — встаёт перед ней (а если та в другом контейнере — заодно туда переезжает);
//   проект → направление       — переезжает туда (через окно проекта: «перенести» или «скопировать»);
//   проект → другой проект     — встаёт перед ним внутри направления.
//
// Порядок хранится в поле sort_order (POST /projects/reorder, /tasks/reorder). Перенос задачи — обычный
// PUT /tasks/{id} всей карточкой с новым project_id (направление проекта бэкенд добавляет сам).
import { canEdit, Direction, errorText, Project, post, put, Task, TaskIn, toIn } from "./api";
import { Store } from "./store";

export const DRAG_TASK = "text/task-id";
export const DRAG_PROJECT = "text/project-id";

/** Число из dataTransfer (0, если этого типа в переносе нет). */
export const dragId = (e: React.DragEvent, type: string): number => Number(e.dataTransfer.getData(type)) || 0;
export const hasType = (e: React.DragEvent, type: string): boolean => e.dataTransfer.types.includes(type);

/** Переставить `moved` так, чтобы он оказался перед `before` (before = null — в конец). */
export function insertBefore(ids: number[], moved: number, before: number | null): number[] {
  const rest = ids.filter((x) => x !== moved);
  if (before === null || before === moved) return [...rest, moved];
  const at = rest.indexOf(before);
  if (at < 0) return [...rest, moved];
  return [...rest.slice(0, at), moved, ...rest.slice(at)];
}

/** Задачи контейнера в текущем порядке: проект (projectId) или «без проекта» внутри направления. */
export function siblingTasks(store: Store, t: Task): Task[] {
  if (t.project_id != null && store.projects.some((p) => p.id === t.project_id)) {
    return store.tasks.filter((x) => x.project_id === t.project_id);
  }
  const dirId = t.directions[0]?.id;
  return store.tasks.filter((x) => (x.project_id == null || !store.projects.some((p) => p.id === x.project_id))
    && (dirId ? x.directions.some((d) => d.id === dirId) : x.directions.length === 0));
}

const ordered = (xs: { id: number; sort_order?: number }[]) =>
  [...xs].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id).map((x) => x.id);

/** Перенести задачу в проект (projectId = null — «Без проекта»); directionId — куда положить, если проекта нет. */
export async function moveTaskToProject(store: Store, taskId: number, projectId: number | null, directionId?: number): Promise<boolean> {
  const t = store.tasks.find((x) => x.id === taskId);
  if (!t || !canEdit(t.access)) return false;
  const target = projectId ? store.projects.find((p) => p.id === projectId) : null;
  if (projectId && (!target || !canEdit(target.access))) return false;
  const dirIds = new Set(t.directions.map((d) => d.id));
  if (directionId) dirIds.add(directionId);
  const sameProject = (t.project_id ?? null) === projectId || (projectId === null && t.project_id != null && !store.projects.some((p) => p.id === t.project_id));
  const sameDirs = dirIds.size === t.directions.length;
  if (sameProject && sameDirs) return false;
  const body: TaskIn = { ...toIn(t, projectId), direction_ids: [...dirIds], updated_at: t.updated_at };
  store.patchTask({ ...t, project_id: projectId });   // оптимистично — строка сразу на новом месте
  try {
    store.patchTask(await put<Task>(`/tasks/${t.id}`, body));
    return true;
  } catch (e) {
    store.patchTask(t); store.setError(errorText(e)); void store.reloadTasks();
    return false;
  }
}

/** Новый порядок задач внутри контейнера. */
export async function reorderTasks(store: Store, ids: number[]): Promise<void> {
  ids.forEach((id, i) => { const t = store.tasks.find((x) => x.id === id); if (t) store.patchTask({ ...t, sort_order: i }); });
  try { store.setTasks(await post<Task[]>("/tasks/reorder", { ids })); }
  catch (e) { store.setError(errorText(e)); void store.reloadTasks(); }
}

/** Новый порядок проектов внутри направления. */
export async function reorderProjects(store: Store, ids: number[]): Promise<void> {
  ids.forEach((id, i) => { const p = store.projects.find((x) => x.id === id); if (p) store.patchProject({ ...p, sort_order: i }); });
  try { store.setProjects(await post<Project[]>("/projects/reorder", { ids })); }
  catch (e) { store.setError(errorText(e)); void store.reloadProjects(); }
}

/** Бросили задачу на другую задачу: встать перед ней (и переехать в её контейнер, если он другой). */
export async function dropTaskOnTask(store: Store, movedId: number, target: Task): Promise<void> {
  const moved = store.tasks.find((x) => x.id === movedId);
  if (!moved || moved.id === target.id || !canEdit(moved.access)) return;
  const targetProject = target.project_id != null && store.projects.some((p) => p.id === target.project_id) ? target.project_id : null;
  const movedProject = moved.project_id != null && store.projects.some((p) => p.id === moved.project_id) ? moved.project_id : null;
  if (targetProject !== movedProject && !(await moveTaskToProject(store, movedId, targetProject, target.directions[0]?.id))) return;
  const ids = ordered(siblingTasks(store, target).length ? siblingTasks(store, target) : [target]);
  await reorderTasks(store, insertBefore(ids.includes(movedId) ? ids : [...ids, movedId], movedId, target.id));
}

/** Бросили проект на другой проект того же направления: встать перед ним. */
export async function dropProjectOnProject(store: Store, movedId: number, target: Project): Promise<boolean> {
  const moved = store.projects.find((x) => x.id === movedId);
  if (!moved || moved.id === target.id || !canEdit(moved.access)) return false;
  if (moved.direction_id !== target.direction_id) return false;   // в другое направление — через окно проекта
  const ids = ordered(store.projects.filter((p) => p.direction_id === target.direction_id));
  await reorderProjects(store, insertBefore(ids, movedId, target.id));
  return true;
}

/** Можно ли класть задачи в этот контейнер. */
export const canDropTask = (store: Store, d: Direction | null, p: Project | null): boolean =>
  p ? canEdit(p.access) : !!d && canEdit(d.access) && d.access !== "via";
