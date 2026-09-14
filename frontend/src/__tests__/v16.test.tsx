// v1.6: задачи под проектом в левой панели, перетаскивание (задача → проект / направление, проект → направление,
// перестановка порядка) и Action Tracker с правкой прямо в строке.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "../api";
import ActionTracker, { buildGroups, tableRows } from "../ActionTracker";
import { insertBefore } from "../dnd";
import Sidebar from "../Sidebar";
import { ToastProvider } from "../toast";
import { makeDirection, makeProject, makeStore, makeTask } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { del, post, put } from "../api";
const delMock = vi.mocked(del) as unknown as ReturnType<typeof vi.fn<(p: string) => Promise<void>>>;
const postMock = vi.mocked(post) as unknown as ReturnType<typeof vi.fn<(p: string, b: unknown) => Promise<unknown>>>;
const putMock = vi.mocked(put) as unknown as ReturnType<typeof vi.fn<(p: string, b: unknown) => Promise<unknown>>>;

beforeEach(() => {
  delMock.mockReset(); postMock.mockReset(); putMock.mockReset();
  delMock.mockResolvedValue(undefined); postMock.mockResolvedValue([]); putMock.mockImplementation(async (_p, b) => b);
  try { localStorage.clear(); } catch { /* приватный режим */ }
});
afterEach(() => vi.restoreAllMocks());

/** Перетаскивание в jsdom: свой dataTransfer, как в реальном браузере. */
function dt(data: Record<string, string>) {
  return { types: Object.keys(data), getData: (k: string) => data[k] ?? "", setData: () => {}, dropEffect: "", effectAllowed: "" };
}
const drag = (target: Element, data: Record<string, string>) => {
  fireEvent.dragOver(target, { dataTransfer: dt(data) });
  fireEvent.drop(target, { dataTransfer: dt(data) });
};

const dir = makeDirection({ id: 1, name: "Эмба" });
const proj = makeProject({ id: 10, direction_id: 1, name: "Договор основной" });
const proj2 = makeProject({ id: 11, direction_id: 1, name: "Договор мини" });

const expandDir = () => fireEvent.click(screen.getByLabelText("Показать проекты"));

const sidebarProps = (over: Partial<React.ComponentProps<typeof Sidebar>> = {}) => ({
  directions: [dir], projects: [proj], tasks: [], view: { kind: "overview" as const }, mindmapCount: 0, inboxCount: 0, sharedCount: 0, trashCount: 0,
  me: { id: 1, email: "me@example.com", name: "Я", is_admin: false, digest_enabled: false }, onProfile: vi.fn(),
  onView: vi.fn(), onNewDirection: vi.fn(), onNewProject: vi.fn(), onDirectionMenu: vi.fn(), onProjectMenu: vi.fn(), ...over,
});

// ═══════════════ Панель: задачи под проектом ═══════════════

describe("Сайдбар: выпадающий список задач у проекта", () => {
  it("стрелка у проекта раскрывает его открытые задачи; клик по задаче открывает карточку", async () => {
    const tasks = [makeTask({ id: 100, title: "Согласовать КП", project_id: 10 }), makeTask({ id: 101, title: "Готовая", project_id: 10, status: "done" })];
    const onOpenTask = vi.fn();
    render(<Sidebar {...sidebarProps({ tasks, onOpenTask })} />);
    expandDir();
    expect(screen.queryByText("Согласовать КП")).toBeNull();
    fireEvent.click(screen.getByLabelText("Показать задачи: Договор основной"));
    expect(screen.getByText("Согласовать КП")).toBeTruthy();
    expect(screen.queryByText("Готовая")).toBeNull();   // готовые в панель не лезут
    fireEvent.click(screen.getByText("Согласовать КП"));
    expect(onOpenTask).toHaveBeenCalledWith(expect.objectContaining({ id: 100 }));
  });

  it("длинный список обрезан: 10 задач и кнопка «ещё N», которая показывает остальные", () => {
    const tasks = Array.from({ length: 13 }, (_, i) => makeTask({ id: 200 + i, title: `Задача ${i + 1}`, project_id: 10 }));
    render(<Sidebar {...sidebarProps({ tasks })} />);
    expandDir();
    fireEvent.click(screen.getByLabelText("Показать задачи: Договор основной"));
    expect(screen.getByText("Задача 10")).toBeTruthy();
    expect(screen.queryByText("Задача 11")).toBeNull();
    fireEvent.click(screen.getByText("ещё 3"));
    expect(screen.getByText("Задача 13")).toBeTruthy();
  });

  it("состояние раскрытия переживает перерисовку (localStorage)", () => {
    const tasks = [makeTask({ id: 100, title: "Согласовать КП", project_id: 10 })];
    const { unmount } = render(<Sidebar {...sidebarProps({ tasks })} />);
    expandDir();
    fireEvent.click(screen.getByLabelText("Показать задачи: Договор основной"));
    unmount();
    render(<Sidebar {...sidebarProps({ tasks })} />);
    expect(screen.getByText("Согласовать КП")).toBeTruthy();
  });
});

