// v1.8 — совместная правка майндмапа: очередь своих правок + живой канал с чужими.
//
// Как держится согласие с сервером (одна и та же схема у всех участников):
//   base     — последняя подтверждённая сервером версия карты (номер version);
//   inflight — своя пачка, которая сейчас летит на сервер (не больше одной: порядок своих правок важен);
//   pending  — свои правки, ещё не отправленные (подряд идущие правки одного узла склеиваются).
// На экране — base + inflight + pending. Чужая пачка из живого канала с номером base+1 накладывается на base;
// пропуск номера — перечитываем карту целиком. Ответ сервера на свою пачку приносит всю карту — его и берём
// за base, если он не старее уже известного. Применение пачки повторно ничего не меняет (mindmapOps.ts),
// поэтому своя пачка, пришедшая и ответом, и из канала, не задваивается.
//
// Нет связи — пачка возвращается в начало очереди и уходит позже (1, 2, 4… до 30 с). Сервер отказал (4xx) —
// правки не принять: сообщаем и перечитываем карту.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE, ApiError, errorText, getSession, MindMap, MindNode, MindOp, MindOpsOut, MindPeer, post } from "./api";
import { applyOps, enqueue } from "./mindmapOps";

type Base = { tree: MindNode; title: string; version: number };
type Remote = Partial<Pick<MindMap, "title" | "data" | "version" | "direction_id" | "task_id">>;
type Opts = {
  map: MindMap;
  canEdit: boolean;
  onRemote?: (patch: Remote) => void;   // карта поменялась (своё подтверждение или чужая правка) — обновить список
  onDeleted?: () => void;               // карту удалил владелец
  onError: (msg: string) => void;
};

export const SEND_EVERY_MS = 300;       // правки уходят не чаще — набор текста виден соседям почти сразу
const PING_MS = 25_000;                 // прокси Railway рвёт молчащие соединения

export function liveUrl(mapId: number): string | null {
  const base = API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  return base ? `${base.replace(/^http/, "ws")}/api/mindmaps/${mapId}/live` : null;
}

const rootOf = (m: Pick<MindMap, "data" | "title">): MindNode => (m.data?.id ? m.data : { id: "root", text: m.title, children: [] });
const newBatchId = () => Math.random().toString(36).slice(2, 12);

