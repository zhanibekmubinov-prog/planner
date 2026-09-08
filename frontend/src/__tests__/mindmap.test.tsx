// v1.2 — майндмап: важность, цвет/толщина ветки, подпись линии, связи-стрелки.
// Проверяем тем, что уходит в PUT /mindmaps/:id — то, что увидит следующий, кто откроет карту.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MindMap, MindMapIn, MindNode } from "../api";
import MindMapEditor from "../MindMapEditor";
import { makeStore } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { put } from "../api";
const putMock = vi.mocked(put) as unknown as ReturnType<typeof vi.fn<(path: string, body: MindMapIn) => Promise<MindMap>>>;

const tree: MindNode = {
  id: "root", text: "ГРП", children: [
    { id: "a", text: "Насосы", children: [{ id: "a1", text: "Импеллеры", children: [] }] },
    { id: "b", text: "Химия", children: [] },
  ],
};
const map: MindMap = { id: 7, title: "ГРП", data: tree, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };

function open() {
  render(<MindMapEditor store={makeStore({ mindmaps: [map] })} map={map} onBack={() => {}} onDeleted={() => {}} />);
}
const node = (text: string) => screen.getByText(text).closest("[data-node]") as HTMLElement;
let seen = 0;   // сколько PUT уже учтено — ждём следующий, а не первый попавшийся
const lastSaved = async (): Promise<MindNode> => {
  await waitFor(() => expect(putMock.mock.calls.length).toBeGreaterThan(seen), { timeout: 2000 });
  seen = putMock.mock.calls.length;
  return putMock.mock.calls[seen - 1][1].data;
};
const find = (n: MindNode, id: string): MindNode | null => n.id === id ? n : n.children.map((c) => find(c, id)).find(Boolean) ?? null;

beforeEach(() => { seen = 0; putMock.mockReset(); putMock.mockImplementation(async (_p, body) => ({ ...map, ...body })); });
afterEach(() => { vi.restoreAllMocks(); });

describe("Майндмап v1.2", () => {
  it("важность: клавиша 2 ставит «!!», повторная — снимает; бейдж виден на узле", async () => {
    open();
    fireEvent.click(node("Насосы"));
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByLabelText("Важность 2 из 3")).toHaveTextContent("!!");
    expect(find(await lastSaved(), "a")?.priority).toBe(2);
    fireEvent.keyDown(window, { key: "2" });
    await waitFor(() => expect(screen.queryByLabelText("Важность 2 из 3")).toBeNull());
  });

  it("панель узла: цвет ветки, «толще», подпись линии — уходят в данные; у корня цвета нет", async () => {
    open();
    fireEvent.click(node("Насосы"));
    fireEvent.click(screen.getByLabelText("Цвет #DC2626"));
    fireEvent.click(screen.getByLabelText("Толще"));
    fireEvent.click(screen.getByText("Подпись"));
    fireEvent.change(screen.getByPlaceholderText(/Подпись на линии/), { target: { value: "критично" } });
    const a = find(await lastSaved(), "a")!;
    expect(a.color).toBe("#DC2626"); expect(a.width).toBe(1); expect(a.note).toBe("критично");
    expect(screen.getByTitle(/Подпись линии/)).toHaveTextContent("критично");
    fireEvent.click(node("ГРП"));
    expect(screen.queryByLabelText("Цвет #DC2626")).toBeNull();
    expect(screen.getByLabelText("Толщина линии")).toBeInTheDocument();
  });

  it("толщина линий убывает с глубиной автоматически (первая ветка толще второй)", () => {
    open();
    const paths = Array.from(document.querySelectorAll(".mm-edges > path")) as SVGPathElement[];
    const widths = paths.map((p) => Number(p.getAttribute("stroke-width")));
    expect(widths.length).toBe(3);
    expect(Math.max(...widths)).toBeGreaterThan(Math.min(...widths));
  });

  it("связь через «Связать» → клик по второму узлу: пунктирная стрелка, подпись, Del убирает", async () => {
    open();
    fireEvent.click(node("Химия"));
    fireEvent.click(screen.getByText("Связать"));
    fireEvent.click(node("Импеллеры"));
    let saved = await lastSaved();
    expect(saved.links).toHaveLength(1);
    expect(saved.links![0]).toMatchObject({ from: "b", to: "a1" });
    expect(document.querySelectorAll(".mm-link").length).toBe(1);
    // связь выбрана — её панель открыта
    fireEvent.change(screen.getByPlaceholderText("Подпись связи"), { target: { value: "тот же поставщик" } });
    saved = await lastSaved();
    expect(saved.links![0].note).toBe("тот же поставщик");
    fireEvent.keyDown(window, { key: "Delete" });
    saved = await lastSaved();
    expect(saved.links).toHaveLength(0);
  });

  it("повторная связь тех же узлов не создаётся; удаление ветки убирает её связи", async () => {
    const withLink: MindMap = { ...map, data: { ...tree, links: [{ id: "L1", from: "b", to: "a1" }] } };
    render(<MindMapEditor store={makeStore({ mindmaps: [withLink] })} map={withLink} onBack={() => {}} onDeleted={() => {}} />);
    fireEvent.click(node("Импеллеры"));
    fireEvent.click(screen.getByText("Связать"));
    fireEvent.click(node("Химия"));               // обратное направление — уже связаны
    expect(document.querySelectorAll(".mm-link").length).toBe(1);
    fireEvent.click(node("Импеллеры"));
    fireEvent.keyDown(window, { key: "Delete" });  // лист — без подтверждения
    const saved = await lastSaved();
    expect(find(saved, "a1")).toBeNull();
    expect(saved.links).toHaveLength(0);
  });
});
