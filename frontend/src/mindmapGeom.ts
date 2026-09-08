// Геометрия майндмапа — общая для редактора (MindMapEditor.tsx) и экспорта в картинку (mindmapExport.ts).
// Чистые функции без React: раскладка дерева, размеры узлов, толщина линий, кривые веток и связей, операции над деревом.
// v1.4: вынесено из MindMapEditor.tsx, чтобы PNG-экспорт рисовал ровно ту же карту, что видна на экране.
import { DIRECTION_COLORS, MIND_COLOR, MindNode } from "./api";

export type Laid = {
  node: MindNode; depth: number; x: number; y: number; w: number; h: number; side: 1 | -1 | 0;
  color: string; adj: -1 | 0 | 1; parent?: Laid; lines: string[];
};

const FONT = { 0: 18, 1: 14.5, 2: 13.5 } as Record<number, number>;
export const fontFor = (d: number) => FONT[Math.min(d, 2)];
export const PAD_X = 14, PAD_Y = 8, GAP_X = 56, GAP_Y = 10, MAX_CHARS = 28, NOTE_GAP = 48;
/** Палитра веток: цвета направлений + фирменный цвет майндмапов + графит. */
export const PALETTE = [...DIRECTION_COLORS, MIND_COLOR, "#475569"];
export const LINK_COLOR = "#6b7280";
export const PRIORITY_MARK = ["", "!", "!!", "!!!"];
export const PRIORITY_COLOR = ["", "#d97706", "#ea580c", "#a12727"];

/** Толщина линии по глубине: первые ветки толще, дальше тоньше; ручная поправка ×1.6 / ×0.55. */
export function strokeFor(depth: number, adj: -1 | 0 | 1): number {
  const auto = depth <= 1 ? 3.6 : depth === 2 ? 2.5 : depth === 3 ? 1.9 : 1.5;
  return +(auto * (adj === 1 ? 1.6 : adj === -1 ? 0.55 : 1)).toFixed(2);
}

export function wrap(text: string, maxChars: number): string[] {
  const words = (text || " ").split(/\s+/); const lines: string[] = []; let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > maxChars && cur) { lines.push(cur); cur = w; } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [" "];
}
export function measure(text: string, depth: number) {
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

/** Раскладка: корень в (0,0); дети корня делятся на правую и левую стороны так, чтобы высоты были сбалансированы.
 *  Цвет и поправка толщины наследуются вниз по ветке, пока узел не задал свои. */
export function layout(root: MindNode): Laid[] {
  const out: Laid[] = [];
  const m0 = measure(root.text, 0);
  const rootL: Laid = { node: root, depth: 0, x: 0, y: 0, w: m0.w, h: m0.h, side: 0, color: MIND_COLOR, adj: root.width ?? 0, lines: m0.lines };
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
      const color = child.color ?? DIRECTION_COLORS[i % DIRECTION_COLORS.length];
      placeSubtree(child, 1, rootL, side, y + hs[k] / 2, color, child.width ?? rootL.adj);
      y += hs[k] + GAP_Y;
    });
  }
  function placeSubtree(n: MindNode, depth: number, parent: Laid, side: 1 | -1, cy: number, color: string, adj: -1 | 0 | 1) {
    const m = measure(n.text, depth);
    const gap = GAP_X + (n.note ? NOTE_GAP : 0);   // подпись на линии — линия длиннее, чтобы подписи было где лечь
    const x = parent.x + side * (parent.w / 2 + gap + m.w / 2);
    const laid: Laid = { node: n, depth, x, y: cy, w: m.w, h: m.h, side, color, adj, parent, lines: m.lines };
    out.push(laid);
    if (n.collapsed || !n.children.length) return;
    const hs = n.children.map((c) => subtreeHeight(c, depth + 1));
    const sum = hs.reduce((a, b) => a + b, 0) + GAP_Y * (hs.length - 1);
    let y = cy - sum / 2;
    n.children.forEach((c, k) => { placeSubtree(c, depth + 1, laid, side, y + hs[k] / 2, c.color ?? color, c.width ?? adj); y += hs[k] + GAP_Y; });
  }
  place(right, 1); place(left, -1);
  return out;
}

