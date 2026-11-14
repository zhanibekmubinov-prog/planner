// v1.8 — совместная работа над майндмапом: операции над узлами, живой канал, «кто на карте», только просмотр.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MindMap, MindNode, MindOp } from "../api";
import MindMapEditor from "../MindMapEditor";
import { applyOps, enqueue } from "../mindmapOps";
import { makeStore } from "./fixtures";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => []), put: vi.fn(), post: vi.fn(), del: vi.fn() };
});
import { post } from "../api";
const postMock = vi.mocked(post) as unknown as ReturnType<typeof vi.fn<(path: string, body: { batch: string; ops: MindOp[] }) => Promise<unknown>>>;

const tree: MindNode = { id: "root", text: "ГРП", children: [
  { id: "a", text: "Насосы", children: [{ id: "a1", text: "Импеллеры", children: [] }] },
  { id: "b", text: "Химия", children: [] },
] };
const doc = { tree, title: "ГРП" };
const ids = (n: MindNode): string[] => [n.id, ...n.children.flatMap(ids)];

describe("applyOps — то же, что на сервере", () => {
  it("добавить, поменять поля, убрать ветку вместе со связями", () => {
    let d = applyOps(doc, [
      { type: "add", parent: "b", node: { id: "b1", text: "Гуар" } },
      { type: "set", id: "a", fields: { priority: 2, color: "#DC2626" } },
      { type: "link_add", link: { id: "L", from: "b1", to: "a1" } },
    ]);
    expect(ids(d.tree)).toEqual(["root", "a", "a1", "b", "b1"]);
    expect(d.tree.children[0]).toMatchObject({ priority: 2, color: "#DC2626" });
    d = applyOps(d, [{ type: "remove", id: "a" }, { type: "set", id: "b", fields: { color: null } }]);
    expect(ids(d.tree)).toEqual(["root", "b", "b1"]);
    expect(d.tree.links).toEqual([]);
    expect(tree.children).toHaveLength(2);   // исходник не тронут
  });

  it("устаревшие операции пропускаются, повтор пачки ничего не меняет", () => {
    const batch: MindOp[] = [{ type: "add", parent: "root", node: { id: "c", text: "Логистика" } }, { type: "remove", id: "a1" }];
    const once = applyOps(doc, batch);
    expect(applyOps(once, batch)).toEqual(once);
    const stale = applyOps(once, [{ type: "set", id: "a1", fields: { text: "поздно" } }, { type: "move", id: "a", parent: "a" }, { type: "remove", id: "root" }]);
    expect(stale).toEqual(once);
  });

  it("очередь склеивает набор текста одного узла в одну правку", () => {
    let q: MindOp[] = [];
    for (const t of ["Н", "На", "Нас"]) q = enqueue(q, [{ type: "set", id: "a", fields: { text: t } }]);
    q = enqueue(q, [{ type: "set", id: "b", fields: { text: "Х" } }]);
    expect(q).toEqual([{ type: "set", id: "a", fields: { text: "Нас" } }, { type: "set", id: "b", fields: { text: "Х" } }]);
  });
});

/* ---------- редактор с живым каналом ---------- */

class FakeWS {
  static all: FakeWS[] = [];
  readyState = 0; sent: Record<string, unknown>[] = [];   // как у настоящего: CONNECTING, потом OPEN
  onopen: (() => void) | null = null; onmessage: ((e: { data: string }) => void) | null = null; onclose: ((e: { code: number }) => void) | null = null;
  constructor(public url: string) { FakeWS.all.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0); }
  send(d: string) { this.sent.push(JSON.parse(d)); }
  close() { this.readyState = 3; }
  emit(msg: Record<string, unknown>) { act(() => { this.onmessage?.({ data: JSON.stringify(msg) }); }); }
}

const base: MindMap = { id: 7, title: "ГРП", data: tree, created_at: "2026-11-14T00:00:00Z", updated_at: "2026-11-14T00:00:00Z", version: 3 };
const node = (text: string) => screen.getByText(text).closest("[data-node]") as HTMLElement;
const me = { id: 1, email: "me@cis.kz", name: "Жанибек Мубинов", is_admin: false, digest_enabled: false };
const nur = { sid: "s2", user_id: 2, name: "Нурлан Абильханов", color: "#7C3AED", node: null, editing: false };

function open(map: MindMap = base) {
  render(<MindMapEditor store={makeStore({ mindmaps: [map], me })} map={map} onBack={() => {}} onDeleted={() => {}} />);
}
async function connected() {
  await waitFor(() => expect(FakeWS.all.length).toBe(1));
  const ws = FakeWS.all[0];
  await waitFor(() => expect(ws.sent[0]).toEqual({ type: "auth", token: "session-token" }));
  ws.emit({ type: "hello", sid: "s1", version: 3, access: "owner", peers: [{ ...nur, sid: "s1", user_id: 1, name: me.name, color: "#2F6FED" }] });
  return ws;
}

