// v0.8: корзина и «Отменить» (тост → restore), страница «Корзина» из GET /trash, доска «Без направления», перенос проекта (move_mode + доступ).
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccessPreview, Project, Task, TrashOut } from "../api";
import Board from "../Board";
import { ConfirmProvider } from "../confirm";
import { useDeletion } from "../deletion";
import { ProjectModal } from "../ProjectMenu";
import { ToastProvider } from "../toast";
import TrashPage from "../Trash";
import { makeDirection, makeProject, makeStore, makeTask } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { api, del, post, put } from "../api";
const apiMock = vi.mocked(api) as unknown as ReturnType<typeof vi.fn<(path: string) => Promise<unknown>>>;
const delMock = vi.mocked(del) as unknown as ReturnType<typeof vi.fn<(path: string) => Promise<void>>>;
const postMock = vi.mocked(post) as unknown as ReturnType<typeof vi.fn<(path: string, body: unknown) => Promise<unknown>>>;
const putMock = vi.mocked(put) as unknown as ReturnType<typeof vi.fn<(path: string, body: unknown) => Promise<unknown>>>;

beforeEach(() => { apiMock.mockReset(); delMock.mockReset(); postMock.mockReset(); putMock.mockReset(); apiMock.mockResolvedValue([]); delMock.mockResolvedValue(undefined); });
afterEach(() => vi.restoreAllMocks());

const wrap = (ui: React.ReactElement) => render(<ToastProvider><ConfirmProvider>{ui}</ConfirmProvider></ToastProvider>);

/** Кнопка «Удалить», вызывающая useDeletion как в TaskPanel/DirectionMenu. */
function Deleter({ store, task }: { store: ReturnType<typeof makeStore>; task: Task }) {
  const { deleteTask } = useDeletion(store);
  return <button onClick={() => void deleteTask(task)}>del</button>;
}

