// Слой доступа к API. Все запросы идут через api<T>(); токен и адрес — из переменных сборки.
// VITE_API_URL может быть задан и как "https://host", и как "https://host/api" — приводим к виду без /api.
const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "").replace(/\/api$/, "");
const TOKEN = (import.meta.env.VITE_API_TOKEN as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// ---- Сессия пользователя (вход через Microsoft) ----
const SESSION_KEY = "planner.session";
export const getSession = (): string | null => { try { return localStorage.getItem(SESSION_KEY); } catch { return null; } };
export const setSession = (t: string | null) => { try { t ? localStorage.setItem(SESSION_KEY, t) : localStorage.removeItem(SESSION_KEY); } catch { /* приватный режим */ } };
export const API_BASE = BASE;
const listeners = new Set<() => void>();
export const onUnauthorized = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

function authHeaders(): Record<string, string> {
  const s = getSession();
  if (s) return { Authorization: `Bearer ${s}` };
  return TOKEN ? { "X-API-Token": TOKEN } : {};
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init.headers || {}) },
  });
  if (res.status === 401) { setSession(null); listeners.forEach((f) => f()); }
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${await res.text()}`);
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown) => JSON.stringify(body);
export const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", body: json(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: json(body) });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

// ---- Типы (зеркало backend/app/schemas.py) ----
export type DirectionStatus = "active" | "paused" | "archived";
export type TaskStatus = "backlog" | "in_progress" | "waiting" | "done";
export type DelegationStatus = "open" | "done";
export type ToolType = "google_sheet" | "excel_sharepoint" | "telegram_bot" | "notion" | "other";
export type Channel = "telegram" | "email" | "outlook_calendar";

// Уровень доступа к сущности (см. backend/app/scope.py): owner — моё; edit/view — открыли мне; via — контейнер виден
// только из-за доступного содержимого; assignee — задача поручена мне.
export type Access = "owner" | "edit" | "view" | "via" | "assignee";
export const canEdit = (a?: Access | null): boolean => !a || a === "owner" || a === "edit";
export const isShared = (a?: Access | null): boolean => a === "edit" || a === "view";

export type Direction = {
  id: number; name: string; description?: string | null; goal?: string | null;
  color?: string | null; status: DirectionStatus; created_at: string; owner?: UserBrief | null; access?: Access | null;
};
export type DirectionIn = Omit<Direction, "id" | "created_at" | "owner" | "access">;

export type Project = {
  id: number; direction_id: number; name: string; description?: string | null; goal?: string | null;
  color?: string | null; status: DirectionStatus; created_at: string; owner?: UserBrief | null; access?: Access | null;
};
export type ProjectIn = Omit<Project, "id" | "created_at" | "owner" | "access">;

export type ShareEntity = "direction" | "project" | "task";
export type Permission = "view" | "edit";
export type Share = { id: number; entity_type: ShareEntity; entity_id: number; permission: Permission; user: UserBrief; created_at: string };
export type SharedWithMe = { entity_type: ShareEntity; entity_id: number; permission: Permission; name: string; direction_id?: number | null; shared_by?: UserBrief | null; created_at: string };
export const PERMISSION_LABEL: Record<Permission, string> = { view: "Смотреть", edit: "Редактировать" };
export const ENTITY_LABEL: Record<ShareEntity, string> = { direction: "Направление", project: "Проект", task: "Задача" };

export type Tool = {
  id: number; name: string; type: ToolType; url?: string | null;
  source_ref?: Record<string, unknown> | null; note?: string | null;
};
export type ToolIn = Omit<Tool, "id"> & { task_ids: number[]; direction_ids: number[] };

export type Task = {
  id: number; title: string; description?: string | null; status: TaskStatus; priority: number;
  deadline?: string | null; next_check_at?: string | null; outlook_event_id?: string | null;
  created_at: string; updated_at: string; directions: Direction[]; tools: Tool[]; owner?: UserBrief | null;
  project_id?: number | null; access?: Access | null; assigned_to_me?: boolean;
};
export type TaskIn = {
  title: string; description?: string | null; status: TaskStatus; priority: number;
  deadline?: string | null; next_check_at?: string | null; direction_ids: number[]; tool_ids: number[]; project_id?: number | null;
};

export type User = { id: number; email: string; name: string; is_admin: boolean; telegram_chat_id?: string | null; digest_enabled: boolean };
export type UserBrief = { id: number; name: string; email: string };

export type Person = { id: number; name: string; telegram_chat_id?: string | null; email?: string | null; note?: string | null; user_id?: number | null };
export type PersonIn = Omit<Person, "id" | "user_id">;

export type Delegation = {
  id: number; task_id: number; person_id: number; check_at?: string | null; comment?: string | null;
  status: DelegationStatus; assigned_at: string; notified_at?: string | null; report?: string | null; person: Person;
};
export type DelegationIn = Omit<Delegation, "id" | "assigned_at" | "notified_at" | "report" | "person">;
export type PersonSummary = { person: Person; total: number; open: number; done: number; overdue: number; check_due: number; tasks: Task[]; delegations: Delegation[] };

export type Recipient = "owner" | "assignees" | "both";
export type Reminder = { id: number; task_id: number; fire_at: string; channels: Channel[]; message?: string | null; recipient?: Recipient; sent_at?: string | null };
export type ReminderIn = Omit<Reminder, "id" | "sent_at">;

export type MindNode = { id: string; text: string; children: MindNode[]; collapsed?: boolean };
export type MindMap = {
  id: number; title: string; direction_id?: number | null; task_id?: number | null; data: MindNode;
  created_at: string; updated_at: string;
};
export type MindMapIn = { title: string; direction_id?: number | null; task_id?: number | null; data: MindNode };
export const MIND_COLOR = "#0f766e"; // фирменный цвет майндмапов — отличается от акцента и цветов направлений
export const newNodeId = () => Math.random().toString(36).slice(2, 10);

// ---- Словари подписей ----
export const STATUSES: TaskStatus[] = ["backlog", "in_progress", "waiting", "done"];
export const STATUS_LABEL: Record<TaskStatus, string> = {
  backlog: "Бэклог", in_progress: "В работе", waiting: "Ожидание", done: "Готово",
};
export const TOOL_TYPE_LABEL: Record<ToolType, string> = {
  google_sheet: "Google Sheet", excel_sharepoint: "Excel · SharePoint", telegram_bot: "Telegram-бот", notion: "Notion", other: "Другое",
};
export const CHANNEL_LABEL: Record<Channel, string> = { telegram: "Telegram", email: "Email", outlook_calendar: "Календарь Outlook" };
export const RECIPIENT_LABEL: Record<Recipient, string> = { owner: "Мне", assignees: "Исполнителю", both: "Мне и исполнителю" };
export const DIRECTION_STATUS_LABEL: Record<DirectionStatus, string> = { active: "Активно", paused: "На паузе", archived: "В архиве" };

// Палитра направлений — используется, если у направления не задан свой цвет.
export const DIRECTION_COLORS = ["#2F6FED", "#0E9F6E", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#BE185D", "#65A30D"];
export const dirColor = (d: Direction) => d.color || DIRECTION_COLORS[d.id % DIRECTION_COLORS.length];
/** Цвет проекта: свой или цвет направления. */
export const projColor = (p: Project, dirs: Direction[]) => p.color || (() => { const d = dirs.find((x) => x.id === p.direction_id); return d ? dirColor(d) : "var(--line-strong)"; })();

// ---- Преобразование дат между <input> и API ----
export const toDateInput = (iso?: string | null) => (iso ? iso.slice(0, 10) : "");
export const toDateTimeInput = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
export const fromDateTimeInput = (v: string) => (v ? new Date(v).toISOString() : null);

const fmtDate = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" });
const fmtDateTime = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
export const showDate = (iso?: string | null) => (iso ? fmtDate.format(new Date(iso)) : "");
export const showDateTime = (iso?: string | null) => (iso ? fmtDateTime.format(new Date(iso)) : "");
export const isOverdue = (iso?: string | null) => !!iso && new Date(iso).getTime() < Date.now();
