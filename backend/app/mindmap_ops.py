"""v1.8 — совместная правка майндмапа: операции над отдельными узлами.

Раньше редактор отправлял карту целиком (PUT), и при одновременной работе двух людей
выигрывал тот, чей запрос пришёл последним, — правки второго пропадали. Теперь редактор
шлёт пачку операций «добавить узел / поменять поля / убрать / перенести / связать»,
а сервер применяет их к текущему дереву по очереди. Двое мешают друг другу, только если
правят одно и то же поле одного узла (тогда выигрывает последний — на уровне поля,
а не всей карты).

Операция, которая потеряла смысл из-за чужой правки (узел уже удалили, связь уже есть),
не ошибка: её молча пропускаем и возвращаем в `skipped`. Ошибка формы (неизвестный тип,
неверные поля) — 400 на всю пачку: это баг клиента.

Тот же алгоритм живёт на фронте (`frontend/src/mindmapOps.ts`) — менять синхронно.
Важное свойство: повторное применение пачки ничего не меняет (add существующего id,
remove отсутствующего — пропуск), поэтому клиент может спокойно наложить свою пачку
поверх версии, где она уже учтена.
"""
from __future__ import annotations

import copy
from typing import Any

MAX_OPS = 500          # операций в одной пачке
MAX_NODES = 5000       # узлов в карте
MAX_TEXT = 2000        # символов в тексте узла
MAX_NOTE = 300         # подпись линии / связи
MAX_ID = 64
MAX_TITLE = 300

OP_TYPES = ("add", "set", "remove", "move", "link_add", "link_set", "link_remove", "title")


class OpError(ValueError):
    """Пачка составлена неверно — отвечаем 400."""


# ── проверка полей ───────────────────────────────────────────────────────────

def _id(v: Any, what: str) -> str:
    if not isinstance(v, str) or not v or len(v) > MAX_ID:
        raise OpError(f"{what}: нужен непустой id до {MAX_ID} символов")
    return v