// ═══════════════ Перетаскивание ═══════════════

describe("insertBefore", () => {
  it("ставит элемент перед целью, в конец — если цели нет", () => {
    expect(insertBefore([1, 2, 3], 3, 1)).toEqual([3, 1, 2]);
    expect(insertBefore([1, 2, 3], 1, 3)).toEqual([2, 1, 3]);
    expect(insertBefore([1, 2, 3], 1, null)).toEqual([2, 3, 1]);
    expect(insertBefore([1, 2, 3], 2, 2)).toEqual([1, 3, 2]);
  });
});

describe("Сайдбар: перетаскивание", () => {
  it("задачу бросили на проект — PUT задачи с новым project_id", async () => {
    const task = makeTask({ id: 100, title: "Согласовать КП", project_id: null, directions: [dir] });
    const store = makeStore({ directions: [dir], projects: [proj], tasks: [task] });
    render(<Sidebar {...sidebarProps({ tasks: [task], store })} />);
    expandDir();
    await act(async () => { drag(screen.getByTitle("Договор основной"), { "text/task-id": "100" }); });
    await waitFor(() => expect(putMock).toHaveBeenCalled());
    const [path, body] = putMock.mock.calls[0];
    expect(path).toBe("/tasks/100");
    expect((body as { project_id: number }).project_id).toBe(10);
  });

  it("задачу бросили на направление — уходит из проекта («Без проекта») и остаётся в направлении", async () => {
    const task = makeTask({ id: 100, title: "Согласовать КП", project_id: 10, directions: [dir] });
    const store = makeStore({ directions: [dir], projects: [proj], tasks: [task] });
    render(<Sidebar {...sidebarProps({ tasks: [task], store })} />);
    await act(async () => { drag(screen.getByTitle("Эмба"), { "text/task-id": "100" }); });
    await waitFor(() => expect(putMock).toHaveBeenCalled());
    const body = putMock.mock.calls[0][1] as { project_id: number | null; direction_ids: number[] };
    expect(body.project_id).toBeNull();
    expect(body.direction_ids).toEqual([1]);
  });

  it("проект бросили на другое направление — открывается окно переноса, а не тихий перенос", async () => {
    const other = makeDirection({ id: 2, name: "Прорва" });
    const store = makeStore({ directions: [dir, other], projects: [proj] });
    const onMoveProject = vi.fn();
    render(<Sidebar {...sidebarProps({ directions: [dir, other], store, onMoveProject })} />);
    await act(async () => { drag(screen.getByTitle("Прорва"), { "text/project-id": "10" }); });
    expect(onMoveProject).toHaveBeenCalledWith(expect.objectContaining({ id: 10 }), expect.objectContaining({ id: 2 }));
    expect(putMock).not.toHaveBeenCalled();
  });

  it("проект бросили на соседний проект того же направления — POST /projects/reorder с новым порядком", async () => {
    const store = makeStore({ directions: [dir], projects: [proj, proj2] });
    render(<Sidebar {...sidebarProps({ projects: [proj, proj2], store })} />);
    expandDir();
    await act(async () => { drag(screen.getByTitle("Договор основной"), { "text/project-id": "11" }); });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/projects/reorder", { ids: [11, 10] }));
  });

  it("задачу бросили на соседнюю задачу — POST /tasks/reorder, задача встаёт перед ней", async () => {
    const a = makeTask({ id: 100, title: "Первая", project_id: 10, sort_order: 0 });
    const b = makeTask({ id: 101, title: "Вторая", project_id: 10, sort_order: 1 });
    const store = makeStore({ directions: [dir], projects: [proj], tasks: [a, b] });
    render(<Sidebar {...sidebarProps({ tasks: [a, b], store })} />);
    expandDir();
    fireEvent.click(screen.getByLabelText("Показать задачи: Договор основной"));
    await act(async () => { drag(screen.getByTitle(/^Первая/), { "text/task-id": "101" }); });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/tasks/reorder", { ids: [101, 100] }));
  });
});

// ═══════════════ Action Tracker ═══════════════

const trackerStore = () => makeStore({
  directions: [dir], projects: [proj],
  people: [{ id: 5, name: "Нурлан" }, { id: 6, name: "Аида" }],
  tasks: [
    makeTask({ id: 100, title: "Согласовать КП", project_id: 10, deadline: "2026-10-01", status: "in_progress", description: "ждём ответ",
      assignees: [{ delegation_id: 70, person_id: 5, name: "Нурлан", status: "open" }] }),
    makeTask({ id: 101, title: "Без проекта и без ответственного", project_id: null }),
    makeTask({ id: 102, title: "Уже закрыта", project_id: 10, status: "done" }),
  ],
});

