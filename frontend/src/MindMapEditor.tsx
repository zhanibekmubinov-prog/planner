// Редактор майндмапа в духе MindNode: центральная тема, автоматическая раскладка влево/вправо,
// плавные ветви, цвет ветви первого уровня наследуется потомками. Автосохранение.
// v1.2: панель выбранного узла (цвет ветки, толщина, важность, подпись линии), связи-стрелки между любыми узлами
// (тянуть за ручку под узлом), толщина линий убывает с глубиной автоматически.
// v1.4: кнопка «Экспорт…» — текст-структура (Markdown: скопировать / скачать) и картинка PNG; геометрия вынесена в mindmapGeom.ts.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { del, dirColor, errorText, MIND_COLOR, MindLink, MindMap, MindMapIn, MindNode, newNodeId, put } from "./api";
import { useConfirm } from "./confirm";
import { layerCount, useDirtyFlag } from "./layers";
import MiniMenu, { MiniAnchor, miniAnchor } from "./MiniMenu";
import { copyText, drawMap, fileName, saveFile, toMarkdown, toPngBlob } from "./mindmapExport";
import { anchor, countAll, edgeEnds, edgePath, findNode, findParent, fontFor, idsOf, Laid, layout, LINK_COLOR, linkGeom, mapTree, PALETTE, PRIORITY_MARK, strokeFor } from "./mindmapGeom";
import { useIsMobile } from "./mobile";
import { Store } from "./store";
import { useToast } from "./toast";

type Props = { store: Store; map: MindMap; onBack: () => void; onDeleted: () => void; onOpenTask?: (taskId: number) => void };

/** Масштаб и сдвиг, при которых вся карта видна в области el с полями; k в пределах [0.3, maxK]. */
function fitView(el: HTMLElement, laid: Laid[], maxK: number) {
  if (!laid.length || !el.clientWidth || !el.clientHeight) return { x: el.clientWidth / 2, y: el.clientHeight / 2, k: 1 };
  const minX = Math.min(...laid.map((l) => l.x - l.w / 2)), maxX = Math.max(...laid.map((l) => l.x + l.w / 2));
  const minY = Math.min(...laid.map((l) => l.y - l.h / 2)), maxY = Math.max(...laid.map((l) => l.y + l.h / 2));
  const k = Math.min(maxK, Math.max(0.3, Math.min((el.clientWidth - 80) / (maxX - minX || 1), (el.clientHeight - 80) / (maxY - minY || 1))));
  return { k, x: el.clientWidth / 2 - ((minX + maxX) / 2) * k, y: el.clientHeight / 2 - ((minY + maxY) / 2) * k };
}

