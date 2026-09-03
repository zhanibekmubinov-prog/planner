import { useState } from "react";
import { del, Direction, DIRECTION_COLORS, DIRECTION_STATUS_LABEL, DirectionIn, DirectionStatus, post, put } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

type Props = { store: Store; direction: Direction | null; onClose: () => void; onSaved: (d: Direction) => void; onDeleted: () => void };

export default function DirectionModal({ store, direction, onClose, onSaved, onDeleted }: Props) {
  const [form, setForm] = useState<DirectionIn>({
    name: direction?.name ?? "", description: direction?.description ?? null, goal: direction?.goal ?? null,
    color: direction?.color ?? DIRECTION_COLORS[store.directions.length % DIRECTION_COLORS.length], status: direction?.status ?? "active",
  });
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();

  async function save() {
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      const body = { ...form, name: form.name.trim(), goal: form.goal?.trim() || null, description: form.description?.trim() || null };
      const saved = direction ? await put<Direction>(`/directions/${direction.id}`, body) : await post<Direction>("/directions", body);
      await store.reloadDirections();
      if (direction) await store.reloadTasks();
      onSaved(saved);
    } catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }
  async function remove() {
    if (!direction) return;
    if (!(await confirm(`Направление «${direction.name}» будет удалено. Задачи останутся, но потеряют привязку к нему.`, { danger: true, okLabel: "Удалить направление" }))) return;
    setBusy(true);
    try { await del(`/directions/${direction.id}`); await store.reloadDirections(); await store.reloadTasks(); onDeleted(); }
    catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
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
          {direction && <button className="btn danger" onClick={remove} disabled={busy} style={{ marginRight: "auto" }}>Удалить</button>}
          <button className="btn" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || !form.name.trim()}>{direction ? "Сохранить" : "Создать"}</button>
        </div>
      </div>
    </div>
  );
}
