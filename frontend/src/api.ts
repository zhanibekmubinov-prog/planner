const BASE = import.meta.env.VITE_API_URL as string;
const TOKEN = import.meta.env.VITE_API_TOKEN as string;

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-API-Token": TOKEN, ...(init.headers || {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? (undefined as T) : res.json();
}

export type Direction = { id: number; name: string; description?: string; goal?: string; color?: string; status: string };
export type Tool = { id: number; name: string; type: string; url?: string; source_ref?: Record<string, unknown>; note?: string };
export type Task = {
  id: number; title: string; description?: string; status: "backlog" | "in_progress" | "waiting" | "done";
  priority: number; deadline?: string; next_check_at?: string; directions: Direction[]; tools: Tool[];
};
