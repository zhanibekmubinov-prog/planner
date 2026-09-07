import { useRef, useState } from "react";
import { Direction, DIRECTION_COLORS, DIRECTION_STATUS_LABEL, DirectionIn, DirectionStatus, errorText, post, put } from "./api";
import { useConfirm } from "./confirm";
import { useDeletion } from "./deletion";
import { useDirtyFlag, useEscape } from "./layers";
import { Store } from "./store";

type Props = { store: Store; direction: Direction | null; onClose: () => void; onSaved: (d: Direction) => void; onDeleted: () => void };

export default function DirectionModal({ store, direction, onClose, onSaved, onDeleted }: Props) {
  const initial: DirectionIn = {
    name: direction?.name ?? "", description: direction?.description ?? null, goal: direction?.goal ?? null,
    color: direction?.color ?? DIRECTION_COLORS[store.directions.length % DIRECTION_COLORS.length], status: direction?.status ?? "active",
  };
  const [form, setForm] = useState<DirectionIn>(initial);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);   // защита от Enter-Enter / двойного клика (С2): состояние обновляется позже, чем второй вызов
  const confirm = useConfirm();
  const { deleteDirection } = useDeletion(store);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  useDirtyFlag(dirty);

  // Н4: закрыть с правками — только после вопроса
  async function close() {
    if (busyRef.current) return;
    if (dirty && !(await confirm("Введённое не сохранится.", { title: "Закрыть без сохранения?", okLabel: "Закрыть" }))) return;
    onClose();
  }
  useEscape(() => void close());

  async function save() {
    if (busyRef.current || !form.name.trim()) return;
    busyRef.current = true; setBusy(true);
    try {
      const body = { ...form, name: form.name.trim(), goal: form.goal?.trim() || null, description: form.description?.trim() || null };
      if (direction && body.status === "archived" && direction.status !== "archived"
        && !(await confirm(`Направление «${body.name}» уйдёт из левой панели и с карты. Вернуть — из раздела «Архив».`, { title: "Убрать в архив?", okLabel: "В архив" }))) return;
      const saved = direction ? await put<Direction>(`/directions/${direction.id}`, body) : await post<Direction>("/directions", body);
      await store.reloadDirections();
      if (direction) await store.reloadTasks();
      onSaved(saved);
    } catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  async function remove() {
    if (!direction || busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try { if (await deleteDirection(direction)) onDeleted(); }
    finally { busyRef.current = false; setBusy(false); }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) void close(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={direction ? "Изменить направление" : "Новое направление"}>
        <h3>{direction ? "Направление" : "Новое направление"}</h3>
        <div className="field">
          <label>Название</label>
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Например, «Закуп» или «Развитие команды»" autoFocus
            onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
        </div>
        <div className="field">
          <label>Цель</label>
          <input className="input" value={form.goal ?? ""} onChange={(e) => setForm({ ...form, goal: e.target.value })} placeholder="Чего добиваемся по этому направлению" />
        </div>
        <div className="field">
          <label>Описание</label>
          <textarea className="textarea" value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
        <div className="grid2">
          <div className="field">
            <label>Цвет</label>
            <div className="swatches">
              {DIRECTION_COLORS.map((c) => (
                <button key={c} className={form.color === c ? "on" : ""} style={{ background: c }} onClick={() => setForm({ ...form, color: c })} aria-label={c} />
              ))}
            </div>
          </div>
          <div className="field">
            <label>Статус</label>
            <select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as DirectionStatus })}>
              {(Object.keys(DIRECTION_STATUS_LABEL) as DirectionStatus[]).map((s) => <option key={s} value={s}>{DIRECTION_STATUS_LABEL[s]}</option>)}
            </select>
          </div>
        </div>
        <div className="foot">
          {direction && (!direction.access || direction.access === "owner") && <button className="btn danger" onClick={remove} disabled={busy} style={{ marginRight: "auto" }}>Удалить…</button>}
          <button className="btn" onClick={() => void close()} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !form.name.trim()}>{direction ? "Сохранить" : "Создать"}</button>
        </div>
      </div>
    </div>
  );
}
