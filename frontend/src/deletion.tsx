// Единый сценарий удаления (владелец, решение 5): цифры из /impact → confirm с заголовком по типу и вводом названия
// → DELETE (soft) → store.reload() → тост «… удалено · Отменить» → POST …/restore.
import { api, del, Direction, errorText, Impact, nProjects, nTasks, plural, post, Project, Task } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";
import { useToast } from "./toast";

async function impactOf(path: string, fallback: Impact): Promise<Impact> {
  try { return await api<Impact>(path); } catch { return fallback; }   // бэкенд без /impact — считаем по стору
}
const sharesNote = (n: number) => (n > 0 ? ` Доступ ${n === 1 ? "коллеги" : `${n} коллег`} к нему закроется.` : "");

export function useDeletion(store: Store) {
  const confirm = useConfirm();
  const toast = useToast();

  const undo = (label: string, restorePath: string) => toast(label, {
    action: "Отменить",
    onAction: async () => { try { await post(restorePath, {}); await store.reload(); } catch (e) { store.setError(errorText(e)); } },
  });

  /** Удалить направление. Возвращает true, если удалено. */
  async function deleteDirection(d: Direction): Promise<boolean> {
    const mine = store.tasks.filter((t) => t.directions.some((x) => x.id === d.id));
    const impact = await impactOf(`/directions/${d.id}/impact`, {
      projects: store.projects.filter((p) => p.direction_id === d.id).length, tasks: mine.length, open_tasks: mine.filter((t) => t.status !== "done").length, shares: 0,
    });
    // v1.6: задачи уходят в корзину вместе с направлением; остаются только те, что числятся ещё в одном живом направлении
    const what = impact.tasks > 0
      ? `Вместе с ним в корзину уйдут ${nProjects(impact.projects)} и ${impact.tasks === 1 ? "задача" : nTasks(impact.tasks)}. Задачи, которые числятся ещё в одном направлении, останутся там.`
      : impact.projects > 0 ? `Вместе с ним в корзину уйдут ${nProjects(impact.projects)}. Задач в нём нет.` : "Задач и проектов в нём нет.";
    const ok = await confirm(`Направление «${d.name}» отправится в корзину. ${what}${sharesNote(impact.shares)}`, {
      title: "Удалить направление?", danger: true, okLabel: "Удалить направление",
      typeToConfirm: impact.tasks > 0 ? d.name : undefined,
      details: <span className="hint">Вернуть можно из корзины в течение 30 дней.</span>,
    });
    if (!ok) return false;
    try { await del(`/directions/${d.id}`); await store.reload(); undo(`Направление «${d.name}» удалено`, `/directions/${d.id}/restore`); return true; }
    catch (e) { store.setError(errorText(e)); return false; }
  }

  async function deleteProject(p: Project): Promise<boolean> {
    const mine = store.tasks.filter((t) => t.project_id === p.id);
    const impact = await impactOf(`/projects/${p.id}/impact`, { projects: 0, tasks: mine.length, open_tasks: mine.filter((t) => t.status !== "done").length, shares: 0 });
    // v1.6: задачи проекта уходят в корзину вместе с ним и возвращаются вместе с ним же
    const what = impact.tasks > 0 ? `${impact.tasks === 1 ? "Его задача уйдёт" : `Его ${nTasks(impact.tasks)} уйдут`} в корзину вместе с ним — и вернутся вместе с ним.` : "Задач в нём нет.";
    const ok = await confirm(`Проект «${p.name}» отправится в корзину. ${what}${sharesNote(impact.shares)}`, {
      title: "Удалить проект?", danger: true, okLabel: "Удалить проект",
      typeToConfirm: impact.tasks > 0 ? p.name : undefined,
      details: <span className="hint">Вернуть можно из корзины в течение 30 дней.</span>,
    });
    if (!ok) return false;
    try { await del(`/projects/${p.id}`); await store.reload(); undo(`Проект «${p.name}» удалён`, `/projects/${p.id}/restore`); return true; }
    catch (e) { store.setError(errorText(e)); return false; }
  }

  async function deleteTask(t: Task): Promise<boolean> {
    const map = store.mindmaps.find((m) => m.task_id === t.id);
    const nodes = map ? countNodes(map.data) - 1 : 0;
    const ok = await confirm(
      `Задача «${t.title}» отправится в корзину вместе с поручениями и напоминаниями${map ? ` и майндмапом задачи (${nodes} ${plural(nodes, "узел", "узла", "узлов")})` : ""}.`,
      { title: "Удалить задачу?", danger: true, okLabel: "Удалить задачу", details: <span className="hint">Вернуть можно из корзины в течение 30 дней.</span> },
    );
    if (!ok) return false;
    try { await del(`/tasks/${t.id}`); await store.reload(); undo(`Задача «${t.title}» удалена`, `/tasks/${t.id}/restore`); return true; }
    catch (e) { store.setError(errorText(e)); return false; }
  }

  return { deleteDirection, deleteProject, deleteTask };
}

function countNodes(n: { children?: { children?: unknown[] }[] } | null | undefined): number {
  return ((n?.children ?? []) as { children?: unknown[] }[]).reduce((s, c) => s + countNodes(c as never), 1);
}
