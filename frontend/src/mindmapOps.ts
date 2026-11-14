// v1.8 — операции над майндмапом: зеркало backend/app/mindmap_ops.py (менять синхронно!).
// Редактор не отправляет карту целиком, а шлёт пачки «добавить / поменять поля / убрать / перенести / связать».
// Здесь — то же применение, что на сервере: им клиент накладывает свои ещё не подтверждённые правки и чужие
// пачки из живого канала. Операция, потерявшая смысл (узел уже удалили), просто пропускается.
// Повторное применение пачки ничего не меняет — поэтому свою пачку можно спокойно наложить ещё раз.
import type { MindLink, MindNode, MindOp } from "./api";

type Doc = { tree: MindNode; title: string };

function clone<T>(x: T): T { return JSON.parse(JSON.stringify(x)) as T; }

/** Поле со значением «по умолчанию» убираем — JSON карты такой же, каким его пишет сервер. */
function applyFields(obj: Record<string, unknown>, fields: Record<string, unknown>, keepText = false) {
  for (const [k, v] of Object.entries(fields)) {
    if (v === undefined) continue;
    if (v === null || (k === "priority" && v === 0) || (k === "collapsed" && v === false)) {
      if (keepText && k === "text") obj[k] = ""; else delete obj[k];
    } else obj[k] = v;
  }
}

function index(root: MindNode) {
  const node = new Map<string, MindNode>(); const parent = new Map<string, MindNode | null>();
  const stack: [MindNode, MindNode | null][] = [[root, null]];
  while (stack.length) {
    const [n, p] = stack.pop()!;
    if (!Array.isArray(n.children)) n.children = [];
    node.set(n.id, n); parent.set(n.id, p);
    for (const c of n.children) stack.push([c, n]);
  }
  return { node, parent };
}

function subtreeIds(n: MindNode): Set<string> {
  const out = new Set<string>(); const stack = [n];
  while (stack.length) { const x = stack.pop()!; out.add(x.id); stack.push(...(x.children ?? [])); }
  return out;
}

function insert(p: MindNode, n: MindNode, at?: number | null) {
  const i = at == null ? p.children.length : Math.max(0, Math.min(at, p.children.length));
  p.children.splice(i, 0, n);
}

/** Применить операции к копии карты. Исходник не трогаем — React сравнивает по ссылке. */
export function applyOps(doc: Doc, ops: MindOp[]): Doc {
  if (!ops.length) return doc;
  const root = clone(doc.tree);
  let title = doc.title;
  const { node, parent } = index(root);
  const links = (): MindLink[] => (root.links ??= []);

  for (const op of ops) {
    switch (op.type) {
      case "add": {
        const p = node.get(op.parent);
        if (!p || node.has(op.node.id)) break;
        const { id, text, ...rest } = op.node;
        const n: MindNode = { id, text: text ?? "", children: [] };
        applyFields(n as unknown as Record<string, unknown>, rest);
        insert(p, n, op.index); node.set(id, n); parent.set(id, p);
        break;
      }
      case "set": {
        const n = node.get(op.id);
        if (n) applyFields(n as unknown as Record<string, unknown>, op.fields, true);
        break;
      }
      case "remove": {
        const n = node.get(op.id); const p = parent.get(op.id);
        if (!n || !p) break;   // нет узла или это корень
        const gone = subtreeIds(n);
        p.children = p.children.filter((c) => c.id !== op.id);
        gone.forEach((g) => { node.delete(g); parent.delete(g); });
        root.links = links().filter((l) => !gone.has(l.from) && !gone.has(l.to));
        break;
      }
      case "move": {
        const n = node.get(op.id); const from = parent.get(op.id); const to = node.get(op.parent);
        if (!n || !from || !to || subtreeIds(n).has(to.id)) break;
        from.children = from.children.filter((c) => c.id !== op.id);
        insert(to, n, op.index); parent.set(n.id, to);
        break;
      }
      case "link_add": {
        const l = op.link;
        if (l.from === l.to || !node.has(l.from) || !node.has(l.to)) break;
        if (links().some((x) => x.id === l.id || (x.from === l.from && x.to === l.to) || (x.from === l.to && x.to === l.from))) break;
        links().push(clone(l));
        break;
      }
      case "link_set": {
        const l = links().find((x) => x.id === op.id);
        if (l) applyFields(l as unknown as Record<string, unknown>, op.fields);
        break;
      }
      case "link_remove":
        if (root.links) root.links = root.links.filter((x) => x.id !== op.id);
        break;
      case "title":
        if (op.title.trim()) title = op.title.trim();
        break;
    }
  }
  return { tree: root, title };
}

/** Дописать операции в очередь неотправленных, склеивая подряд идущие правки одного узла
 *  (набор текста — это десятки «set text» в секунду; на сервер уходит последняя). */
export function enqueue(queue: MindOp[], ops: MindOp[]): MindOp[] {
  const out = [...queue];
  for (const op of ops) {
    const last = out[out.length - 1];
    if (last && last.type === "set" && op.type === "set" && last.id === op.id) {
      out[out.length - 1] = { ...last, fields: { ...last.fields, ...op.fields } };
    } else if (last && last.type === "link_set" && op.type === "link_set" && last.id === op.id) {
      out[out.length - 1] = { ...last, fields: { ...last.fields, ...op.fields } };
    } else if (last && last.type === "title" && op.type === "title") {
      out[out.length - 1] = op;
    } else out.push(op);
  }
  return out;
}
