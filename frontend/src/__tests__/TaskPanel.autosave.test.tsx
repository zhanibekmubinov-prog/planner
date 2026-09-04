// В1 / В2 — автосохранение карточки задачи: потеря правки при быстром закрытии и откат при гонке.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Task, TaskIn } from "../api";
import TaskPanel from "../TaskPanel";
import { makeStore, makeTask } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { put } from "../api";
const putMock = vi.mocked(put) as unknown as ReturnType<typeof vi.fn<(path: string, body: TaskIn) => Promise<Task>>>;

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

/** Как в App: store.patchTask меняет задачу → в панель приходит новый prop task. */
function Harness({ initial, onClose }: { initial: Task; onClose?: () => void }) {
  const [task, setTask] = useState(initial);
  const store = makeStore({ tasks: [task], patchTask: (t) => setTask(t) });
  return <TaskPanel store={store} task={task} onClose={onClose ?? (() => {})} onDeleted={() => {}} onOpenMindmap={() => {}} onShare={() => {}} />;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const titleBox = () => screen.getByPlaceholderText("Название задачи") as HTMLTextAreaElement;

beforeEach(() => { putMock.mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });

describe("TaskPanel — автосохранение (В1, В2)", () => {
  it("В1: закрытие панели раньше 600 мс не теряет правку — PUT уходит с новым названием", async () => {
    putMock.mockImplementation(async (_p, body) => makeTask({ ...body, id: 100 } as Partial<Task>));
    const { unmount } = render(<Harness initial={makeTask()} />);
    fireEvent.change(titleBox(), { target: { value: "Согласовать КП с юристами" } });
    expect(screen.getByText("изменено")).toBeInTheDocument();
    unmount();                                   // Esc / крестик / клик мимо — панель размонтирована
    await sleep(750);
    expect(putMock).toHaveBeenCalledTimes(1);
    expect(putMock.mock.calls[0][1].title).toBe("Согласовать КП с юристами");
  });

  it("В2: набор текста во время запроса не откатывается — последний PUT содержит актуальный текст", async () => {
    const first = deferred<Task>();
    putMock.mockImplementationOnce(() => first.promise)
      .mockImplementation(async (_p, body) => makeTask({ ...body, id: 100 } as Partial<Task>));
    render(<Harness initial={makeTask()} />);

    fireEvent.change(titleBox(), { target: { value: "Согласовать КП A" } });
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1), { timeout: 2000 });   // первый PUT в полёте

    fireEvent.change(titleBox(), { target: { value: "Согласовать КП AB" } });            // печатаем дальше
    await act(async () => { first.resolve(makeTask({ title: "Согласовать КП A" })); await Promise.resolve(); });

    // Ожидаемое: поле не «прыгает назад» и второй PUT уходит с «AB»
    expect(titleBox().value).toBe("Согласовать КП AB");
    await waitFor(() => expect(putMock.mock.calls.length).toBeGreaterThanOrEqual(2), { timeout: 2000 });
    expect(putMock.mock.calls[putMock.mock.calls.length - 1][1].title).toBe("Согласовать КП AB");
  });

  it("регрессия: пауза 600 мс после правки → один PUT с новым названием, шапка «сохранено»", async () => {
    putMock.mockImplementation(async (_p, body) => makeTask({ ...body, id: 100 } as Partial<Task>));
    render(<Harness initial={makeTask()} />);
    fireEvent.change(titleBox(), { target: { value: "Новое название" } });
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(putMock.mock.calls[0][0]).toBe("/tasks/100");
    expect(putMock.mock.calls[0][1].title).toBe("Новое название");
    await waitFor(() => expect(screen.getByText("сохранено")).toBeInTheDocument());
    await sleep(700);
    expect(putMock).toHaveBeenCalledTimes(1);   // повторных PUT нет
  });
});
