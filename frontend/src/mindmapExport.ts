// Экспорт майндмапа (v1.4): текст-структура (Markdown) — чтобы отдать Claude или вставить в документ,
// и картинка PNG — та же карта, что на экране, нарисованная на canvas (шрифты страницы, цвета темы).
// Чистые функции без React; кнопка «Экспорт…» живёт в MindMapEditor.tsx.
import { MindLink, MindMap, MindNode, MIND_COLOR } from "./api";
import { edgeEnds, findNode, fontFor, Laid, layout, LINK_COLOR, linkGeom, PRIORITY_COLOR, PRIORITY_MARK, strokeFor } from "./mindmapGeom";

export type ExportContext = { direction?: string | null; task?: string | null; now?: Date };

const fmtDay = (d: Date) => `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;

/* ---------- Markdown ---------- */

/** Дерево целиком (свёрнутые ветки тоже), одна строка — один узел: «- Текст (!!) [линия: подпись]».
 *  Связи между узлами — отдельным списком внизу; в конце — пояснение обозначений, если они встретились. */
export function toMarkdown(map: MindMap, ctx: ExportContext = {}): string {
  const root = map.data?.id ? map.data : { id: "root", text: map.title, children: [] as MindNode[] };
  const title = (map.title || root.text || "Майндмап").trim();
  const out: string[] = [`# ${title}`];
  const meta: string[] = [];
  if (ctx.direction) meta.push(`Направление: ${ctx.direction}`);
  if (ctx.task) meta.push(`Задача: ${ctx.task}`);
  meta.push(`Майндмап из CIS Planner, ${fmtDay(ctx.now ?? new Date())}`);
  out.push(`_${meta.join(" · ")}_`, "");

  let usedPrio = false, usedNote = false;
  const line = (n: MindNode, depth: number) => {
    let s = `${"  ".repeat(depth)}- ${(n.text || "…").trim()}`;
    if (n.priority) { s += ` (${PRIORITY_MARK[n.priority]})`; usedPrio = true; }
    if (n.note && depth > 0) { s += ` [линия: ${n.note.trim()}]`; usedNote = true; }
    out.push(s);
    n.children.forEach((c) => line(c, depth + 1));
  };
  if (root.text.trim() && root.text.trim() !== title) out.push(`Центральная тема: ${root.text.trim()}`, "");
  root.children.forEach((c) => line(c, 0));
  if (!root.children.length) out.push("_(карта пока пустая)_");

  const links = (root.links ?? []).filter((l) => findNode(root, l.from) && findNode(root, l.to));
  if (links.length) {
    out.push("", "## Связи между узлами");
    for (const l of links) {
      const a = findNode(root, l.from)!, b = findNode(root, l.to)!;
      out.push(`- ${a.text.trim() || "…"} → ${b.text.trim() || "…"}${l.note ? `: ${l.note.trim()}` : ""}`);
    }
  }
  const legend: string[] = [];
  if (usedPrio) legend.push("(!) (!!) (!!!) — важность узла");
  if (usedNote) legend.push("[линия: …] — подпись на линии от родительского узла");
  if (links.length) legend.push("→ — связь-стрелка между узлами");
  if (legend.length) out.push("", `_${legend.join("; ")}._`);
  return out.join("\n") + "\n";
}

/* ---------- PNG ---------- */

type Theme = { bg: string; surface: string; text: string; text2: string; text3: string; font: string; display: string; mono: string };
const FALLBACK: Theme = {
  bg: "#f3efe6", surface: "#fffdf8", text: "#211d17", text2: "#6a635a", text3: "#9a927f",
  font: '"Rubik", system-ui, sans-serif', display: '"Source Serif 4", Georgia, serif', mono: '"Source Code Pro", ui-monospace, monospace',
};

/** Цвета и шрифты текущей темы — из CSS-переменных страницы, чтобы картинка совпадала с экраном. */
export function readTheme(): Theme {
  if (typeof document === "undefined") return FALLBACK;
  const cs = getComputedStyle(document.body);
  const v = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb;
  return {
    bg: v("--bg", FALLBACK.bg), surface: v("--surface", FALLBACK.surface), text: v("--text", FALLBACK.text),
    text2: v("--text-2", FALLBACK.text2), text3: v("--text-3", FALLBACK.text3),
    font: v("--font", FALLBACK.font), display: v("--display", FALLBACK.display), mono: v("--mono", FALLBACK.mono),
  };
}

const PAD = 44, CAPTION_H = 26;