/* ---------- компонент ---------- */
export default function MindMapEditor({ store, map, onBack, onDeleted, onOpenTask }: Props) {
  const [tree, setTree] = useState<MindNode>(map.data?.id ? map.data : { id: "root", text: map.title, children: [] });
  const [title, setTitle] = useState(map.title);
  const [selected, setSelected] = useState<string | null>(null);
  const [selLink, setSelLink] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [noteEdit, setNoteEdit] = useState(false);             // открыта строка «подпись линии» в панели узла
  const [linking, setLinking] = useState<{ from: string; px: number; py: number } | null>(null);
  const [armed, setArmed] = useState<string | null>(null);     // «Связать» кнопкой: ждём клик по второму узлу
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [dragging, setDragging] = useState<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const areaRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const confirm = useConfirm();
  const toast = useToast();
  const isMobile = useIsMobile();
  const [exportMenu, setExportMenu] = useState<MiniAnchor | null>(null);
  // С5: последняя версия — в ref, чтобы досохранить при уходе со страницы; revision — чтобы ответ на старую версию не гасил «изменено»
  const latest = useRef({ tree, title });
  const dirtyRef = useRef(false);
  const revision = useRef(0);
  const storeRef = useRef(store); storeRef.current = store;
  useDirtyFlag(dirty);

  const laid = useMemo(() => layout(tree), [tree]);
  const byId = useMemo(() => new Map(laid.map((l) => [l.node.id, l])), [laid]);
  const links = tree.links ?? [];
  const direction = map.direction_id ? store.directions.find((d) => d.id === map.direction_id) : undefined;
  const task = map.task_id ? store.tasks.find((t) => t.id === map.task_id) : undefined;

  // v1.4.1: при открытии карта вписывается в область целиком (раньше — центр при 100%, и большая карта уезжала за края).
  // Мелкую карту не увеличиваем больше 100%; кнопка «Вписать» может и до 200%.
  const fittedFor = useRef<number | null>(null);
  useEffect(() => {
    if (fittedFor.current === map.id) return;
    const el = areaRef.current; if (!el) return;
    fittedFor.current = map.id;
    setView(fitView(el, laid, 1));
  }, [map.id, laid]);

  const flush = useCallback(async () => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    if (!dirtyRef.current) return;
    const { tree: tr, title: ti } = latest.current; const rev = revision.current;
    setSaving(true);
    try {
      const body: MindMapIn = { title: ti.trim() || tr.text || "Майндмап", direction_id: map.direction_id ?? null, task_id: map.task_id ?? null, data: tr };
      storeRef.current.patchMindmap(await put<MindMap>(`/mindmaps/${map.id}`, body));
      if (revision.current === rev) { dirtyRef.current = false; setDirty(false); }
      else { timer.current = window.setTimeout(() => void flush(), 200); }   // правили во время запроса — дошлём
    } catch (e) { storeRef.current.setError(errorText(e)); } finally { setSaving(false); }
  }, [map.id, map.direction_id, map.task_id]);

  const schedule = useCallback(() => {
    dirtyRef.current = true; revision.current++; setDirty(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), 800);
  }, [flush]);

  const commit = useCallback((next: MindNode, nextTitle?: string) => {
    setTree(next); latest.current = { ...latest.current, tree: next };
    if (nextTitle !== undefined) { setTitle(nextTitle); latest.current = { ...latest.current, title: nextTitle }; }
    schedule();
  }, [schedule]);

  // С5: уход со страницы (Назад, Esc, другой раздел) — досохраняем то, что не успел таймер
  useEffect(() => () => { if (dirtyRef.current) void flush(); }, [flush]);
  const back = () => { void flush(); onBack(); };

  const selectNode = (id: string | null) => { setSelected(id); setSelLink(null); setNoteEdit(false); };
  const selectLink = (id: string | null) => { setSelLink(id); setSelected(null); setEditing(null); setNoteEdit(false); };

  /* --- редактирование --- */
  function patchNode(id: string, patch: Partial<MindNode>) {
    commit(mapTree(tree, (n) => (n.id === id ? { ...n, ...patch } : n)));
  }
  function addChild(parentId: string) {
    const id = newNodeId();
    commit(mapTree(tree, (n) => (n.id === parentId ? { ...n, collapsed: false, children: [...n.children, { id, text: "", children: [] }] } : n)));
    selectNode(id); setEditing(id);
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
    selectNode(nid); setEditing(nid);
  }
  /** Убрать узел из дерева и все связи, которые в него (или в его ветку) вели. */
  function withoutNode(root: MindNode, id: string): MindNode {
    const gone = idsOf(findNode(root, id) ?? { id, text: "", children: [] });
    const parent = findParent(root, id);
    const next = mapTree(root, (x) => (x.id === parent?.id ? { ...x, children: x.children.filter((c) => c.id !== id) } : x));
    return { ...next, links: (next.links ?? []).filter((l) => !gone.has(l.from) && !gone.has(l.to)) };
  }
  async function removeNode(id: string) {
    if (id === tree.id) return;
    const node = findNode(tree, id); if (!node) return;
    const n = countAll(node) - 1;
    if (n > 0 && !(await confirm(`Узел «${node.text || "…"}» и ${n} вложенных исчезнут с карты.`, { title: "Удалить ветку?", danger: true, okLabel: "Удалить ветку" }))) return;
    const parent = findParent(tree, id);
    commit(withoutNode(tree, id));
    selectNode(parent?.id ?? null); setEditing(null);
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
      commit(withoutNode(tree, id));
      selectNode(parent?.id ?? null);
    }
  }
  function setPriority(id: string, p: 0 | 1 | 2 | 3) {
    const cur = findNode(tree, id)?.priority ?? 0;
    patchNode(id, { priority: cur === p ? 0 : p });   // повторное нажатие снимает
  }

  /* --- связи --- */
  function addLink(from: string, to: string) {
    if (from === to || !findNode(tree, from) || !findNode(tree, to)) return;
    if (links.some((l) => (l.from === from && l.to === to) || (l.from === to && l.to === from))) return;   // уже связаны
    const id = newNodeId();
    commit({ ...tree, links: [...links, { id, from, to }] });
    selectLink(id);
  }
  function patchLink(id: string, patch: Partial<MindLink>) {
    commit({ ...tree, links: links.map((l) => (l.id === id ? { ...l, ...patch } : l)) });
  }
  function removeLink(id: string) {
    commit({ ...tree, links: links.filter((l) => l.id !== id) });
    setSelLink(null);
  }
  const toLayer = (clientX: number, clientY: number) => {
    const r = areaRef.current!.getBoundingClientRect();
    return { px: (clientX - r.left - view.x) / view.k, py: (clientY - r.top - view.y) / view.k };
  };
  function startLinking(e: React.PointerEvent, from: string) {
    e.stopPropagation(); e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setLinking({ from, ...toLayer(e.clientX, e.clientY) });
  }
  function moveLinking(e: React.PointerEvent) {
    if (!linking) return;
    setLinking({ ...linking, ...toLayer(e.clientX, e.clientY) });
  }
  function endLinking(e: React.PointerEvent) {
    if (!linking) return;
    const from = linking.from; setLinking(null);
    const target = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest<HTMLElement>("[data-node]");
    const to = target?.dataset.node;
    if (to && to !== from) addLink(from, to);
  }

  // клавиатура
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editing || noteEdit) return; // в режиме ввода — свои обработчики
      if (layerCount() > 0) return;   // С4: открыт диалог/меню — клавиши ему, а не карте
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (selLink) {
        if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeLink(selLink); }
        else if (e.key === "Escape") { setSelLink(null); }
        return;
      }
      if (!selected) { if (e.key === "Escape") back(); return; }
      if (e.key === "Tab") { e.preventDefault(); addChild(selected); }
      else if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey || selected === tree.id) setEditing(selected); else addSibling(selected); }
      else if (e.key === "F2") { e.preventDefault(); setEditing(selected); }
      else if (e.key === "Delete") { e.preventDefault(); void removeNode(selected); }
      // С4: Backspace на листе — не удаление, а правка текста (как в текстовом редакторе); ветку — только Delete
      else if (e.key === "Backspace") { e.preventDefault(); const n = findNode(tree, selected); if (n && n.children.length === 0 && selected !== tree.id) setEditing(selected); else void removeNode(selected); }
      else if (e.key === " ") { e.preventDefault(); toggleCollapse(selected); }
      else if (e.key === "0" || e.key === "1" || e.key === "2" || e.key === "3") { e.preventDefault(); setPriority(selected, Number(e.key) as 0 | 1 | 2 | 3); }
      else if (e.key === "Escape") { if (armed) setArmed(null); else selectNode(null); }
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
    setView(fitView(el, laid, 2));
  }

  async function relink(directionId: number | null) {
    try {
      const body: MindMapIn = { title: title.trim() || tree.text || "Майндмап", direction_id: directionId, task_id: map.task_id ?? null, data: tree };
      store.patchMindmap(await put<MindMap>(`/mindmaps/${map.id}`, body));
    } catch (e) { store.setError(errorText(e)); }
  }

  /* --- экспорт (v1.4) --- */
  const exportCtx = () => ({ direction: direction?.name ?? null, task: task?.title ?? null });
  const currentMap = (): MindMap => ({ ...map, title: title.trim() || tree.text || "Майндмап", data: tree });
  async function exportMarkdown(mode: "copy" | "file") {
    const md = toMarkdown(currentMap(), exportCtx());
    if (mode === "copy") {
      if (await copyText(md)) toast("Структура скопирована — вставьте её в Claude или документ", { ms: 4000 });
      else store.setError("Не удалось скопировать: браузер не дал доступ к буферу обмена. Скачайте файл .md.");
      return;
    }
    const how = await saveFile(new Blob([md], { type: "text/markdown;charset=utf-8" }), fileName(currentMap().title, "md"), isMobile);
    if (how === "downloaded") toast("Файл .md сохранён в загрузки", { ms: 4000 });
  }
  async function exportPng() {
    try {
      const m = currentMap();
      const blob = await toPngBlob(drawMap(tree, { title: m.title }));
      const how = await saveFile(blob, fileName(m.title, "png"), isMobile);
      if (how === "downloaded") toast("Картинка PNG сохранена в загрузки", { ms: 4000 });
    } catch (e) { store.setError(e instanceof Error ? e.message : String(e)); }
  }

  async function removeMap() {
    if (!(await confirm(`Майндмап «${title}» будет удалён целиком — все ${countAll(tree)} узлов. Корзины у майндмапов нет.`, { title: "Удалить майндмап?", danger: true, okLabel: "Удалить майндмап" }))) return;
    dirtyRef.current = false; if (timer.current) window.clearTimeout(timer.current);
    try { await del(`/mindmaps/${map.id}`); await store.reloadMindmaps(); onDeleted(); } catch (e) { store.setError(errorText(e)); }
  }

  const visibleLinks = links.map((l) => ({ l, a: byId.get(l.from), b: byId.get(l.to) })).filter((x): x is { l: MindLink; a: Laid; b: Laid } => !!x.a && !!x.b);

  const toScreen = (x: number, y: number) => ({ left: view.x + x * view.k, top: view.y + y * view.k });
  const selL = selected ? byId.get(selected) : undefined;
  const selLk = selLink ? visibleLinks.find((x) => x.l.id === selLink) : undefined;

  /* --- панель --- */
  const swatches = (cur: string | undefined, onPick: (c: string | undefined) => void, autoTitle: string) => (
    <div className="mm-sw" role="group" aria-label="Цвет">
      <button className={`mm-swatch auto ${cur ? "" : "on"}`} title={autoTitle} onClick={() => onPick(undefined)} aria-label={autoTitle} />
      {PALETTE.map((c) => <button key={c} className={`mm-swatch ${cur === c ? "on" : ""}`} style={{ background: c }} title={c} aria-label={`Цвет ${c}`} onClick={() => onPick(c)} />)}
    </div>
  );

  return (
    <div className="mm" style={{ ["--mind" as string]: MIND_COLOR }}>
      <div className="mm-bar">
        <button className="btn ghost" onClick={back}>← Назад</button>
        <span className="mm-glyph" aria-hidden="true" />
        <input className="mm-title" value={title} onChange={(e) => { setTitle(e.target.value); latest.current = { ...latest.current, title: e.target.value }; schedule(); }} placeholder="Название майндмапа" />
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
        <button className="btn ghost sm mm-export" onClick={(e) => setExportMenu(miniAnchor(e))} aria-haspopup="menu" aria-expanded={!!exportMenu} title="Экспорт: текст-структура для Claude или картинка">Экспорт…</button>
        <button className="btn danger sm" onClick={removeMap}>Удалить</button>
      </div>
      {exportMenu && (
        <MiniMenu anchor={exportMenu} label="Экспорт майндмапа" title="Экспорт майндмапа" onClose={() => setExportMenu(null)} items={[
          { label: "Скопировать структуру (текст)", onClick: () => void exportMarkdown("copy") },
          { label: isMobile ? "Структура — поделиться файлом .md" : "Скачать структуру — файл .md", onClick: () => void exportMarkdown("file") },
          "hr",
          { label: isMobile ? "Картинка PNG — поделиться" : "Картинка PNG — скачать", onClick: () => void exportPng() },
        ]} />
      )}

      <div
        ref={areaRef} className={`mm-area ${dragging ? "dragging" : ""} ${linking || armed ? "linking" : ""}`}
        onWheel={onWheel}
        onMouseDown={(e) => { if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains("mm-layer")) { setDragging({ sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y }); selectNode(null); setEditing(null); setArmed(null); } }}
        onMouseMove={(e) => { if (dragging) setView((v) => ({ ...v, x: dragging.ox + e.clientX - dragging.sx, y: dragging.oy + e.clientY - dragging.sy })); }}
        onMouseUp={() => setDragging(null)} onMouseLeave={() => setDragging(null)}
      >
        <div className="mm-layer" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
          <svg className="mm-edges" style={{ overflow: "visible" }}>
            {laid.filter((l) => l.parent).map((l) => (
              <path key={l.node.id} d={edgePath(l)} stroke={l.color} strokeWidth={strokeFor(l.depth, l.adj)} fill="none" strokeLinecap="round" opacity={0.9} />
            ))}
            {visibleLinks.map(({ l, a, b }) => {
              const g = linkGeom(a, b); const col = l.color ?? LINK_COLOR; const on = selLink === l.id;
              return (
                <g key={l.id} className={`mm-link ${on ? "sel" : ""}`}>
                  <path d={g.d} stroke={col} strokeWidth={on ? 2.6 : 1.8} strokeDasharray="6 5" fill="none" strokeLinecap="round" />
                  <path d={g.head} fill={col} />
                  <path d={g.d} className="mm-link-hit" stroke="transparent" strokeWidth={16} fill="none"
                        onClick={(e) => { e.stopPropagation(); selectLink(l.id); }} onMouseDown={(e) => e.stopPropagation()} />
                </g>
              );
            })}
            {linking && byId.get(linking.from) && (() => {
              const a = byId.get(linking.from)!; const p0 = anchor(a, linking.px, linking.py);
              return <path d={`M ${p0.x} ${p0.y} L ${linking.px} ${linking.py}`} stroke={LINK_COLOR} strokeWidth={1.8} strokeDasharray="6 5" fill="none" />;
            })()}
          </svg>

          {/* подписи на линиях веток */}
          {laid.filter((l) => l.parent && l.node.note).map((l) => {
            const { x1, y1, x2, y2 } = edgeEnds(l);
            return (
              <button key={"n" + l.node.id} className="mm-edge-note" style={{ left: (x1 + x2) / 2, top: (y1 + y2) / 2, ["--c" as string]: l.color }}
                      title="Подпись линии — нажмите, чтобы изменить"
                      onMouseDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); selectNode(l.node.id); setNoteEdit(true); }}>
                {l.node.note}
              </button>
            );
          })}
          {laid.map((l) => {
            const isSel = selected === l.node.id, isEdit = editing === l.node.id;
            const hidden = l.node.collapsed && l.node.children.length > 0;
            const prio = l.node.priority ?? 0;
            return (
              <div
                key={l.node.id} data-node={l.node.id}
                className={`mm-node d${Math.min(l.depth, 2)} ${isSel ? "sel" : ""} ${hidden ? "collapsed" : ""} ${isEdit ? "editing" : ""} ${armed && armed !== l.node.id ? "target" : ""}`}
                style={(() => {
                  // В режиме ввода узел шире — растёт в сторону от родителя, чтобы не наезжать на него
                  const w = isEdit ? Math.max(l.w, 240) : l.w;
                  const left = !isEdit || l.side === 0 ? l.x - w / 2 : l.side === 1 ? l.x - l.w / 2 : l.x + l.w / 2 - w;
                  return { left, top: l.y - l.h / 2, width: w, minHeight: l.h, ["--c" as string]: l.color, fontSize: fontFor(l.depth) };
                })()}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  if (armed && armed !== l.node.id) { addLink(armed, l.node.id); setArmed(null); return; }
                  selectNode(l.node.id);
                }}
                onDoubleClick={(e) => { e.stopPropagation(); selectNode(l.node.id); setEditing(l.node.id); }}
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
                {prio > 0 && <span className={`mm-badge p${prio}`} title={`Важность ${prio} из 3`} aria-label={`Важность ${prio} из 3`}>{PRIORITY_MARK[prio]}</span>}
                {hidden && <button className="mm-count" title="Развернуть" onClick={(e) => { e.stopPropagation(); toggleCollapse(l.node.id); }}>{countAll(l.node) - 1}</button>}
                {isSel && !isEdit && (
                  <>
                    <button className={`mm-add ${l.side === -1 ? "left" : "right"}`} title="Добавить подпункт (Tab)" onClick={(e) => { e.stopPropagation(); addChild(l.node.id); }}>+</button>
                    {l.node.children.length > 0 && !hidden && (
                      <button className={`mm-fold ${l.side === -1 ? "left" : "right"}`} title="Свернуть (пробел)" onClick={(e) => { e.stopPropagation(); toggleCollapse(l.node.id); }}>–</button>
                    )}
                    <button className="mm-link-handle" title="Связь с другим узлом — потяните на него" aria-label="Связать с другим узлом"
                            onPointerDown={(e) => startLinking(e, l.node.id)} onPointerMove={moveLinking} onPointerUp={endLinking} onPointerCancel={() => setLinking(null)}
                            onClick={(e) => e.stopPropagation()} />
                  </>
                )}
              </div>
            );
          })}
          {/* подписи на связях */}
          {visibleLinks.filter(({ l }) => l.note).map(({ l, a, b }) => {
            const g = linkGeom(a, b);
            return (
              <button key={"ln" + l.id} className="mm-edge-note link" style={{ left: g.mid.x, top: g.mid.y, ["--c" as string]: l.color ?? LINK_COLOR }}
                      onMouseDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); selectLink(l.id); }}>
                {l.note}
              </button>
            );
          })}
        </div>

        {/* панель выбранного узла — над узлом, в экранных координатах (не масштабируется вместе с картой) */}
        {selL && !editing && (() => {
          const pos = toScreen(selL.x, selL.y - selL.h / 2);
          const isRoot = selL.depth === 0; const n = selL.node; const cur = n.priority ?? 0;
          return (
            <div className="mm-panel" style={{ left: pos.left, top: pos.top }} role="toolbar" aria-label="Настройки узла"
                 onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
              <div className="mm-panel-row">
                {!isRoot && swatches(n.color, (c) => patchNode(n.id, { color: c }), "Цвет ветки как у родителя")}
                {!isRoot && <span className="mm-sep" />}
                <div className="mm-seg" role="group" aria-label="Толщина линии" title="Толщина линии: тоньше · автоматически · толще">
                  {([-1, 0, 1] as const).map((a) => (
                    <button key={a} className={(n.width ?? 0) === a ? "on" : ""} onClick={() => patchNode(n.id, { width: a === 0 ? undefined : a })}
                            aria-label={a === -1 ? "Тоньше" : a === 1 ? "Толще" : "Автоматически"} aria-pressed={(n.width ?? 0) === a}>
                      <svg width="18" height="12" viewBox="0 0 18 12" aria-hidden="true"><path d="M1 6 H17" stroke="currentColor" strokeLinecap="round" strokeWidth={a === -1 ? 1.2 : a === 0 ? 2.4 : 4} /></svg>
                    </button>
                  ))}
                </div>
                <span className="mm-sep" />
                <div className="mm-seg prio" role="group" aria-label="Важность" title="Важность (клавиши 1–3, 0 — снять)">
                  {([1, 2, 3] as const).map((p) => (
                    <button key={p} className={cur === p ? "on" : ""} onClick={() => setPriority(n.id, p)} aria-pressed={cur === p} aria-label={`Важность ${p}`}>{PRIORITY_MARK[p]}</button>
                  ))}
                </div>
                {!isRoot && <span className="mm-sep" />}
                {!isRoot && <button className={`mm-pbtn ${noteEdit || n.note ? "on" : ""}`} onClick={() => setNoteEdit((v) => !v)} title="Подпись на линии от родителя">Подпись</button>}
                <span className="mm-sep" />
                <button className={`mm-pbtn ${armed === n.id ? "on" : ""}`} onClick={() => setArmed(armed === n.id ? null : n.id)} title="Связать: нажмите, затем выберите второй узел">
                  {armed === n.id ? "Выберите узел…" : "Связать"}
                </button>
              </div>
              {noteEdit && !isRoot && (
                <div className="mm-panel-row">
                  <input autoFocus className="input mm-note-input" value={n.note ?? ""} placeholder="Подпись на линии, например «зависит от»"
                         onChange={(e) => patchNode(n.id, { note: e.target.value || undefined })}
                         onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); setNoteEdit(false); } }} />
                </div>
              )}
            </div>
          );
        })()}

        {/* панель выбранной связи */}
        {selLk && (() => {
          const g = linkGeom(selLk.a, selLk.b); const pos = toScreen(g.mid.x, g.mid.y); const l = selLk.l;
          return (
            <div className="mm-panel" style={{ left: pos.left, top: pos.top - 14 }} role="toolbar" aria-label="Настройки связи"
                 onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
              <div className="mm-panel-row">
                {swatches(l.color, (c) => patchLink(l.id, { color: c }), "Серый по умолчанию")}
                <span className="mm-sep" />
                <input className="input mm-note-input" value={l.note ?? ""} placeholder="Подпись связи"
                       onChange={(e) => patchLink(l.id, { note: e.target.value || undefined })}
                       onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); (e.target as HTMLInputElement).blur(); } }} />
                <span className="mm-sep" />
                <button className="mm-pbtn danger" onClick={() => removeLink(l.id)} title="Убрать связь (Del)">Убрать</button>
              </div>
            </div>
          );
        })()}

        <div className="mm-help">
          <span><kbd>Tab</kbd> подпункт</span><span><kbd>Enter</kbd> соседний</span><span><kbd>F2</kbd> / двойной клик — текст</span>
          <span><kbd>Del</kbd> удалить</span><span><kbd>Пробел</kbd> свернуть</span><span><kbd>1</kbd>–<kbd>3</kbd> важность</span>
          <span>точка под узлом — потянуть на другой узел: связь</span><span>колёсико — масштаб, тянуть фон — сдвиг</span>
        </div>
      </div>
    </div>
  );
}