/** Точка на границе узла (прямоугольник со скруглением) в направлении к цели — отсюда начинается стрелка-связь. */
export function anchor(l: Laid, tx: number, ty: number) {
  const dx = tx - l.x, dy = ty - l.y;
  if (!dx && !dy) return { x: l.x, y: l.y };
  const t = Math.min(l.w / 2 / (Math.abs(dx) || 1e-6), l.h / 2 / (Math.abs(dy) || 1e-6));
  return { x: l.x + dx * t, y: l.y + dy * t };
}

/** Концы ветки: от края родителя до края ребёнка. */
export const edgeEnds = (c: Laid) => {
  const p = c.parent!;
  return { x1: p.x + c.side * p.w / 2, y1: p.y, x2: c.x - c.side * c.w / 2, y2: c.y };
};
export const edgePath = (c: Laid) => {
  const { x1, y1, x2, y2 } = edgeEnds(c);
  const dx = (x2 - x1) / 2;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
};

/** Связь: дуга от границы одного узла к границе другого с небольшим прогибом, чтобы не сливаться с ветками; стрелка на конце.
 *  Возвращает и SVG-пути (редактор), и точки (canvas-экспорт). */
export function linkGeom(a: Laid, b: Laid) {
  const p0 = anchor(a, b.x, b.y), p2 = anchor(b, a.x, a.y);
  const mx = (p0.x + p2.x) / 2, my = (p0.y + p2.y) / 2;
  const dx = p2.x - p0.x, dy = p2.y - p0.y, len = Math.hypot(dx, dy) || 1;
  const bow = Math.min(60, len * 0.18);
  const c = { x: mx - dy / len * bow, y: my + dx / len * bow };
  const mid = { x: (p0.x + 2 * c.x + p2.x) / 4, y: (p0.y + 2 * c.y + p2.y) / 4 };
  const tx = p2.x - c.x, ty = p2.y - c.y, tl = Math.hypot(tx, ty) || 1, ux = tx / tl, uy = ty / tl;
  const s = 9;
  const headPts = [
    { x: p2.x, y: p2.y },
    { x: p2.x - ux * s - uy * s * 0.5, y: p2.y - uy * s + ux * s * 0.5 },
    { x: p2.x - ux * s + uy * s * 0.5, y: p2.y - uy * s - ux * s * 0.5 },
  ];
  const head = `M ${headPts[0].x} ${headPts[0].y} L ${headPts[1].x} ${headPts[1].y} L ${headPts[2].x} ${headPts[2].y} Z`;
  return { d: `M ${p0.x} ${p0.y} Q ${c.x} ${c.y} ${p2.x} ${p2.y}`, head, mid, p0, p2, c, headPts };
}

/* ---------- операции над деревом (иммутабельно) ---------- */
export function mapTree(n: MindNode, f: (n: MindNode) => MindNode): MindNode {
  return f({ ...n, children: n.children.map((c) => mapTree(c, f)) });
}
export function findParent(root: MindNode, id: string): MindNode | null {
  for (const c of root.children) { if (c.id === id) return root; const r = findParent(c, id); if (r) return r; }
  return null;
}
export function findNode(root: MindNode, id: string): MindNode | null {
  if (root.id === id) return root;
  for (const c of root.children) { const r = findNode(c, id); if (r) return r; }
  return null;
}
export function countAll(n: MindNode): number { return n.children.reduce((s, c) => s + countAll(c), 1); }
export function idsOf(n: MindNode, acc: Set<string> = new Set()): Set<string> { acc.add(n.id); n.children.forEach((c) => idsOf(c, acc)); return acc; }