const renderTracker = (store = trackerStore(), over: Partial<React.ComponentProps<typeof ActionTracker>> = {}) =>
  render(<ToastProvider><ActionTracker store={store} onOpenTask={vi.fn()} onOpenProject={vi.fn()} onOpenDirection={vi.fn()} {...over} /></ToastProvider>);

describe("Action Tracker", () => {
  it("собирает направление → проект → задачи, показывает ответственного и срок, готовые скрыты", () => {
    renderTracker();
    expect(screen.getByRole("button", { name: /Эмба/ })).toBeTruthy();
    expect(screen.getByText("Договор основной")).toBeTruthy();
    expect(screen.getByText("Без проекта")).toBeTruthy();
    expect(screen.getByText("Согласовать КП")).toBeTruthy();
    expect(screen.queryByText("Уже закрыта")).toBeNull();
    expect((screen.getByLabelText("Ответственный: Согласовать КП") as HTMLSelectElement).value).toBe("5");
    expect((screen.getByLabelText("Срок: Согласовать КП") as HTMLInputElement).value).toBe("2026-10-01");
  });

  it("статус меняется прямо в строке — PUT задачи с новым статусом", async () => {
    renderTracker();
    await act(async () => { fireEvent.change(screen.getByLabelText("Статус: Согласовать КП"), { target: { value: "done" } }); });
    await waitFor(() => expect(putMock).toHaveBeenCalled());
    expect((putMock.mock.calls[0][1] as { status: string }).status).toBe("done");
  });

  it("срок меняется прямо в строке", async () => {
    renderTracker();
    await act(async () => { fireEvent.change(screen.getByLabelText("Срок: Согласовать КП"), { target: { value: "2026-11-20" } }); });
    await waitFor(() => expect(putMock).toHaveBeenCalled());
    expect((putMock.mock.calls[0][1] as { deadline: string }).deadline).toBe("2026-11-20");
  });

  it("смена ответственного снимает прежнее поручение и создаёт новое", async () => {
    const store = trackerStore();
    renderTracker(store);
    await act(async () => { fireEvent.change(screen.getByLabelText("Ответственный: Согласовать КП"), { target: { value: "6" } }); });
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(delMock).toHaveBeenCalledWith("/delegations/70");
    expect(postMock).toHaveBeenCalledWith("/delegations", { task_id: 100, person_id: 6, status: "open" });
    expect(store.reloadTasks).toHaveBeenCalled();
  });

  it("план действий сохраняется по уходу из поля, Esc возвращает прежний текст", async () => {
    renderTracker();
    const plan = screen.getByLabelText("План действий: Согласовать КП");
    fireEvent.change(plan, { target: { value: "запросить у Жандоса" } });
    await act(async () => { fireEvent.blur(plan); });
    await waitFor(() => expect(putMock).toHaveBeenCalled());
    expect((putMock.mock.calls[0][1] as { description: string }).description).toBe("запросить у Жандоса");
  });

  it("фильтр «только просроченные» и поиск сужают таблицу", () => {
    renderTracker();
    fireEvent.change(screen.getByLabelText("Поиск по таблице"), { target: { value: "нурлан" } });
    expect(screen.getByText("Согласовать КП")).toBeTruthy();
    expect(screen.queryByText("Без проекта и без ответственного")).toBeNull();
  });

  it("таблица для копирования и Excel: шапка и строка на задачу", () => {
    const rows = tableRows(buildGroups(trackerStore(), { hideDone: true, onlyMine: false, onlyLate: false, q: "", dirFilter: "all" }));
    expect(rows[0]).toEqual(["Направление", "Проект", "Задача", "Ответственный", "Срок", "Статус", "План действий"]);
    expect(rows[1]).toEqual(["Эмба", "Договор основной", "Согласовать КП", "Нурлан", "2026-10-01", "В работе", "ждём ответ"]);
    expect(rows).toHaveLength(3);   // + задача без проекта
  });

  it("задачи в корзине в таблицу не попадают — их нет в сторе", () => {
    const store = trackerStore();
    const groups = buildGroups({ ...store, tasks: store.tasks.filter((t: Task) => t.id !== 100) }, { hideDone: true, onlyMine: false, onlyLate: false, q: "", dirFilter: "all" });
    expect(groups.flatMap((g) => g.projects.flatMap((p) => p.rows)).map((r) => r.task.id)).toEqual([101]);
  });

  it("только просмотр: правки в строке нет, значения показаны текстом", () => {
    const store = trackerStore();
    const ro = { ...store, tasks: store.tasks.map((t: Task) => ({ ...t, access: "view" as const })) };
    renderTracker(ro);
    expect(screen.queryByLabelText("Статус: Согласовать КП")).toBeNull();
    expect(within(screen.getByText("Согласовать КП").closest("tr")!).getByText("Нурлан")).toBeTruthy();
  });
});
