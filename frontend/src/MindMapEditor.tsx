// Редактор майндмапа в духе MindNode: центральная тема, автоматическая раскладка влево/вправо,
// плавные ветви, цвет ветви первого уровня наследуется потомками. Автосохранение.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { del, DIRECTION_COLORS, dirColor, MIND_COLOR, MindMap, MindMapIn, MindNode, newNodeId, put } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

type Props = { store: Store; map: MindMap; onBack: () => void; onDeleted: () => void; onOpenTask?: (taskId: number) => void };

/* ---------- геометрия ---------- */
type Laid = { node: MindNode; depth: number; x: number; y: number; w: number; h: number; side: 1 | -1 | 0; color: string; parent?: Laid; lines: string[] };

const FONT = { 0: 18, 1: 14.5, 2: 13.5 } as Record<number, number>;
const fontFor = (d: number) => FONT[Math.min(d, 2)];
const PAD_X = 14, PAD_Y = 8, GAP_X = 56, GAP_Y = 10, MAX_CHARS = 28;

function wrap(text: string, maxChars: number): string[] {
  const words = (text || " ").split(/\s+/); const lines: string[] = []; let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > maxChars && cur) { lines.push(cur); cur = w; } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [" "];
}
function measure(text: string, depth: number) {
  const fs = fontFor(depth); const lines = wrap(text, depth === 0 ? 22 : MAX_CHARS);
  const w = Math.max(...lines.map((l) => l.length)) * fs * 0.62 + PAD_X * 2;
  const h = lines.length * fs * 1.3 + PAD_Y * 2;
  return { w: Math.max(w, depth === 0 ? 120 : 48), h, lines };
}

function subtreeHeight(n: MindNode, depth: number): number {
  const own = measure(n.text, depth).h;
  if (n.collapsed || !n.children.length) return own;
  const kids = n.children.reduce((s, c) => s + subtreeHeight(c, depth + 1), 0) + GAP_Y * (n.children.length - 1);
  return Math.max(own, kids);
}

/** Раскладка: корень в (0,0); дети корня делятся на правую и левую стороны так, чтобы высоты были сбалансированы. */
function layout(root: MindNode): Laid[] {
  const out: Laid[] = [];
  const m0 = measure(root.text, 0);
  const rootL: Laid = { node: root, depth: 0, x: 0, y: 0, w: m0.w, h: m0.h, side: 0, color: MIND_COLOR, lines: m0.lines };
  out.push(rootL);
  if (root.collapsed) return out;
  const kids = root.children;
  const heights = kids.map((k) => subtreeHeight(k, 1));
  const total = heights.reduce((a, b) => a + b, 0);
  const right: number[] = [], left: number[] = []; let acc = 0;
  kids.forEach((_, i) => { (acc < total / 2 ? right : left).push(i); acc += heights[i]; });

  function place(indices: number[], side: 1 | -1) {
    const hs = indices.map((i) => heights[i]);
    const sum = hs.reduce((a, b) => a + b, 0) + GAP_Y * Math.max(0, hs.length - 1);
    let y = -sum / 2;
    indices.forEach((i, k) => {
      const child = kids[i];
      const color = DIRECTION_COLORS[i % DIRECTION_COLORS.length];
      placeSubtree(child, 1, rootL, side, y + hs[k] / 2, color);
      y += hs[k] + GAP_Y;
    });
  }
  function placeSubtree(n: MindNode, depth: number, parent: Laid, side: 1 | -1, cy: number, color: string) {
    const m = measure(n.text, depth);
    const x = parent.x + side * (parent.w / 2 + GAP_X + m.w / 2);
    const laid: Laid = { node: n, depth, x, y: cy, w: m.w, h: m.h, side, color, parent, lines: m.lines };
    out.push(laid);
    if (n.collapsed || !n.children.length) return;
    const hs = n.children.map((c) => subtreeHeight(c, depth + 1));
    const sum = hs.reduce((a, b) => a + b, 0) + GAP_Y * (hs.length - 1);
    let y = cy - sum / 2;
    n.children.forEach((c, k) => { placeSubtree(c, depth + 1, laid, side, y + hs[k] / 2, color); y += hs[k] + GAP_Y; });
  }
  place(right, 1); place(left, -1);
  return out;
}