describe("Удаление → корзина → тост «Отменить» → restore", () => {
  it("после подтверждения: DELETE /tasks/id, store.reload, тост с названием; «Отменить» → POST /tasks/id/restore и reload", async () => {
    const task = makeTask({ id: 100, title: "Согласовать КП" });
    const store = makeStore({ tasks: [task] });
    postMock.mockResolvedValue(task);
    wrap(<Deleter store={store} task={task} />);
    await act(async () => { fireEvent.click(screen.getByText("del")); });
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Удалить задачу?");
    expect(within(dialog).getByRole("button", { name: "Отмена" })).toHaveFocus();
    await act(async () => { fireEvent.click(within(dialog).getByRole("button", { name: "Удалить задачу" })); });
    await waitFor(() => expect(delMock).toHaveBeenCalledWith("/tasks/100"));
    await waitFor(() => expect(store.reload).toHaveBeenCalledTimes(1));
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("Задача «Согласовать КП» удалена");
    await act(async () => { fireEvent.click(within(toast).getByRole("button", { name: "Отменить" })); });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/tasks/100/restore", {}));
    await waitFor(() => expect(store.reload).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("отказ в диалоге — ничего не удаляется и тоста нет", async () => {
    const task = makeTask();
    wrap(<Deleter store={makeStore({ tasks: [task] })} task={task} />);
    await act(async () => { fireEvent.click(screen.getByText("del")); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Отмена" })); });
    expect(delMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("Страница «Корзина» (GET /trash)", () => {
  const trash: TrashOut = {
    directions: [makeDirection({ id: 1, name: "Закуп", deleted_at: "2026-09-03T10:00:00Z" })],
    projects: [makeProject({ id: 10, direction_id: 1, name: "Договор основной", deleted_at: "2026-09-03T10:00:00Z" })],
    tasks: [makeTask({ id: 100, title: "Согласовать КП", deleted_at: "2026-09-02T09:00:00Z", directions: [] })],
  };

  it("показывает три группы, восстановление направления шлёт POST /directions/1/restore", async () => {
    apiMock.mockImplementation(async (path: string) => (path === "/trash" ? trash : []));
    postMock.mockResolvedValue(trash.directions[0]);
    const store = makeStore();
    wrap(<TrashPage store={store} />);
    expect(await screen.findByText("Закуп")).toBeInTheDocument();
    expect(screen.getByText("Договор основной")).toBeInTheDocument();
    expect(screen.getByText("Согласовать КП")).toBeInTheDocument();
    expect(screen.getByText(/направление тоже в корзине/)).toBeInTheDocument();
    const row = screen.getByText("Закуп").closest(".arch-row")!;
    await act(async () => { fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Восстановить" })); });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/directions/1/restore", {}));
    await waitFor(() => expect(store.reload).toHaveBeenCalled());
  });

  it("409 при восстановлении проекта — текст сервера показан на странице", async () => {
    apiMock.mockImplementation(async (path: string) => (path === "/trash" ? trash : []));
    const { ApiError } = await vi.importActual<typeof import("../api")>("../api");
    postMock.mockRejectedValue(new ApiError(409, '409 {"detail":"Сначала восстановите направление"}'));
    wrap(<TrashPage store={makeStore()} />);
    const row = (await screen.findByText("Договор основной")).closest(".arch-row")!;
    await act(async () => { fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Восстановить" })); });
    expect(await screen.findByRole("alert")).toHaveTextContent("Сначала восстановите направление");
  });

  it("«Очистить корзину» требует ввести слово «корзина», затем DELETE /trash", async () => {
    apiMock.mockImplementation(async (path: string) => (path === "/trash" ? trash : []));
    wrap(<TrashPage store={makeStore()} />);
    await screen.findByText("Закуп");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Очистить корзину…" })); });
    const ok = screen.getByRole("button", { name: "Очистить" });
    expect(ok).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Введите название, чтобы подтвердить"), { target: { value: "корзина" } });
    await act(async () => { fireEvent.click(ok); });
    await waitFor(() => expect(delMock).toHaveBeenCalledWith("/trash"));
  });

  it("пустая корзина — сообщение", async () => {
    apiMock.mockImplementation(async (path: string) => (path === "/trash" ? { directions: [], projects: [], tasks: [] } : []));
    wrap(<TrashPage store={makeStore()} />);
    expect(await screen.findByText("Корзина пуста")).toBeInTheDocument();
  });
});

describe("Доска «Без направления» (Н1)", () => {
  it("orphans=true показывает только задачи без направлений", () => {
    const d = makeDirection();
    const store = makeStore({
      directions: [d],
      tasks: [makeTask({ id: 1, title: "С направлением", directions: [d] }), makeTask({ id: 2, title: "Сирота", directions: [] }), makeTask({ id: 3, title: "Сирота готовая", directions: [], status: "done" })],
    });
    render(<Board store={store} direction={null} project={null} looseOnly={false} orphans selectedId={null} onSelect={vi.fn()} onEditDirection={vi.fn()} onOpenDirection={vi.fn()} onEditProject={vi.fn()} onShare={vi.fn()} onOpenMindmap={vi.fn()} onMindmaps={vi.fn()} />);
    expect(screen.getByText("Сирота")).toBeInTheDocument();
    expect(screen.getByText("Сирота готовая")).toBeInTheDocument();
    expect(screen.queryByText("С направлением")).toBeNull();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Без направления");
  });
});

describe("ProjectModal — перенос в другое направление", () => {
  const d1 = makeDirection({ id: 1, name: "Закуп" });
  const d2 = makeDirection({ id: 2, name: "Команда" });
  const project = makeProject({ id: 10, direction_id: 1 });
  const preview: AccessPreview[] = [
    { user: { id: 5, name: "Айгуль", email: "a@cis.kz" }, permission: "edit", keeps_access: false },
    { user: { id: 6, name: "Борис", email: "b@cis.kz" }, permission: "view", keeps_access: true },
    { user: { id: 7, name: "Вика", email: "v@cis.kz" }, permission: "view", keeps_access: false },
  ];

  it("смена направления → блок переноса с превью доступа; PUT содержит move_mode и grant_access_user_ids (снятый чекбокс исключается)", async () => {
    apiMock.mockImplementation(async (path: string) => (path.startsWith("/projects/10/access-preview?direction_id=2") ? preview : []));
    putMock.mockResolvedValue({ ...project, direction_id: 2 } satisfies Project);
    const store = makeStore({ directions: [d1, d2], projects: [project] });
    const onSaved = vi.fn();
    wrap(<ProjectModal store={store} direction={d1} project={project} onClose={vi.fn()} onSaved={onSaved} />);
    expect(screen.queryByTestId("move-block")).toBeNull();
    fireEvent.change(screen.getByDisplayValue("Закуп"), { target: { value: "2" } });
    expect(screen.getByTestId("move-block")).toBeInTheDocument();
    expect(await screen.findByText("Айгуль")).toBeInTheDocument();
    expect(screen.getByLabelText("Оставить доступ: Айгуль")).toBeChecked();      // теряющие доступ — отмечены по умолчанию
    expect(screen.queryByLabelText("Оставить доступ: Борис")).toBeNull();          // сохраняет доступ сам — без чекбокса
    fireEvent.click(screen.getByLabelText("Оставить доступ: Вика"));                // Вике не оставляем
    fireEvent.click(screen.getByRole("radio", { name: /Скопировать/ }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Скопировать и сохранить" })); });
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(putMock.mock.calls[0][0]).toBe("/projects/10");
    expect(putMock.mock.calls[0][1]).toMatchObject({ direction_id: 2, move_mode: "copy", grant_access_user_ids: [5] });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(store.reloadTasks).toHaveBeenCalled();
  });

  it("без смены направления move_mode в PUT не уходит", async () => {
    putMock.mockResolvedValue(project);
    const store = makeStore({ directions: [d1, d2], projects: [project] });
    wrap(<ProjectModal store={store} direction={d1} project={project} onClose={vi.fn()} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/Договор основной/), { target: { value: "Договор новый" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Сохранить" })); });
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(putMock.mock.calls[0][1]).not.toHaveProperty("move_mode");
  });
});
