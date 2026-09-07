// v0.11: телефон — нижняя панель вкладок, шторка «Ещё» с левой панелью, доска стартует с «В работе» и меняет статус через «⋯».
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Board from "../Board";
import MobileNav from "../MobileNav";
import { makeDirection, makeStore, makeTask } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(async () => ({})), post: vi.fn(async () => ({})), del: vi.fn() };
});
import { put } from "../api";

let listeners: Array<() => void> = [];
function setMobile(on: boolean) {
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: on, media: "", onchange: null,
    addEventListener: (_: string, cb: () => void) => listeners.push(cb), removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
beforeEach(() => { listeners = []; setMobile(true); });
afterEach(() => { vi.restoreAllMocks(); });

const navProps = (over: Partial<React.ComponentProps<typeof MobileNav>> = {}) => ({
  directions: [makeDirection()], projects: [], tasks: [], view: { kind: "overview" as const }, mindmapCount: 0, inboxCount: 2, sharedCount: 0, trashCount: 0,
  me: { id: 1, email: "me@example.com", name: "Я", is_admin: false, digest_enabled: false }, onProfile: vi.fn(),
  onView: vi.fn(), onNewDirection: vi.fn(), onNewProject: vi.fn(), onDirectionMenu: vi.fn(), onProjectMenu: vi.fn(), ...over,
});

describe("MobileNav", () => {
  it("четыре вкладки, счётчик «Поручено», переход по вкладке вызывает onView", () => {
    const p = navProps();
    render(<MobileNav {...p} />);
    expect(screen.getByRole("navigation", { name: "Основные разделы" })).toBeInTheDocument();
    expect(screen.getByText("2")).toHaveClass("tabbar-badge");
    fireEvent.click(screen.getByText("Задачи"));
    expect(p.onView).toHaveBeenCalledWith({ kind: "board", directionId: null });
  });

  it("«Ещё» открывает шторку с левой панелью; выбор направления закрывает шторку и открывает карту проектов", () => {
    const p = navProps();
    render(<MobileNav {...p} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByText("Ещё"));
    expect(screen.getByRole("dialog", { name: "Разделы и направления" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Закуп"));
    expect(p.onView).toHaveBeenCalledWith({ kind: "direction", directionId: 1 });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Board на телефоне", () => {
  const boardProps = (store: ReturnType<typeof makeStore>) => ({
    store, direction: null, project: null, looseOnly: false, selectedId: null, onSelect: vi.fn(), onEditDirection: vi.fn(), onOpenDirection: vi.fn(),
    onEditProject: vi.fn(), onShare: vi.fn(), onOpenMindmap: vi.fn(), onMindmaps: vi.fn(),
  });

  it("стартует с одной колонки «В работе»; повторный тап по вкладке не сбрасывает фильтр", () => {
    const store = makeStore({ tasks: [makeTask({ id: 1, title: "В бэклоге", status: "backlog" }), makeTask({ id: 2, title: "Идёт", status: "in_progress" })] });
    render(<Board {...boardProps(store)} />);
    expect(screen.getByText("Идёт")).toBeInTheDocument();
    expect(screen.queryByText("В бэклоге")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: /В работе/ }));
    expect(screen.getByText("Идёт")).toBeInTheDocument();
    expect(screen.queryByText("В бэклоге")).toBeNull();
    expect(document.querySelector(".board")).toHaveClass("single");
  });

  it("«⋯» на карточке → меню статусов → PUT с новым статусом, карточка не открывается", async () => {
    const t = makeTask({ id: 2, title: "Идёт", status: "in_progress" });
    const store = makeStore({ tasks: [t] });
    const props = boardProps(store);
    render(<Board {...props} />);
    fireEvent.click(screen.getByLabelText("Сменить статус задачи"));
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "→ Готово" })); });
    expect(vi.mocked(put)).toHaveBeenCalledWith("/tasks/2", expect.objectContaining({ status: "done" }));
    expect(store.patchTask).toHaveBeenCalledWith(expect.objectContaining({ id: 2, status: "done" }));
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("на компьютере доска по-прежнему стартует со всех колонок", () => {
    setMobile(false);
    const store = makeStore({ tasks: [makeTask({ id: 1, title: "В бэклоге", status: "backlog" }), makeTask({ id: 2, title: "Идёт", status: "in_progress" })] });
    render(<Board {...boardProps(store)} />);
    expect(screen.getByText("В бэклоге")).toBeInTheDocument();
    expect(screen.getByText("Идёт")).toBeInTheDocument();
  });
});
