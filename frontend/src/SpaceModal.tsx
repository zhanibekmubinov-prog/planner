// Перенос направления между слоями (v1.7).
//
// В «Организацию» переносим сразу — скрывать там нечего. В «Личное» сначала показываем, кто
// сейчас видит направление: слой — это раскладка, а не замок, и владелец должен сам решить,
// закрывать доступ или оставить (решение владельца 2026-10-05). Молча доступ не снимаем
// и молча не оставляем — спрашиваем.
import { useEffect, useState } from "react";
import { api, Direction, errorText, PERMISSION_LABEL, put, SpaceAccessRow, SpacePreview } from "./api";
import { useEscape } from "./layers";
import { Space, SPACE_LABEL } from "./spaces";
import { Store } from "./store";

const VIA: Record<string, string> = { direction: "направление", project: "проект", task: "задача" };

export default function SpaceModal({ store, direction, to, onClose }: { store: Store; direction: Direction; to: Space; onClose: () => void }) {
  const [people, setPeople] = useState<SpaceAccessRow[] | null>(null);
  const [revoke, setRevoke] = useState(false);
  const [busy, setBusy] = useState(false);
  useEscape(onClose);

  useEffect(() => {
    if (to !== "personal") { setPeople([]); return; }
    let alive = true;
    api<SpacePreview>(`/directions/${direction.id}/space-preview`)
      .then((r) => { if (alive) setPeople(r.people); })
      .catch(() => { if (alive) setPeople([]); });
    return () => { alive = false; };
  }, [direction.id, to]);

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      await put<Direction>(`/directions/${direction.id}/space`, { space: to, revoke_shares: revoke });
      await Promise.all([store.reloadDirections(), store.reloadShared()]);
      if (revoke) await store.reloadTasks();
      store.setSpace(to);        // переходим туда, куда перенесли — иначе направление «исчезнет» на глазах
      onClose();
    } catch (e) { store.setError(errorText(e)); setBusy(false); }
  }

  const shown = people ?? [];
  const loading = people === null;

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Перенести направление в другой слой">
        <h3>Перенести «{direction.name}» в «{SPACE_LABEL[to]}»</h3>

        {to === "org" ? (
          <p className="hint">Направление уйдёт на вкладку «Организация» вместе со своими проектами, задачами и майндмапами. Доступ коллег не меняется.</p>
        ) : loading ? (
          <p className="hint">Смотрю, кому открыто…</p>
        ) : shown.length === 0 ? (
          <p className="hint">Направление никому не открыто — после переноса его видите только вы.</p>
        ) : (
          <>
            <p className="hint">Сейчас это видят {shown.length} чел. Слой сам по себе доступ не закрывает — выберите, что сделать.</p>
            <div className="space-people">
              {shown.map((p) => (
                <div className="row-person" key={p.user_id}>
                  <b>{p.name}</b>
                  <span className="email">{p.email}</span>
                  <span className="perm">{PERMISSION_LABEL[p.permission]} · через {VIA[p.via] ?? p.via}</span>
                </div>
              ))}
            </div>
            <label className="check">
              <input type="checkbox" checked={revoke} onChange={(e) => setRevoke(e.target.checked)} />
              Закрыть доступ всем — направление, его проекты и задачи станут видны только мне
            </label>
          </>
        )}

        <div className="foot">
          <button className="btn" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn primary" onClick={save} disabled={busy || loading}>
            {to === "personal" && revoke ? "Перенести и закрыть доступ" : "Перенести"}
          </button>
        </div>
      </div>
    </div>
  );
}