export function useMindmapSync({ map, canEdit, onRemote, onDeleted, onError }: Opts) {
  const base = useRef<Base>({ tree: rootOf(map), title: map.title, version: map.version ?? 0 });
  const inflight = useRef<{ batch: string; ops: MindOp[] } | null>(null);
  const pending = useRef<MindOp[]>([]);
  const busy = useRef(false);
  const timer = useRef<number | null>(null);
  const retry = useRef(0);
  const cb = useRef({ onRemote, onDeleted, onError, canEdit });
  cb.current = { onRemote, onDeleted, onError, canEdit };

  const [doc, setDoc] = useState(() => ({ tree: base.current.tree, title: base.current.title }));
  const [queued, setQueued] = useState({ dirty: false, saving: false });
  const [offline, setOffline] = useState(false);
  const [peers, setPeers] = useState<MindPeer[]>([]);
  const [live, setLive] = useState(false);
  const sid = useRef<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const ready = useRef(false);            // сервер принял вход (пришёл hello) — до этого в канал только auth
  const lastFocus = useRef("");
  const wantFocus = useRef<{ node: string | null; editing: boolean }>({ node: null, editing: false });

  const recompute = useCallback(() => {
    let d = { tree: base.current.tree, title: base.current.title };
    if (inflight.current) d = applyOps(d, inflight.current.ops);
    d = applyOps(d, pending.current);
    setDoc(d);
    setQueued({ dirty: pending.current.length > 0 || !!inflight.current, saving: !!inflight.current });
  }, []);

  const setBase = useCallback((next: Base, extra: Remote = {}) => {
    base.current = next;
    recompute();
    cb.current.onRemote?.({ title: next.title, data: next.tree, version: next.version, ...extra });
  }, [recompute]);

  const resync = useCallback(async () => {
    try {
      const m = await api<MindMap>(`/mindmaps/${map.id}`);
      setBase({ tree: rootOf(m), title: m.title, version: m.version ?? 0 }, { direction_id: m.direction_id, task_id: m.task_id });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) cb.current.onDeleted?.();
    }
  }, [map.id, setBase]);

  const send = useCallback(async (): Promise<void> => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    if (busy.current || !pending.current.length) return;
    busy.current = true;
    const batch = newBatchId();
    inflight.current = { batch, ops: pending.current };
    pending.current = [];
    recompute();
    try {
      const res = await post<MindOpsOut>(`/mindmaps/${map.id}/ops`, { batch, ops: inflight.current.ops });
      if (inflight.current?.batch === batch) inflight.current = null;
      retry.current = 0; setOffline(false);
      if (res.version >= base.current.version) setBase({ tree: res.data, title: res.title, version: res.version });
      else recompute();
    } catch (e) {
      const mine = inflight.current?.batch === batch ? inflight.current.ops : [];
      inflight.current = null;
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        // сервер правку не примет и при повторе (нет права, карта удалена, баг формы) — показываем и перечитываем
        cb.current.onError(errorText(e));
        void resync();
      } else {
        pending.current = enqueue(mine, pending.current);   // нет связи — повторим позже, в том же порядке
        setOffline(true);
        busy.current = false;
        recompute();
        timer.current = window.setTimeout(() => void send(), Math.min(30_000, 1000 * 2 ** retry.current++));
        return;
      }
      recompute();
    } finally {
      busy.current = false;
    }
    if (pending.current.length && !timer.current) timer.current = window.setTimeout(() => void send(), SEND_EVERY_MS);
  }, [map.id, recompute, resync, setBase]);

  /** Свои правки: сразу на экран, на сервер — не чаще SEND_EVERY_MS. */
  const apply = useCallback((ops: MindOp[]) => {
    if (!cb.current.canEdit || !ops.length) return;
    pending.current = enqueue(pending.current, ops);
    recompute();
    if (!timer.current && !busy.current) timer.current = window.setTimeout(() => void send(), SEND_EVERY_MS);
  }, [recompute, send]);

  /** Что у меня выбрано — соседи видят рамку моего цвета на этом узле. */
  const focus = useCallback((node: string | null, editing: boolean) => {
    wantFocus.current = { node, editing };
    const key = `${node}|${editing}`;
    if (key === lastFocus.current || !ready.current || ws.current?.readyState !== 1) return;
    lastFocus.current = key;
    ws.current.send(JSON.stringify({ type: "focus", node, editing }));
  }, []);

  // живой канал
  useEffect(() => {
    const url = liveUrl(map.id);
    if (!url || !getSession() || typeof WebSocket === "undefined") return;
    let stop = false; let attempt = 0; let reconnect: number | null = null;
    const handle = (m: Record<string, unknown>) => {
      switch (m.type) {
        case "hello":
          sid.current = m.sid as string; attempt = 0; setLive(true); setPeers(m.peers as MindPeer[]);
          ready.current = true;
          lastFocus.current = "";   // сервер (в т. ч. после переподключения) ещё не знает мой выбор — сообщаем
          if (wantFocus.current.node) focus(wantFocus.current.node, wantFocus.current.editing);
          if ((m.version as number) !== base.current.version) void resync();
          break;
        case "presence": setPeers(m.peers as MindPeer[]); break;
        case "ops": {
          const v = m.version as number;
          if (inflight.current?.batch === m.batch) inflight.current = null;   // своя пачка — уже в base после этого шага
          if (v <= base.current.version) { recompute(); break; }
          if (v !== base.current.version + 1) { void resync(); break; }
          const next = applyOps({ tree: base.current.tree, title: base.current.title }, m.ops as MindOp[]);
          setBase({ tree: next.tree, title: (m.title as string) ?? next.title, version: v });
          break;
        }
        case "snapshot":
          setBase({ tree: rootOf({ data: m.data as MindNode, title: m.title as string }), title: m.title as string, version: m.version as number },
                  { direction_id: m.direction_id as number | null, task_id: m.task_id as number | null });
          break;
        case "meta": cb.current.onRemote?.({ direction_id: m.direction_id as number | null, task_id: m.task_id as number | null }); break;
        case "deleted": cb.current.onDeleted?.(); break;
      }
    };
    const connect = () => {
      const s = new WebSocket(url);
      ws.current = s;
      s.onopen = () => s.send(JSON.stringify({ type: "auth", token: getSession() }));
      s.onmessage = (ev) => { try { handle(JSON.parse(String(ev.data))); } catch { /* не JSON — пропускаем */ } };
      s.onclose = (ev) => {
        if (ws.current === s) ws.current = null;
        ready.current = false;
        setLive(false); setPeers([]);
        if (stop) return;
        if (ev.code === 4404) { void resync(); return; }   // доступ закрыли или карту удалили
        if (ev.code === 4401) return;                       // сессия кончилась — REST сам уведёт на вход
        reconnect = window.setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempt++));
      };
    };
    connect();
    const ping = window.setInterval(() => { if (ws.current?.readyState === 1) ws.current.send('{"type":"ping"}'); }, PING_MS);
    return () => {
      stop = true;
      window.clearInterval(ping);
      if (reconnect) window.clearTimeout(reconnect);
      ws.current?.close(); ws.current = null;
    };
  }, [map.id, recompute, resync, setBase, focus]);

  // уход со страницы — досылаем то, что не успел таймер (как С5 у прежнего автосохранения)
  useEffect(() => () => { void send(); }, [send]);

  return {
    tree: doc.tree, title: doc.title, apply, focus, flush: send,
    dirty: queued.dirty, saving: queued.saving, offline, live, peers, sid: sid.current,
  };
}