beforeEach(() => {
  FakeWS.all = [];
  vi.stubGlobal("WebSocket", FakeWS);
  localStorage.setItem("planner.session", "session-token");
  postMock.mockReset();
});
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe("Майндмап v1.8 — вместе", () => {
  it("правка коллеги из живого канала появляется на карте без перезагрузки", async () => {
    open();
    const ws = await connected();
    expect(ws.url).toMatch(/^ws:\/\/.+\/api\/mindmaps\/7\/live$/);
    ws.emit({ type: "ops", version: 4, batch: "x", by: { id: 2, name: nur.name }, title: "ГРП",
              ops: [{ type: "add", parent: "b", node: { id: "b1", text: "Гуар от Нурлана" } }] });
    expect(screen.getByText("Гуар от Нурлана")).toBeInTheDocument();
    // пропуск номера правки — карта перечитывается целиком, а не склеивается наугад
    const { api } = await import("../api");
    vi.mocked(api).mockResolvedValueOnce({ ...base, version: 9, data: { ...tree, children: [] } } as never);
    ws.emit({ type: "ops", version: 7, batch: "y", by: { id: 2, name: nur.name }, title: "ГРП", ops: [] });
    await waitFor(() => expect(screen.queryByText("Насосы")).toBeNull());
  });

  it("узел, выбранный коллегой, — в рамке его цвета с именем; вверху кружки тех, кто на карте", async () => {
    open();
    const ws = await connected();
    ws.emit({ type: "presence", peers: [{ ...nur, sid: "s1", user_id: 1, name: me.name, color: "#2F6FED" }, { ...nur, node: "a", editing: true }] });
    const a = node("Насосы");
    expect(a).toHaveClass("peer");
    expect(a.style.getPropertyValue("--peer")).toBe("#7C3AED");
    expect(a).toHaveTextContent("Нурлан · печатает…");
    expect(screen.getByLabelText("Сейчас на карте").textContent).toBe("ЖМНА");
    // мой выбор уходит коллегам
    fireEvent.click(node("Химия"));
    await waitFor(() => expect(ws.sent).toContainEqual({ type: "focus", node: "b", editing: false }));
  });

  it("нет связи — правка не теряется: повтор той же пачкой, потом «сохранено»", async () => {
    let fail = true;
    postMock.mockImplementation(async (_p, body) => {
      if (fail) { fail = false; throw new TypeError("Failed to fetch"); }
      const d = applyOps(doc, body.ops);
      return { version: 4, title: d.title, data: d.tree, applied: body.ops.length, skipped: [] };
    });
    open();
    fireEvent.click(node("Насосы"));
    fireEvent.keyDown(window, { key: "3" });
    await waitFor(() => expect(screen.getByText("нет связи — повторю")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("сохранено")).toBeInTheDocument(), { timeout: 3000 });
    expect(postMock).toHaveBeenCalledTimes(2);
    expect(postMock.mock.calls[1][1].ops).toEqual([{ type: "set", id: "a", fields: { priority: 3 } }]);
    expect(screen.getByLabelText("Важность 3 из 3")).toBeInTheDocument();
  });

  it("только просмотр: ничего не правится и не отправляется, свернуть можно у себя", async () => {
    open({ ...base, access: "view", owner: { id: 9, name: "Аида", email: "aida@cis.kz" } as never });
    expect(screen.getByText("только просмотр")).toBeInTheDocument();
    expect(screen.getByText("карта: Аида")).toBeInTheDocument();
    expect(screen.queryByText("Удалить")).toBeNull();
    expect(screen.queryByText(/Поделиться/)).toBeNull();
    fireEvent.click(node("Насосы"));
    expect(screen.queryByTitle("Добавить подпункт (Tab)")).toBeNull();
    expect(screen.queryByRole("toolbar", { name: "Настройки узла" })).toBeNull();
    fireEvent.keyDown(window, { key: "Tab" });
    fireEvent.keyDown(window, { key: "Delete" });
    fireEvent.doubleClick(node("Насосы"));
    expect(document.querySelector(".mm-input")).toBeNull();
    fireEvent.keyDown(window, { key: " " });   // свернуть — только у себя
    expect(screen.queryByText("Импеллеры")).toBeNull();
    await new Promise((r) => setTimeout(r, 400));
    expect(postMock).not.toHaveBeenCalled();
  });

  it("владелец видит «Поделиться» — окно открывается на саму карту", async () => {
    const { api } = await import("../api");
    vi.mocked(api).mockResolvedValue([] as never);
    open({ ...base, access: "owner" });
    fireEvent.click(screen.getByText(/Поделиться/));
    expect(await screen.findByRole("dialog", { name: "Поделиться" })).toHaveTextContent("Открывается только эта карта");
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/shares?entity_type=mindmap&entity_id=7"));
  });
});
