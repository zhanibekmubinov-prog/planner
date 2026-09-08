// v1.4 — экспорт майндмапа: текст-структура (Markdown) и картинка PNG.
// Симптом владельца: «сделал майндмап, хочу показать его Claude — а экспорта нет». Проверяем, что уходит в буфер / в файл.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MindMap, MindNode } from "../api";
import MindMapEditor from "../MindMapEditor";
import { fileName, toMarkdown } from "../mindmapExport";
import { makeStore } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(async (_p: string, b: unknown) => b), post: vi.fn(), del: vi.fn() };
});

const tree: MindNode = {
  id: "root", text: "ГРП", children: [
    { id: "a", text: "Насосы", priority: 2, children: [{ id: "a1", text: "Импеллеры", note: "критично", children: [] }] },
    { id: "b", text: "Химия", collapsed: true, children: [{ id: "b1", text: "Гуар", children: [] }] },
  ],
  links: [{ id: "L1", from: "b", to: "a1", note: "зависит от" }, { id: "L2", from: "b", to: "нет-такого" }],
};
const map: MindMap = { id: 7, title: "ГРП", data: tree, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
const NOW = new Date(2026, 8, 8);

describe("toMarkdown", () => {
  it("даёт всё дерево (свёрнутые ветки тоже), важность, подписи линий и связи; висячие связи пропускает", () => {
    const md = toMarkdown(map, { direction: "Снабжение", now: NOW });
    expect(md).toBe([
      "# ГРП",
      "_Направление: Снабжение · Майндмап из CIS Planner, 08.09.2026_",
      "",
      "- Насосы (!!)",
      "  - Импеллеры [линия: критично]",
      "- Химия",
      "  - Гуар",
      "",
      "## Связи между узлами",
      "- Химия → Импеллеры: зависит от",
      "",
      "_(!) (!!) (!!!) — важность узла; [линия: …] — подпись на линии от родительского узла; → — связь-стрелка между узлами._",
      "",
    ].join("\n"));
  });

  it("пустая карта и карта без оформления — без легенды и без раздела связей", () => {
    const empty: MindMap = { ...map, title: "Пусто", data: { id: "root", text: "Пусто", children: [] } };
    const md = toMarkdown(empty, { now: NOW });
    expect(md).toContain("_(карта пока пустая)_");
    expect(md).not.toContain("##");
    expect(md).not.toContain("важность");
    const plain: MindMap = { ...map, data: { id: "root", text: "ГРП", children: [{ id: "x", text: "Один", children: [] }] } };
    expect(toMarkdown(plain, { now: NOW }).trim().split("\n").at(-1)).toBe("- Один");
  });

  it("имя файла без запрещённых символов", () => {
    expect(fileName('План: "ГРП" / 2026?', "md")).toBe("План ГРП 2026.md");
    expect(fileName("", "png")).toBe("Майндмап.png");
  });
});

describe("Кнопка «Экспорт…» в редакторе", () => {
  const writeText = vi.fn(async () => {});
  let downloads: { name: string; type: string }[] = [];
  beforeEach(() => {
    downloads = [];
    Object.assign(navigator, { clipboard: { writeText } });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { downloads.push({ name: "", type: b.type }); return "blob:x"; }), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads[downloads.length - 1].name = this.download; });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  const open = () => render(<MindMapEditor store={makeStore({ mindmaps: [map] })} map={map} onBack={() => {}} onDeleted={() => {}} />);

  it("«Скопировать структуру» кладёт Markdown в буфер обмена", async () => {
    open();
    fireEvent.click(screen.getByText("Экспорт…"));
    fireEvent.click(screen.getByRole("menuitem", { name: /Скопировать структуру/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const md = writeText.mock.calls[0][0] as unknown as string;
    expect(md.startsWith("# ГРП\n")).toBe(true);
    expect(md).toContain("- Насосы (!!)\n  - Импеллеры [линия: критично]");
    expect(screen.queryByRole("menu")).toBeNull();   // меню закрылось
  });

  it("«Скачать структуру» отдаёт файл ГРП.md", async () => {
    open();
    fireEvent.click(screen.getByText("Экспорт…"));
    fireEvent.click(screen.getByRole("menuitem", { name: /файл \.md/ }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0]).toEqual({ name: "ГРП.md", type: "text/markdown;charset=utf-8" });
  });

  it("PNG без canvas (jsdom) — понятная ошибка в плашке, а не молчание", async () => {
    const store = makeStore({ mindmaps: [map] });
    render(<MindMapEditor store={store} map={map} onBack={() => {}} onDeleted={() => {}} />);
    fireEvent.click(screen.getByText("Экспорт…"));
    fireEvent.click(screen.getByRole("menuitem", { name: /PNG/ }));
    await waitFor(() => expect(store.setError).toHaveBeenCalled());
    expect(String((store.setError as ReturnType<typeof vi.fn>).mock.calls[0][0])).toMatch(/картинк/i);
    expect(downloads).toHaveLength(0);
  });
});

describe("Открытие карты (v1.4.1)", () => {
  // jsdom не считает размеры — подставляем область 800×500 и смотрим, какой масштаб выбрал редактор
  const size = (w: number, h: number) => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get() { return (this as HTMLElement).classList?.contains("mm-area") ? w : 0; } });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get() { return (this as HTMLElement).classList?.contains("mm-area") ? h : 0; } });
  };
  afterEach(() => { delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth; delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight; });
  const scaleOf = () => Number(/scale\(([\d.]+)\)/.exec((document.querySelector(".mm-layer") as HTMLElement).style.transform)?.[1]);

  it("большая карта при открытии уменьшается, чтобы влезть целиком", () => {
    size(800, 500);
    const big: MindNode = { id: "root", text: "ПТО ГРП", children: Array.from({ length: 14 }, (_, i) => ({
      id: `n${i}`, text: `Может заменять мастера в его отсутствие и вести журнал ${i}`,
      children: [{ id: `n${i}a`, text: "Проверка оборудования перед выездом на куст", children: [] }],
    })) };
    render(<MindMapEditor store={makeStore()} map={{ ...map, data: big }} onBack={() => {}} onDeleted={() => {}} />);
    const k = scaleOf();
    expect(k).toBeLessThan(0.8); expect(k).toBeGreaterThanOrEqual(0.3);
    expect(screen.getByText(/%$/).textContent).toBe(`${Math.round(k * 100)}%`);
  });

  it("маленькая карта не увеличивается больше 100%", () => {
    size(1600, 900);
    render(<MindMapEditor store={makeStore()} map={map} onBack={() => {}} onDeleted={() => {}} />);
    expect(scaleOf()).toBe(1);
  });
});