def _index(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise OpError("index: целое число")
    return v


def _str(v: Any, limit: int, what: str) -> str:
    if not isinstance(v, str):
        raise OpError(f"{what}: строка")
    if len(v) > limit:
        raise OpError(f"{what}: не длиннее {limit} символов")
    return v


def _color(v: Any) -> str:
    return _str(v, 32, "color")


def _width(v: Any) -> int:
    if isinstance(v, bool) or v not in (-1, 1):
        raise OpError("width: -1 или 1 (пусто — автоматически)")
    return v


def _priority(v: Any) -> int:
    if isinstance(v, bool) or v not in (0, 1, 2, 3):
        raise OpError("priority: 0–3")
    return v


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise OpError("collapsed: true или false")
    return v


NODE_FIELDS = {
    "text": lambda v: _str(v, MAX_TEXT, "text"),
    "color": _color,
    "width": _width,
    "priority": _priority,
    "note": lambda v: _str(v, MAX_NOTE, "note"),
    "collapsed": _bool,
}
LINK_FIELDS = {"color": _color, "note": lambda v: _str(v, MAX_NOTE, "note")}


def _fields(raw: Any, allowed: dict) -> dict:
    """Поля для set: значение None — убрать поле (вернуть «как по умолчанию»)."""
    if not isinstance(raw, dict) or not raw:
        raise OpError("fields: непустой объект")
    out = {}
    for k, v in raw.items():
        if k not in allowed:
            raise OpError(f"fields: поле {k!r} менять нельзя")
        out[k] = None if v is None else allowed[k](v)
    return out


def _apply_fields(obj: dict, fields: dict, *, keep: tuple[str, ...] = ()) -> None:
    """Записать поля. Значение «по умолчанию» (None, важность 0, не свёрнут) — поле убираем,
    чтобы JSON карты оставался таким же, как его пишет редактор."""
    for k, v in fields.items():
        if v is None or (k == "priority" and v == 0) or (k == "collapsed" and v is False):
            if k in keep:
                obj[k] = ""
            else:
                obj.pop(k, None)
        else:
            obj[k] = v


def validate(ops: Any) -> list[dict]:
    """Проверить форму пачки целиком до применения. Возвращает нормализованные операции."""
    if not isinstance(ops, list) or not ops:
        raise OpError("ops: непустой список операций")
    if len(ops) > MAX_OPS:
        raise OpError(f"ops: не больше {MAX_OPS} операций за раз")
    out = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise OpError(f"ops[{i}]: объект")
        t = op.get("type")
        try:
            if t == "add":
                node = op.get("node")
                if not isinstance(node, dict):
                    raise OpError("node: объект")
                n = {"id": _id(node.get("id"), "node.id"), "text": _str(node.get("text", ""), MAX_TEXT, "text"), "children": []}
                extra = {k: v for k, v in node.items() if k not in ("id", "text", "children")}
                if extra:
                    _apply_fields(n, _fields(extra, NODE_FIELDS))
                out.append({"type": "add", "parent": _id(op.get("parent"), "parent"), "index": _index(op.get("index")), "node": n})
            elif t == "set":
                out.append({"type": "set", "id": _id(op.get("id"), "id"), "fields": _fields(op.get("fields"), NODE_FIELDS)})
            elif t == "remove":
                out.append({"type": "remove", "id": _id(op.get("id"), "id")})
            elif t == "move":
                out.append({"type": "move", "id": _id(op.get("id"), "id"), "parent": _id(op.get("parent"), "parent"), "index": _index(op.get("index"))})
            elif t == "link_add":
                lk = op.get("link")
                if not isinstance(lk, dict):
                    raise OpError("link: объект")
                link = {"id": _id(lk.get("id"), "link.id"), "from": _id(lk.get("from"), "link.from"), "to": _id(lk.get("to"), "link.to")}
                extra = {k: v for k, v in lk.items() if k not in ("id", "from", "to")}
                if extra:
                    _apply_fields(link, _fields(extra, LINK_FIELDS))
                out.append({"type": "link_add", "link": link})
            elif t == "link_set":
                out.append({"type": "link_set", "id": _id(op.get("id"), "id"), "fields": _fields(op.get("fields"), LINK_FIELDS)})
            elif t == "link_remove":
                out.append({"type": "link_remove", "id": _id(op.get("id"), "id")})
            elif t == "title":
                title = _str(op.get("title"), MAX_TITLE, "title").strip()
                if not title:
                    raise OpError("title: не пустое")
                out.append({"type": "title", "title": title})
            else:
                raise OpError(f"type: одно из {', '.join(OP_TYPES)}")
        except OpError as e:
            raise OpError(f"ops[{i}] ({t}): {e}") from None
    return out


# ── дерево ───────────────────────────────────────────────────────────────────

def normalize(data: Any, title: str) -> dict:
    """Копия дерева карты; пустая карта (data = {}) получает корень с названием."""
    if isinstance(data, dict) and isinstance(data.get("id"), str) and data["id"]:
        root = copy.deepcopy(data)
        root.setdefault("children", [])
        root.setdefault("text", "")
        return root
    return {"id": "root", "text": title, "children": []}


class _Tree:
    def __init__(self, root: dict):
        self.root = root
        self.node: dict[str, dict] = {}
        self.parent: dict[str, dict | None] = {}
        stack: list[tuple[dict, dict | None]] = [(root, None)]
        while stack:
            n, p = stack.pop()
            self.node[n["id"]] = n
            self.parent[n["id"]] = p
            kids = n.get("children")
            if not isinstance(kids, list):
                n["children"] = kids = []
            for c in kids:
                stack.append((c, n))

    def subtree_ids(self, nid: str) -> set[str]:
        out, stack = set(), [self.node[nid]]
        while stack:
            n = stack.pop()
            out.add(n["id"])
            stack.extend(n.get("children") or [])
        return out

    def detach(self, nid: str) -> dict:
        n, p = self.node[nid], self.parent[nid]
        p["children"] = [c for c in p["children"] if c["id"] != nid]
        return n

    def insert(self, parent_id: str, n: dict, index: int | None) -> None:
        p = self.node[parent_id]
        kids = p["children"]
        i = len(kids) if index is None else max(0, min(index, len(kids)))
        kids.insert(i, n)
        self.parent[n["id"]] = p

    @property
    def links(self) -> list[dict]:
        lk = self.root.get("links")
        if not isinstance(lk, list):
            lk = self.root["links"] = []
        return lk


def apply_ops(root: dict, title: str, ops: list[dict]) -> tuple[dict, str, list[dict], list[dict]]:
    """Применить проверенные операции к дереву (меняет его на месте — передавайте копию).

    Возвращает (дерево, название, применённые операции, пропущенные — с причиной).
    Применённые рассылаются остальным участникам ровно в этом порядке.
    """
    tree = _Tree(root)
    applied: list[dict] = []
    skipped: list[dict] = []

    def skip(op: dict, why: str) -> None:
        skipped.append({**op, "reason": why})

    for op in ops:
        t = op["type"]
        if t == "add":
            n = copy.deepcopy(op["node"])
            if n["id"] in tree.node:
                skip(op, "узел уже есть"); continue
            if op["parent"] not in tree.node:
                skip(op, "родителя уже нет"); continue
            if len(tree.node) >= MAX_NODES:
                skip(op, f"в карте уже {MAX_NODES} узлов"); continue
            tree.insert(op["parent"], n, op["index"])
            tree.node[n["id"]] = n
        elif t == "set":
            n = tree.node.get(op["id"])
            if n is None:
                skip(op, "узла уже нет"); continue
            _apply_fields(n, op["fields"], keep=("text",))
        elif t == "remove":
            nid = op["id"]
            if nid not in tree.node:
                skip(op, "узла уже нет"); continue
            if nid == tree.root["id"]:
                skip(op, "центральную тему не удалить"); continue
            gone = tree.subtree_ids(nid)
            tree.detach(nid)
            for g in gone:
                tree.node.pop(g, None); tree.parent.pop(g, None)
            tree.root["links"] = [lk for lk in tree.links if lk.get("from") not in gone and lk.get("to") not in gone]
        elif t == "move":
            nid, pid = op["id"], op["parent"]
            if nid not in tree.node or pid not in tree.node:
                skip(op, "узла уже нет"); continue
            if nid == tree.root["id"]:
                skip(op, "центральную тему не перенести"); continue
            if pid in tree.subtree_ids(nid):
                skip(op, "нельзя перенести ветку внутрь неё самой"); continue
            n = tree.detach(nid)
            tree.insert(pid, n, op["index"])
        elif t == "link_add":
            lk = copy.deepcopy(op["link"])
            if lk["from"] == lk["to"] or lk["from"] not in tree.node or lk["to"] not in tree.node:
                skip(op, "узла уже нет"); continue
            if any(x.get("id") == lk["id"] for x in tree.links):
                skip(op, "связь уже есть"); continue
            if any({x.get("from"), x.get("to")} == {lk["from"], lk["to"]} for x in tree.links):
                skip(op, "эти узлы уже связаны"); continue
            tree.links.append(lk)
        elif t == "link_set":
            lk = next((x for x in tree.links if x.get("id") == op["id"]), None)
            if lk is None:
                skip(op, "связи уже нет"); continue
            _apply_fields(lk, op["fields"])
        elif t == "link_remove":
            if not any(x.get("id") == op["id"] for x in tree.links):
                skip(op, "связи уже нет"); continue
            tree.root["links"] = [x for x in tree.links if x.get("id") != op["id"]]
        elif t == "title":
            title = op["title"]
        applied.append(op)

    return tree.root, title, applied, skipped
