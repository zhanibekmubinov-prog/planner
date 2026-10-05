// Слои (v1.7): «Личное» и «Организация». Решения владельца 2026-10-05.
//
// Слой живёт на направлении; проекты, задачи и майндмапы наследуют слой своего направления.
// Задача без направлений несёт слой сама (поле space). Задача, лежащая и в личном, и в рабочем
// направлении, видна в обоих слоях — задачи кросс-направленческие, и прятать её было бы ложью.
//
// Фильтрация идёт на фронте, по уже загруженным данным (store.ts): переключение слоя не стоит
// ни одного запроса. Это важно — сервисы в sfo, владелец в Атырау, каждый запрос ~300 мс.
//
// Не фильтруются «Мне поручено» и «Общие»: они по смыслу всегда рабочие и видны в обоих слоях.
import { useCallback, useEffect, useState } from "react";
import type { Direction, MindMap, Project, Task, TrashOut } from "./api";

export type Space = "personal" | "org";
export const SPACE_LABEL: Record<Space, string> = { personal: "Личное", org: "Организация" };

const KEY = "planner.space";
const EVENT = "planner:space";

export function readSpace(): Space {
  try { return localStorage.getItem(KEY) === "org" ? "org" : "personal"; } catch { return "personal"; }
}

/** Текущий слой + переключение. Событие — чтобы все окна приложения переключились разом. */
export function useSpace(): [Space, (s: Space) => void] {
  const [space, set] = useState<Space>(readSpace);
  useEffect(() => {
    const onChange = () => set(readSpace());
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onChange);   // вторая вкладка браузера
    return () => { window.removeEventListener(EVENT, onChange); window.removeEventListener("storage", onChange); };
  }, []);
  const change = useCallback((s: Space) => {
    try { localStorage.setItem(KEY, s); } catch { /* приватный режим */ }
    set(s);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [space, change];
}

export const spaceOf = (d: Direction): Space => (d.space === "org" ? "org" : "personal");

/** Слой задачи: по живым направлениям; без направлений — собственный слой задачи. */
export function spaceOfTask(t: Task): Space[] {
  const dirs = t.directions || [];
  if (!dirs.length) return [t.space === "org" ? "org" : "personal"];
  const out = new Set<Space>(dirs.map(spaceOf));
  return [...out];
}

export const dirInSpace = (d: Direction, space: Space): boolean => spaceOf(d) === space;
export const taskInSpace = (t: Task, space: Space): boolean => spaceOfTask(t).includes(space);

/** Отфильтровать весь набор данных под слой. Проекты и майндмапы идут за своим направлением. */
export function filterForSpace(
  space: Space,
  data: { directions: Direction[]; projects: Project[]; tasks: Task[]; mindmaps: MindMap[]; trash: TrashOut | null },
) {
  const directions = data.directions.filter((d) => dirInSpace(d, space));
  const ids = new Set(directions.map((d) => d.id));
  // направления корзины тоже раскладываем по слоям — своя корзина у каждого слоя
  const trashDirIds = new Set((data.trash?.directions || []).filter((d) => dirInSpace(d, space)).map((d) => d.id));
  const known = new Set([...ids, ...trashDirIds]);
  const inSpaceProject = (p: Project) => known.has(p.direction_id);
  return {
    directions,
    projects: data.projects.filter(inSpaceProject),
    tasks: data.tasks.filter((t) => taskInSpace(t, space)),
    mindmaps: data.mindmaps.filter((m) => m.direction_id == null || known.has(m.direction_id)),
    trash: data.trash
      ? {
          directions: data.trash.directions.filter((d) => dirInSpace(d, space)),
          projects: data.trash.projects.filter(inSpaceProject),
          tasks: data.trash.tasks.filter((t) => taskInSpace(t, space)),
        }
      : null,
  };
}
