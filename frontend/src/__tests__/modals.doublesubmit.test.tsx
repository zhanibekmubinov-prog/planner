// С2 — двойной Enter в модалках создания направления/проекта должен давать ровно один POST.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Direction, Project } from "../api";
import DirectionModal from "../DirectionModal";
import { ProjectModal } from "../ProjectMenu";
import { makeDirection, makeProject, makeStore } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { post } from "../api";
const postMock = vi.mocked(post) as unknown as ReturnType<typeof vi.fn<(path: string, body: unknown) => Promise<unknown>>>;

function pending<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => postMock.mockReset());
afterEach(() => vi.restoreAllMocks());

/** «Сервер ответил»: резолвим отложенный промис и даём эффектам доиграть, чтобы cleanup не ждал вечно. */
const settle = (resolve: () => void) => act(async () => { resolve(); await Promise.resolve(); await Promise.resolve(); });

const enterTwice = (el: HTMLElement) => {
  fireEvent.keyDown(el, { key: "Enter" });
  fireEvent.keyDown(el, { key: "Enter" });
};

describe("DirectionModal (С2)", () => {
  const setup = () => {
    const store = makeStore();
    const onSaved = vi.fn();
    render(<DirectionModal store={store} direction={null} onClose={vi.fn()} onSaved={onSaved} onDeleted={vi.fn()} />);
    const input = screen.getByPlaceholderText(/Закуп/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  Закуп  " } });
    return { input, onSaved, store };
  };

  it("С2: Enter-Enter в поле названия → ровно один POST /directions", async () => {
    const p = pending<Direction>();
    postMock.mockReturnValue(p.promise);
    const { input } = setup();
    await act(async () => { enterTwice(input); });
    const calls = postMock.mock.calls.length;
    await settle(() => p.resolve(makeDirection({ id: 5, name: "Закуп" })));
    expect(calls).toBe(1);
  });

  it("регрессия: двойной клик по «Создать» → один POST (кнопка disabled={busy})", async () => {
    const p = pending<Direction>();
    postMock.mockReturnValue(p.promise);
    setup();
    const btn = screen.getByRole("button", { name: "Создать" });
    await act(async () => { fireEvent.click(btn); });
    await act(async () => { fireEvent.click(btn); });
    const calls = postMock.mock.calls.length;
    await settle(() => p.resolve(makeDirection({ id: 5, name: "Закуп" })));
    expect(calls).toBe(1);
  });

  it("регрессия: один Enter → POST с обрезанным именем, затем reloadDirections и onSaved", async () => {
    const saved = makeDirection({ id: 5, name: "Закуп" });
    postMock.mockResolvedValue(saved);
    const { input, onSaved, store } = setup();
    await act(async () => { fireEvent.keyDown(input, { key: "Enter" }); });
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock.mock.calls[0][0]).toBe("/directions");
    expect(postMock.mock.calls[0][1]).toMatchObject({ name: "Закуп", status: "active" });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(store.reloadDirections).toHaveBeenCalledTimes(1);
  });

  it("регрессия: пустое имя → POST не уходит", async () => {
    const store = makeStore();
    render(<DirectionModal store={store} direction={null} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />);
    await act(async () => { fireEvent.keyDown(screen.getByPlaceholderText(/Закуп/), { key: "Enter" }); });
    expect(postMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
  });
});

describe("ProjectModal (С2)", () => {
  const direction = makeDirection();
  const setup = () => {
    const store = makeStore({ directions: [direction] });
    const onSaved = vi.fn();
    render(<ProjectModal store={store} direction={direction} project={null} onClose={vi.fn()} onSaved={onSaved} />);
    const input = screen.getByPlaceholderText(/Договор основной/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Договор основной" } });
    return { input, onSaved, store };
  };

  it("С2: Enter-Enter в поле названия → ровно один POST /projects", async () => {
    const p = pending<Project>();
    postMock.mockReturnValue(p.promise);
    const { input } = setup();
    await act(async () => { enterTwice(input); });
    const calls = postMock.mock.calls.length;
    await settle(() => p.resolve(makeProject({ id: 42 })));
    expect(calls).toBe(1);
  });

  it("регрессия: один Enter → POST /projects с direction_id и именем, onSaved после ответа", async () => {
    const saved = makeProject({ id: 42 });
    postMock.mockResolvedValue(saved);
    const { input, onSaved, store } = setup();
    await act(async () => { fireEvent.keyDown(input, { key: "Enter" }); });
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock.mock.calls[0][0]).toBe("/projects");
    expect(postMock.mock.calls[0][1]).toMatchObject({ name: "Договор основной", direction_id: direction.id, status: "active" });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(store.reloadProjects).toHaveBeenCalledTimes(1);
  });
});
