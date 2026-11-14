"""v1.8 — живой режим майндмапа: правки соседей и «кто сейчас на карте» без перезагрузки.

Канал — WebSocket `/api/mindmaps/{id}/live`. Он только РАЗДАЁТ: правки по-прежнему идут
обычным REST (`POST /mindmaps/{id}/ops`) — там права, проверка и сохранение. После
сохранения роутер зовёт `hub.publish(...)`, и пачка уходит всем, кто держит карту открытой.

Вход: браузер не умеет ставить заголовок Authorization у WebSocket, а токен в адресе попал
бы в журналы прокси. Поэтому первое сообщение клиента — `{"type": "auth", "token": "<сессия>"}`,
без него за 10 с соединение закрывается. Доступ перепроверяется раз в минуту: отозвали —
соединение закрывается с кодом 4404.

Коды закрытия: 4401 — сессия недействительна, 4404 — карты нет или она вам больше не видна.
Клиент на них не переподключается.

Сообщения сервера:
  hello    {sid, version, access, peers}         — сразу после входа
  presence {peers}                                — кто на карте и какой узел у кого выбран
  ops      {version, batch, by, ops, title}       — принятая пачка операций
  snapshot {version, title, data, direction_id, task_id} — карту заменили целиком (PUT)
  meta     {direction_id, task_id}                — поменяли привязку
  deleted  {}                                     — карту удалили
Сообщения клиента: auth, focus {node, editing}, ping.

Комнаты живут в памяти процесса: бэкенд один (uvicorn без --workers, как и для билетов
входа из платформы, v1.5). Станет несколько процессов — рассылку переносить на
Postgres LISTEN/NOTIFY.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from . import models
from .auth import user_from_session
from .db import SessionLocal
from .scope import WRITE, mindmap_access

router = APIRouter(tags=["mindmaps"])
log = logging.getLogger("live")

AUTH_TIMEOUT_SEC = 10
RECHECK_SEC = 60.0          # как часто перепроверять доступ открытого соединения
CLOSE_UNAUTHORIZED, CLOSE_GONE = 4401, 4404
# цвета участников: различимы между собой и не похожи на ржавый акцент планнера
PEER_COLORS = ("#2F6FED", "#0E9F6E", "#7C3AED", "#D97706", "#0891B2", "#BE185D", "#65A30D", "#DC2626")


def peer_color(user_id: int) -> str:
    return PEER_COLORS[user_id % len(PEER_COLORS)]


@dataclass(eq=False)
class Peer:
    sid: str
    user_id: int
    name: str
    ws: WebSocket
    loop: asyncio.AbstractEventLoop
    can_edit: bool
    node: str | None = None
    editing: bool = False

    def public(self) -> dict:
        return {"sid": self.sid, "user_id": self.user_id, "name": self.name, "color": peer_color(self.user_id),
                "node": self.node, "editing": self.editing}


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[int, dict[str, Peer]] = {}

    def peers(self, map_id: int) -> list[dict]:
        return [p.public() for p in self.rooms.get(map_id, {}).values()]

    def join(self, map_id: int, peer: Peer) -> None:
        self.rooms.setdefault(map_id, {})[peer.sid] = peer

    def leave(self, map_id: int, sid: str) -> None:
        room = self.rooms.get(map_id)
        if room is None:
            return
        room.pop(sid, None)
        if not room:
            self.rooms.pop(map_id, None)

    async def _send(self, map_id: int, peer: Peer, msg: dict) -> None:
        try:
            await peer.ws.send_json(msg)
        except Exception:  # noqa: BLE001 — соединение уже закрыто: просто забываем участника
            self.leave(map_id, peer.sid)

    def _deliver(self, map_id: int, peer: Peer, msg: dict) -> asyncio.Future | None:
        """Отправить в цикл событий участника. Из чужого потока/цикла — через run_coroutine_threadsafe."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is peer.loop:
            return asyncio.ensure_future(self._send(map_id, peer, msg))
        if peer.loop.is_closed():
            self.leave(map_id, peer.sid)
            return None
        try:
            asyncio.run_coroutine_threadsafe(self._send(map_id, peer, msg), peer.loop)
        except RuntimeError:
            self.leave(map_id, peer.sid)
        return None

    async def broadcast(self, map_id: int, msg: dict, exclude: str | None = None) -> None:
        mine = [f for p in list(self.rooms.get(map_id, {}).values()) if p.sid != exclude
                for f in [self._deliver(map_id, p, msg)] if f is not None]
        if mine:
            await asyncio.gather(*mine, return_exceptions=True)

    def publish(self, map_id: int, msg: dict) -> None:
        """Разослать всем, кто держит карту открытой. Зовётся из синхронных обработчиков (поток пула)."""
        for p in list(self.rooms.get(map_id, {}).values()):
            self._deliver(map_id, p, msg)

    def presence(self, map_id: int) -> dict:
        return {"type": "presence", "peers": self.peers(map_id)}


hub = Hub()


def _check(token: object, map_id: int) -> int | tuple[int, str, str, int]:
    """Кто подключается и что ему можно. Код закрытия — если нельзя."""
    if not isinstance(token, str) or not token:
        return CLOSE_UNAUTHORIZED
    db = SessionLocal()
    try:
        try:
            user = user_from_session(db, token)
        except HTTPException:
            return CLOSE_UNAUTHORIZED
        m = db.get(models.MindMap, map_id)
        acc = mindmap_access(db, user, m) if m else None
        if not acc:
            return CLOSE_GONE
        return user.id, user.name, acc, int(m.version or 0)
    finally:
        db.close()


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:  # noqa: BLE001
        pass


async def _watch(ws: WebSocket, peer: Peer, map_id: int, token: str) -> None:
    """Раз в RECHECK_SEC перепроверить доступ: отозвали или удалили карту — закрыть соединение."""
    while True:
        await asyncio.sleep(RECHECK_SEC)
        res = await run_in_threadpool(_check, token, map_id)
        if isinstance(res, int):
            await _close(ws, res)
            return
        peer.can_edit = res[2] in WRITE


@router.websocket("/api/mindmaps/{map_id}/live")
async def live(ws: WebSocket, map_id: int) -> None:
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SEC))
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, RuntimeError):
        await _close(ws, CLOSE_UNAUTHORIZED)
        return
    token = first.get("token") if isinstance(first, dict) and first.get("type") == "auth" else None
    res = await run_in_threadpool(_check, token, map_id)
    if isinstance(res, int):
        await _close(ws, res)
        return
    user_id, name, access, version = res
    peer = Peer(sid=secrets.token_hex(6), user_id=user_id, name=name, ws=ws, loop=asyncio.get_running_loop(),
                can_edit=access in WRITE)
    hub.join(map_id, peer)
    watcher = asyncio.create_task(_watch(ws, peer, map_id, token))  # type: ignore[arg-type]
    try:
        await ws.send_json({"type": "hello", "sid": peer.sid, "version": version, "access": access, "peers": hub.peers(map_id)})
        await hub.broadcast(map_id, hub.presence(map_id), exclude=peer.sid)
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except ValueError:
                continue    # мусор вместо JSON — игнорируем, соединение не рвём
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if t == "focus":
                node = msg.get("node")
                peer.node = node if isinstance(node, str) and 0 < len(node) <= 64 else None
                peer.editing = bool(msg.get("editing")) and peer.node is not None and peer.can_edit
                await hub.broadcast(map_id, hub.presence(map_id), exclude=peer.sid)
            elif t == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()
        hub.leave(map_id, peer.sid)
        await hub.broadcast(map_id, hub.presence(map_id))
