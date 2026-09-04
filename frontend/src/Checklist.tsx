// Чеклист внутри задачи: пункты с галочками. Ввёл текст → Enter → пункт добавлен, поле остаётся для следующего.
// Текст пункта правится прямо в строке (сохраняется по blur/Enter), «×» убирает пункт. Прогресс — в заголовке и на карточке.
import { useState } from "react";
import { ChecklistItem, newNodeId } from "./api";

type Props = { items: ChecklistItem[]; onChange: (items: ChecklistItem[]) => void; readOnly?: boolean };

export function checklistProgress(items?: ChecklistItem[] | null) {
  const total = items?.length ?? 0;
  const done = items?.filter((i) => i.done).length ?? 0;
  return { total, done, pct: total ? Math.round((done / total) * 100) : 0 };
}

export default function Checklist({ items, onChange, readOnly }: Props) {
  const [draft, setDraft] = useState("");
  const { total, done, pct } = checklistProgress(items);

  function add() {
    const text = draft.trim();
    if (!text) return;
    onChange([...items, { id: newNodeId(), text, done: false }]);
    setDraft("");
  }
  const patch = (id: string, p: Partial<ChecklistItem>) => onChange(items.map((i) => (i.id === id ? { ...i, ...p } : i)));
  const remove = (id: string) => onChange(items.filter((i) => i.id !== id));

  if (readOnly && total === 0) return null;

  return (
    <div className="section checklist">
      <div className="section-head">
        Чеклист
        {total > 0 && <span className="n">{done}/{total}</span>}
        <span className="spacer" />
        {total > 0 && <span className="ck-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} title={`${pct}% выполнено`}><span style={{ width: `${pct}%` }} /></span>}
      </div>
      {total > 0 && (
        <ul className="ck-list">
          {items.map((i) => (
            <li key={i.id} className={i.done ? "done" : ""}>
              <input type="checkbox" className="ck-box" checked={i.done} disabled={readOnly} aria-label={i.done ? `Снять отметку: ${i.text}` : `Выполнено: ${i.text}`}
                onChange={(e) => patch(i.id, { done: e.target.checked })} />
              <input className="ck-text" value={i.text} readOnly={readOnly} aria-label="Текст пункта"
                onChange={(e) => patch(i.id, { text: e.target.value })}
                onBlur={(e) => { if (!e.target.value.trim()) remove(i.id); }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLInputElement).blur(); } }} />
              {!readOnly && <button type="button" className="ck-del" onClick={() => remove(i.id)} title="Убрать пункт" aria-label={`Убрать пункт: ${i.text}`}>×</button>}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div className="ck-add">
          <span className="ck-plus" aria-hidden="true">+</span>
          <input className="ck-text" value={draft} placeholder={total ? "Ещё пункт… Enter — добавить" : "Разбить на шаги: пункт → Enter"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } if (e.key === "Escape") setDraft(""); }}
            onBlur={add} />
        </div>
      )}
    </div>
  );
}