/* ---------- операции над деревом (иммутабельно) ---------- */
function mapTree(n: MindNode, f: (n: MindNode) => MindNode): MindNode {
  return f({ ...n, children: n.children.map((c) => mapTree(c, f)) });
}
function findParent(root: MindNode, id: string): MindNode | null {
  for (const c of root.children) { if (c.id === id) return root; const r = findParent(c, id); if (r) return r; }
  return null;
}
function findNode(root: MindNode, id: string): MindNode | null {
  if (root.id === id) return root;
  for (const c of root.children) { const r = findNode(c, id); if (r) return r; }
  return null;
}
function countAll(n: MindNode): number { return n.children.reduce((s, c) => s + countAll(c), 1); }

/* ---------- компонент ---------- */
export default function MindMapEditor({ store, map, onBack, onDeleted, onOpenTask }: Props) {
  const [tree, setTree] = useState<MindNode>(map.data?.id ? map.data : { id: "root", text: map.title, children: [] });
  const [title, setTitle] = useState(map.title);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [dragging, setDragging] = useState<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const areaRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const confirm = useConfirm();

  const laid = useMemo(() => layout(tree), [tree]);
  const byId = useMemo(() => new Map(laid.map((l) => [l.node.id, l])), [laid]);
  const direction = map.direction_id ? store.directions.find((d) => d.id === map.direction_id) : undefined;
  const task = map.task_id ? store.tasks.find((t) => t.id === map.task_id) : undefined;

  // центрировать при открытии
  useEffect(() => {
    const el = areaRef.current; if (!el) return;
    setView({ x: el.clientWidth / 2, y: el.clientHeight / 2, k: 1 });
  }, [map.id]);

  const commit = useCallback((next: MindNode, nextTitle?: string) => {
    setTree(next); if (nextTitle !== undefined) setTitle(nextTitle); setDirty(true);
  }, []);

  // автосохранение
  useEffect(() => {
    if (!dirty) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setSaving(true);
      try {
        const body: MindMapIn = { title: title.trim() || tree.text || "Майндмап", direction_id: map.direction_id ?? null, task_id: map.task_id ?? null, data: tree };
        store.patchMindmap(await put<MindMap>(`/mindmaps/${map.id}`, body));
        setDirty(false);
      } catch (e) { store.setError(String(e)); } finally { setSaving(false); }
    }, 800);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [tree, title, dirty, map.id, map.direction_id, map.task_id, store]);

  /* --- редактирование --- */
  function addChild(parentId: string) {
    const id = newNodeId();
    commit(mapTree(tree, (n) => (n.id === parentId ? { ...n, collapsed: false, children: [...n.children, { id, text: "", children: [] }] } : n)));
    setSelected(id); setEditing(id);
  }
  function addSibling(id: string) {
    const parent = findParent(tree, id); if (!parent) { addChild(id); return; }
    const nid = newNodeId();
    commit(mapTree(tree, (n) => {
      if (n.id !== parent.id) return n;
      const i = n.children.findIndex((c) => c.id === id);
      const kids = [...n.children]; kids.splice(i + 1, 0, { id: nid, text: "", children: [] });
      return { ...n, children: kids };
    }));
    setSelected(nid); setEditing(nid);
  }
  async function removeNode(id: string) {
    if (id === tree.id) return;
    const node = findNode(tree, id); if (!node) return;
    const n = countAll(node) - 1;
    if (n > 0 && !(await confirm(`Удалить узел «${node.text || "…"}» и ${n} вложенных?`, { danger: true, okLabel: "Удалить ветку" }))) return;
    const parent = findParent(tree, id);
    commit(mapTree(tree, (x) => (x.id === parent?.id ? { ...x, children: x.children.filter((c) => c.id !== id) } : x)));
    setSelected(parent?.id ?? null); setEditing(null);
  }
  function setText(id: string, text: string) {
    commit(mapTree(tree, (n) => (n.id === id ? { ...n, text } : n)), id === tree.id ? text : undefined);
  }
  function toggleCollapse(id: string) {
    commit(mapTree(tree, (n) => (n.id === id ? { ...n, collapsed: !n.collapsed } : n)));
  }
  function finishEdit(id: string) {
    setEditing(null);
    const node = findNode(tree, id);
    if (node && !node.text.trim() && id !== tree.id) {
      // пустой новый узел — убираем
      const parent = findParent(tree, id);
      commit(mapTree(tree, (x) => (x.id === parent?.id ? { ...x, children: x.children.filter((c) => c.id !== id) } : x)));
      setSelected(parent?.id ?? null);
    }
  }

  // клавиатура
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editing) return; // в режиме ввода — свои обработчики
      if (!selected) { if (e.key === "Escape") onBack(); return; }
      if (e.key === "Tab") { e.preventDefault(); addChild(selected); }
      else if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey || selected === tree.id) setEditing(selected); else addSibling(selected); }
      else if (e.key === "F2") { e.preventDefault(); setEditing(selected); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); void removeNode(selected); }
      else if (e.key === " ") { e.preventDefault(); toggleCollapse(selected); }
      else if (e.key === "Escape") { setSelected(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  /* --- панорама и масштаб --- */
  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    const el = areaRef.current!; const r = el.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    setView((v) => {
      const k = Math.min(2.5, Math.max(0.3, v.k * factor));
      return { k, x: mx - (mx - v.x) * (k / v.k), y: my - (my - v.y) * (k / v.k) };
    });
  }
  function fit() {
    const el = areaRef.current; if (!el || !laid.length) return;
    const minX = Math.min(...laid.map((l) => l.x - l.w / 2)), maxX = Math.max(...laid.map((l) => l.x + l.w / 2));
    const minY = Math.min(...laid.map((l) => l.y - l.h / 2)), maxY = Math.max(...laid.map((l) => l.y + l.h / 2));
    const k = Math.min(2, Math.max(0.3, Math.min((el.clientWidth - 80) / (maxX - minX || 1), (el.clientHeight - 80) / (maxY - minY || 1))));
    setView({ k, x: el.clientWidth / 2 - ((minX + maxX) / 2) * k, y: el.clientHeight / 2 - ((minY + maxY) / 2) * k });
  }

  async function relink(directionId: number | null) {
    try {
      const body: MindMapIn = { title: title.trim() || tree.text || "Майндмап", direction_id: directionId, task_id: map.task_id ?? null, data: tree };
      store.patchMindmap(await put<MindMap>(`/mindmaps/${map.id}`, body));
    } catch (e) { store.setError(String(e)); }
  }

  async function removeMap() {
    if (!(await confirm(`Майндмап «${title}» будет удалён целиком.`, { danger: true, okLabel: "Удалить майндмап" }))) return;
    try { await del(`/mindmaps/${map.id}`); await store.reloadMindmaps(); onDeleted(); } catch (e) { store.setError(String(e)); }
  }

  const edgePath = (c: Laid) => {
    const p = c.parent!;
    const x1 = p.x + c.side * p.w / 2, y1 = p.y, x2 = c.x - c.side * c.w / 2, y2 = c.y;
    const dx = (x2 - x1) / 2;
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };

  return (
    <div className="mm" style={{ ["--mind" as string]: MIND_COLOR }}>
      <div className="mm-bar">
        <button className="btn ghost" onClick={onBack}>← Назад</button>
        <span className="mm-glyph" aria-hidden="true" />
        <input className="mm-title" value={title} onChange={(e) => { setTitle(e.target.value); setDirty(true); }} placeholder="Название майндмапа" />
        <label className="mm-dir" title="Направление майндмапа">
          <span className="dot" style={{ background: direction ? dirColor(direction) : "var(--line-strong)" }} />
          <select className="select" value={map.direction_id ?? ""} onChange={(e) => void relink(e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">Без направления</option>
            {store.directions.filter((d) => d.status !== "archived" || d.id === map.direction_id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        {task && <button className="tag mm-tasklink" onClick={() => onOpenTask?.(task.id)} title="Открыть задачу">задача: {task.title}</button>}
        <span className="saving">{saving ? "сохраняю…" : dirty ? "изменено" : "сохранено"}</span>
        <span className="spacer" />
        <div className="mm-zoom">
          <button className="btn ghost sm" onClick={() => setView((v) => ({ ...v, k: Math.max(0.3, v.k / 1.2) }))} aria-label="Уменьшить">−</button>
          <span className="mono">{Math.round(view.k * 100)}%</span>
          <button className="btn ghost sm" onClick={() => setView((v) => ({ ...v, k: Math.min(2.5, v.k * 1.2) }))} aria-label="Увеличить">+</button>
          <button className="btn ghost sm" onClick={fit}>Вписать</button>
        </div>
        <button className="btn danger sm" onClick={removeMap}>Удалить</button>
      </div>

      <div
        ref={areaRef} className={`mm-area ${dragging ? "dragging" : ""}`}
        onWheel={onWheel}
        onMouseDown={(e) => { if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains("mm-layer")) { setDragging({ sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y }); setSelected(null); setEditing(null); } }}
        onMouseMove={(e) => { if (dragging) setView((v) => ({ ...v, x: dragging.ox + e.clientX - dragging.sx, y: dragging.oy + e.clientY - dragging.sy })); }}
        onMouseUp={() => setDragging(null)} onMouseLeave={() => setDragging(null)}
      >
        <div className="mm-layer" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
          <svg className="mm-edges" style={{ overflow: "visible" }}>
            {laid.filter((l) => l.parent).map((l) => (
              <path key={l.node.id} d={edgePath(l)} stroke={l.color} strokeWidth={l.depth === 1 ? 3.5 : 2.2} fill="none" strokeLinecap="round" opacity={0.9} />
            ))}
          </svg>
          {laid.map((l) => {
            const isSel = selected === l.node.id, isEdit = editing === l.node.id;
            const hidden = l.node.collapsed && l.node.children.length > 0;
            return (
              <div
                key={l.node.id}
                className={`mm-node d${Math.min(l.depth, 2)} ${isSel ? "sel" : ""} ${hidden ? "collapsed" : ""} ${isEdit ? "editing" : ""}`}
                style={(() => {
                  // В режиме ввода узел шире — растёт в сторону от родителя, чтобы не наезжать на него
                  const w = isEdit ? Math.max(l.w, 240) : l.w;
                  const left = !isEdit || l.side === 0 ? l.x - w / 2 : l.side === 1 ? l.x - l.w / 2 : l.x + l.w / 2 - w;
                  return { left, top: l.y - l.h / 2, width: w, minHeight: l.h, ["--c" as string]: l.color, fontSize: fontFor(l.depth) };
                })()}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); setSelected(l.node.id); }}
                onDoubleClick={(e) => { e.stopPropagation(); setSelected(l.node.id); setEditing(l.node.id); }}
              >
                {isEdit ? (
                  <textarea
                    autoFocus className="mm-input" value={l.node.text} rows={1}
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => setText(l.node.id, e.target.value.replace(/\n/g, " "))}
                    onBlur={() => finishEdit(l.node.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); finishEdit(l.node.id); if (l.node.text.trim() && !e.shiftKey && l.node.id !== tree.id) setTimeout(() => addSibling(l.node.id), 0); }
                      if (e.key === "Tab") { e.preventDefault(); finishEdit(l.node.id); if (l.node.text.trim()) setTimeout(() => addChild(l.node.id), 0); }
                      if (e.key === "Escape") { e.preventDefault(); finishEdit(l.node.id); }
                    }}
                  />
                ) : (
                  <span className="mm-text">{l.lines.join("\n")}</span>
                )}
                {hidden && <button className="mm-count" title="Развернуть" onClick={(e) => { e.stopPropagation(); toggleCollapse(l.node.id); }}>{countAll(l.node) - 1}</button>}
                {isSel && !isEdit && (
                  <>
                    <button className={`mm-add ${l.side === -1 ? "left" : "right"}`} title="Добавить подпункт (Tab)" onClick={(e) => { e.stopPropagation(); addChild(l.node.id); }}>+</button>
                    {l.node.children.length > 0 && !hidden && (
                      <button className={`mm-fold ${l.side === -1 ? "left" : "right"}`} title="Свернуть (пробел)" onClick={(e) => { e.stopPropagation(); toggleCollapse(l.node.id); }}>–</button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
        <div className="mm-help">
          <span><kbd>Tab</kbd> подпункт</span><span><kbd>Enter</kbd> соседний</span><span><kbd>F2</kbd> / двойной клик — текст</span>
          <span><kbd>Del</kbd> удалить</span><span><kbd>Пробел</kbd> свернуть</span><span>колёсико — масштаб, тянуть фон — сдвиг</span>
        </div>
      </div>
    </div>
  );
}
