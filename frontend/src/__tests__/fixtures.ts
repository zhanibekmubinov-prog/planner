// Фабрики тестовых данных и фейковый Store (все reload/patch — no-op vi.fn()).
import { vi } from "vitest";
import type { Direction, Project, Task } from "../api";
import type { Store } from "../store";

const noop = () => vi.fn(async () => {});

export function makeDirection(over: Partial<Direction> = {}): Direction {
  return { id: 1, name: "Закуп", status: "active", created_at: "2026-01-01T00:00:00Z", access: "owner", color: null, goal: null, description: null, ...over };
}

export function makeProject(over: Partial<Project> = {}): Project {
  return { id: 10, direction_id: 1, name: "Договор основной", status: "active", created_at: "2026-01-01T00:00:00Z", access: "owner", color: null, goal: null, description: null, ...over };
}

export function makeTask(over: Partial<Task> = {}): Task {
  return {
    id: 100, title: "Согласовать КП", description: null, status: "backlog", priority: 3, deadline: null, next_check_at: null,
    created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:00:00Z", directions: [makeDirection()], tools: [], owner: null,
    project_id: null, access: "owner", checklist: [], ...over,
  };
}

export function makeStore(over: Partial<Store> = {}): Store {
  return {
    me: { id: 1, email: "me@example.com", name: "Я", is_admin: false, digest_enabled: false },
    directions: [], projects: [], tasks: [], inbox: [], people: [], tools: [], mindmaps: [], shared: [],
    loading: false, error: null,
    reload: noop(), reloadTasks: noop(), reloadDirections: noop(), reloadProjects: noop(), reloadShared: noop(),
    reloadPeople: noop(), reloadTools: noop(), reloadMindmaps: noop(), reloadMe: noop(),
    setMe: vi.fn(), patchMindmap: vi.fn(), patchTask: vi.fn(), setError: vi.fn(),
    ...over,
  };
}