/** Границы карты с запасом под подписи, бейджи и стрелки. */
export function bounds(laid: Laid[]) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const l of laid) {
    minX = Math.min(minX, l.x - l.w / 2 - 30); maxX = Math.max(maxX, l.x + l.w / 2 + 30);
    minY = Math.min(minY, l.y - l.h / 2 - 16); maxY = Math.max(maxY, l.y + l.h / 2 + 16);
  }
  if (!isFinite(minX)) { minX = -60; maxX = 60; minY = -30; maxY = 30; }
  return { minX, maxX, minY, maxY, w: maxX - minX, h: maxY - minY };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y); ctx.lineTo(x + w - rr, y); ctx.arcTo(x + w, y, x + w, y + rr, rr);
  ctx.lineTo(x + w, y + h - rr); ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr);
  ctx.lineTo(x + rr, y + h); ctx.arcTo(x, y + h, x, y + h - rr, rr);
  ctx.lineTo(x, y + rr); ctx.arcTo(x, y, x + rr, y, rr); ctx.closePath();
}

/** Подпись-«таблетка» (на ветке или связи), центр в (cx, cy); dashed — у связей. */
function pill(ctx: CanvasRenderingContext2D, text: string, cx: number, cy: number, color: string, th: Theme, dashed: boolean) {
  ctx.font = `italic 11.5px ${th.font}`;
  const tw = Math.min(ctx.measureText(text).width, 170);
  const w = tw + 16, h = 18;
  ctx.save();
  ctx.setLineDash(dashed ? [3, 3] : []);
  ctx.fillStyle = th.surface; ctx.strokeStyle = color; ctx.lineWidth = 1;
  roundRect(ctx, cx - w / 2, cy - h / 2, w, h, 9); ctx.fill(); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = th.text2; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.save(); roundRect(ctx, cx - w / 2 + 4, cy - h / 2, w - 8, h, 9); ctx.clip();
  ctx.fillText(text, cx, cy + 0.5); ctx.restore();
  ctx.restore();
}

