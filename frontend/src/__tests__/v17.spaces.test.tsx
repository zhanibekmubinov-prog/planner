// v1.7: слои «Личное» / «Организация».
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Sidebar from "../Sidebar";
import { filterForSpace, readSpace, spaceOfTask } from "../spaces";
import { makeDirection, makeProject, makeStore, makeTask } from "./fixtures";

const personal = makeDirection({ id: 1, name: "Личное развитие", space: "personal" });
const org = makeDirection({ id: 2, name: "Эмба", space: "org" });

describe("раскладка по слоям", () => {
  it("направления попадают каждое в свой слой", () => {
    const data = { directions: [personal, org], projects: [], tasks: [], mindmaps: [], trash: null };
    expect(filterForSpace("personal", data).directions.map((d) => d.name)).toEqual(["Личное развитие"]);
    expect(filterForSpace("org", data).directions.map((d) => d.name)).toEqual(["Эмба"]);
  });

  it("направление без поля space считается личным (старые данные)", () => {
    const old = makeDirection({ id: 3, name: "Старое", space: undefined });
    const data = { directions: [old], projects: [], tasks: [], mindmaps: [], trash: null };
    expect(filterForSpace("personal", data).directions).toHaveLength(1);
    expect(filterForSpace("org", data).directions).toHaveLength(0);
  });

  it("проект идёт за своим направлением", () => {
    const p = makeProject({ id: 10, direction_id: 2 });
    const data = { directions: [personal, org], projects: [p], tasks: [], mindmaps: [], trash: null };
    expect(filterForSpace("org", data).projects).toHaveLength(1);
    expect(filterForSpace("personal", data).projects).toHaveLength(0);
  });

  it("майндмап без направления виден в обоих слоях", () => {
    const m = { id: 5, title: "Карта", direction_id: null, task_id: null, data: { id: "r", text: "r", children: [] }, created_at: "", updated_at: "" };
    const data = { directions: [personal, org], projects: [], tasks: [], mindmaps: [m], trash: null };
    expect(filterForSpace("personal", data).mindmaps).toHaveLength(1);
    expect(filterForSpace("org", data).mindmaps).toHaveLength(1);
  });
});

describe("слой задачи", () => {
  it("задача берёт слой своих направлений", () => {
    expect(spaceOfTask(makeTask({ directions: [org] }))).toEqual(["org"]);
    expect(spaceOfTask(makeTask({ directions: [personal] }))).toEqual(["personal"]);
  });

  it("кросс-направленческая задача видна в обоих слоях — прятать её было бы ложью", () => {
    const t = makeTask({ directions: [personal, org] });
    expect(spaceOfTask(t).sort()).toEqual(["org", "personal"]);
    const data = { directions: [personal, org], projects: [], tasks: [t], mindmaps: [], trash: null };
    expect(filterForSpace("personal", data).tasks).toHaveLength(1);
    expect(filterForSpace("org", data).tasks).toHaveLength(1);
  });

  it("задача без направлений несёт слой сама", () => {
    const t = makeTask({ directions: [], space: "org" });
    const data = { directions: [], projects: [], tasks: [t], mindmaps: [], trash: null };
    expect(filterForSpace("org", data).tasks).toHaveLength(1);
    expect(filterForSpace("personal", data).tasks).toHaveLength(0);
  });

  it("задача без направлений и без слоя — личная", () => {
    expect(spaceOfTask(makeTask({ directions: [], space: null }))).toEqual(["personal"]);
  });
});

describe("корзина у каждого слоя своя", () => {
  it("удалённое личное направление не всплывает в рабочей корзине", () => {
    const trash = { directions: [makeDirection({ id: 9, name: "Удалённое", space: "personal" })], projects: [], tasks: [] };
    const data = { directions: [], projects: [], tasks: [], mindmaps: [], trash };
    expect(filterForSpace("personal", data).trash?.directions).toHaveLength(1);
    expect(filterForSpace("org", data).trash?.directions).toHaveLength(0);
  });
});

describe("вкладки в панели", () => {
  const props = {
    directions: [personal], projects: [], tasks: [], view: { kind: "overview" } as const,
    mindmapCount: 0, inboxCount: 0, sharedCount: 0, trashCount: 0,
    me: null, onProfile: vi.fn(), onView: vi.fn(), onNewDirection: vi.fn(), onNewProject: vi.fn(),
    onDirectionMenu: vi.fn(), onProjectMenu: vi.fn(), store: makeStore(),
  };

  beforeEach(() => { try { localStorage.clear(); } catch { /* приватный режим */ } });

  it("обе вкладки видны всегда, со счётчиками", () => {
    render(<Sidebar {...props} space="personal" onSpace={vi.fn()} personalCount={3} orgCount={7} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Личное3", "Организация7"]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
  });

  it("клик переключает слой", () => {
    const onSpace = vi.fn();
    render(<Sidebar {...props} space="personal" onSpace={onSpace} personalCount={0} orgCount={0} />);
    fireEvent.click(screen.getByRole("tab", { name: /Организация/ }));
    expect(onSpace).toHaveBeenCalledWith("org");
  });

  it("выбранный слой переживает перезагрузку", () => {
    localStorage.setItem("planner.space", "org");
    expect(readSpace()).toBe("org");
  });

  it("мусор в localStorage не ломает приложение", () => {
    localStorage.setItem("planner.space", "что-то не то");
    expect(readSpace()).toBe("personal");
  });
});