/** Нарисовать карту на canvas. Возвращает canvas (для тестов и предпросмотра); toPngBlob() делает из него файл. */
export function drawMap(tree: MindNode, opts: { title: string; theme?: Theme; scale?: number; now?: Date }): HTMLCanvasElement {
  const th = opts.theme ?? readTheme();
  const laid = layout(tree);
  const byId = new Map(laid.map((l) => [l.node.id, l]));
  const links: MindLink[] = tree.links ?? [];
  const b = bounds(laid);
  const scale = opts.scale ?? Math.min(2, Math.max(1, typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1));
  const W = Math.ceil(b.w + PAD * 2), H = Math.ceil(b.h + PAD * 2 + CAPTION_H);
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(W * scale); canvas.height = Math.ceil(H * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Браузер не умеет рисовать картинки (canvas недоступен)");
  ctx.scale(scale, scale);
  ctx.fillStyle = th.bg; ctx.fillRect(0, 0, W, H);
  ctx.translate(PAD - b.minX, PAD - b.minY);

  // ветки
  ctx.lineCap = "round"; ctx.globalAlpha = 0.9;
  for (const l of laid) {
    if (!l.parent) continue;
    const { x1, y1, x2, y2 } = edgeEnds(l); const dx = (x2 - x1) / 2;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.bezierCurveTo(x1 + dx, y1, x2 - dx, y2, x2, y2);
    ctx.strokeStyle = l.color; ctx.lineWidth = strokeFor(l.depth, l.adj); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  // связи
  const vis = links.map((l) => ({ l, a: byId.get(l.from), b: byId.get(l.to) })).filter((x): x is { l: MindLink; a: Laid; b: Laid } => !!x.a && !!x.b);
  for (const { l, a, b: bb } of vis) {
    const g = linkGeom(a, bb); const col = l.color ?? LINK_COLOR;
    ctx.save(); ctx.setLineDash([6, 5]); ctx.strokeStyle = col; ctx.lineWidth = 1.8;
    ctx.beginPath(); ctx.moveTo(g.p0.x, g.p0.y); ctx.quadraticCurveTo(g.c.x, g.c.y, g.p2.x, g.p2.y); ctx.stroke(); ctx.restore();
    ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(g.headPts[0].x, g.headPts[0].y); ctx.lineTo(g.headPts[1].x, g.headPts[1].y); ctx.lineTo(g.headPts[2].x, g.headPts[2].y); ctx.closePath(); ctx.fill();
  }
  // подписи веток
  for (const l of laid) {
    if (!l.parent || !l.node.note) continue;
    const { x1, y1, x2, y2 } = edgeEnds(l);
    pill(ctx, l.node.note, (x1 + x2) / 2, (y1 + y2) / 2 - 12, l.color, th, false);
  }
  // узлы
  for (const l of laid) {
    const x = l.x - l.w / 2, y = l.y - l.h / 2, fs = fontFor(l.depth);
    const d0 = l.depth === 0, d1 = l.depth === 1;
    ctx.save();
    if (d0) { ctx.shadowColor = "rgba(15,118,110,0.35)"; ctx.shadowBlur = 18; ctx.shadowOffsetY = 6; }
    else { ctx.shadowColor = "rgba(40,30,10,0.10)"; ctx.shadowBlur = 4; ctx.shadowOffsetY = 1; }
    ctx.fillStyle = d0 ? MIND_COLOR : d1 ? l.color : th.surface;
    roundRect(ctx, x, y, l.w, l.h, 999); ctx.fill();
    ctx.restore();
    if (!d0 && !d1) { ctx.strokeStyle = l.color; ctx.lineWidth = 1.5; roundRect(ctx, x, y, l.w, l.h, 999); ctx.stroke(); }
    if (l.node.collapsed && l.node.children.length) { ctx.save(); ctx.setLineDash([4, 3]); ctx.strokeStyle = l.color; ctx.lineWidth = 2; roundRect(ctx, x, y, l.w, l.h, 999); ctx.stroke(); ctx.restore(); }
    ctx.fillStyle = d0 || d1 ? "#ffffff" : th.text;
    ctx.font = `${d0 ? 700 : d1 ? 600 : 500} ${fs}px ${d0 ? th.display : th.font}`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const lh = fs * 1.3; const top = l.y - (l.lines.length * lh) / 2 + lh / 2;
    l.lines.forEach((t, i) => ctx.fillText(t, l.x, top + i * lh));
    // важность
    const p = l.node.priority ?? 0;
    if (p > 0) {
      ctx.font = `700 11px ${th.mono}`;
      const tw = ctx.measureText(PRIORITY_MARK[p]).width; const bw = Math.max(18, tw + 10), bh = 18;
      const bx = l.x + l.w / 2 + 6 - bw, by = l.y - l.h / 2 - 9;
      ctx.fillStyle = th.bg; roundRect(ctx, bx - 2, by - 2, bw + 4, bh + 4, 11); ctx.fill();
      ctx.fillStyle = PRIORITY_COLOR[p]; roundRect(ctx, bx, by, bw, bh, 9); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(PRIORITY_MARK[p], bx + bw / 2, by + bh / 2 + 0.5);
    }
    // свёрнутая ветка — число скрытых узлов
    if (l.node.collapsed && l.node.children.length) {
      const n = countHidden(l.node); const cx = l.x + l.w / 2 + 15, cy = l.y;
      ctx.fillStyle = th.text; ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = `600 11px ${th.mono}`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(n), cx, cy + 0.5);
    }
  }
  // подписи связей — поверх узлов, как на экране
  for (const { l, a, b: bb } of vis) {
    if (!l.note) continue;
    const g = linkGeom(a, bb); pill(ctx, l.note, g.mid.x, g.mid.y, l.color ?? LINK_COLOR, th, true);
  }
  // подпись внизу
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = th.text3; ctx.font = `11px ${th.font}`; ctx.textAlign = "right"; ctx.textBaseline = "alphabetic";
  ctx.fillText(`${opts.title} · CIS Planner · ${fmtDay(opts.now ?? new Date())}`, W - 16, H - 10);
  return canvas;
}

function countHidden(n: MindNode): number { return n.children.reduce((s, c) => s + 1 + countHidden(c), 0); }

export function toPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    if (typeof canvas.toBlob !== "function") { reject(new Error("Браузер не умеет сохранять картинки")); return; }
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Не удалось собрать PNG"))), "image/png");
  });
}

/* ---------- файлы ---------- */

/** Имя файла из названия карты: без символов, запрещённых в Windows/iOS, не длиннее 80 знаков. */
export function fileName(title: string, ext: string): string {
  const base = (title || "Майндмап").replace(/[\\/:*?"<>|\x00-\x1f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "Майндмап";
  return `${base}.${ext}`;
}

/** Скачать файл. На телефоне (если умеет) — системное меню «Поделиться», откуда файл уходит в Claude, Telegram или почту. */
export async function saveFile(blob: Blob, name: string, preferShare = false): Promise<"shared" | "downloaded"> {
  const nav = typeof navigator !== "undefined" ? (navigator as Navigator & { canShare?: (d: ShareData) => boolean }) : undefined;
  if (preferShare && nav?.share && nav.canShare) {
    const file = new File([blob], name, { type: blob.type });
    if (nav.canShare({ files: [file] })) {
      try { await nav.share({ files: [file], title: name }); return "shared"; }
      catch (e) { if ((e as Error)?.name === "AbortError") return "shared"; /* иначе — обычное скачивание */ }
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.rel = "noopener"; a.style.display = "none";
  document.body.appendChild(a); a.click(); a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return "downloaded";
}

/** Скопировать текст в буфер обмена; false — не вышло (нет разрешения / старый браузер). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* попробуем запасной путь */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove();
    return ok;
  } catch { return false; }
}
