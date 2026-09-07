// Раздел «Корзина» (владелец, решение 5): удалённые направления, проекты, задачи (GET /trash) —
// восстановить, удалить навсегда, очистить. Автоочистка на сервере — через 30 дней.
import { useEffect, useState } from "react";
import { api, del, Direction, dirColor, errorText, nTasks, post, Project, showDateTime, Task, TrashEntity, TrashOut } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

type Props = { store: Store };

export default function TrashPage({ store }: Props) {
  const [trash, setTrash] = useState<TrashOut | null>(store.trash);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);   // ответ сервера на неудачное восстановление (409 и т. п.)
  const confirm = useConfirm();

  const load = async () => { try { setTrash(await api<TrashOut>("/trash")); setFailed(false); } catch (e) { setFailed(true); store.setError(errorText(e)); } };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const after = async () => { await Promise.all([load(), store.reload()]); };
  async function restore(kind: TrashEntity, id: number) {
    setBusy(`${kind}${id}`); setNote(null);
    try { await post(`/${kind}s/${id}/restore`, {}); await after(); }
    catch (e) { setNote(errorText(e)); } finally { setBusy(null); }
  }
  async function purge(kind: TrashEntity, id: number, name: string) {
    const label = { direction: "направление", project: "проект", task: "задачу" }[kind];
    if (!(await confirm(`${cap(label)} «${name}» будет удалён${kind === "task" ? "а" : ""} навсегда — без возможности вернуть.`, { title: "Удалить навсегда?", danger: true, okLabel: "Удалить навсегда" }))) return;
    setBusy(`${kind}${id}`); setNote(null);
    try { await del(`/trash/${kind}/${id}`); await after(); } catch (e) { setNote(errorText(e)); } finally { setBusy(null); }
  }
  async function clear() {
    if (!(await confirm(`Всё содержимое корзины (${summary(trash)}) будет удалено навсегда.`, { title: "Очистить корзину?", danger: true, okLabel: "Очистить", typeToConfirm: "корзина" }))) return;
    setBusy("all"); setNote(null);
    try { await del("/trash"); await after(); } catch (e) { setNote(errorText(e)); } finally { setBusy(null); }
  }

  const total = trash ? trash.directions.length + trash.projects.length + trash.tasks.length : 0;
  const dirName = (id: number | null | undefined) => store.directions.find((d) => d.id === id)?.name ?? trash?.directions.find((d) => d.id === id)?.name;

  return (
    <div className="page trash-page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2><span className="swatch trash-swatch" />Корзина</h2>
        <span className="spacer" />
        {total > 0 && <button className="btn danger sm" onClick={clear} disabled={busy === "all"}>Очистить корзину…</button>}
      </div>
      <p className="hint">Удалённое хранится здесь 30 дней, потом стирается. Направление возвращается вместе со своими проектами; проект из удалённого направления — только после направления. Доступ коллег при удалении закрывается и сам не возвращается.</p>
      {note && <div className="trash-note" role="alert">{note}<button className="btn ghost sm" onClick={() => setNote(null)} aria-label="Скрыть">×</button></div>}

      {trash === null ? (
        <div className="state" style={{ flex: "none", padding: "40px 20px" }}>{failed ? <><h3>Корзина недоступна</h3><p>Сервер не ответил на запрос корзины.</p><button className="btn" onClick={load}>Повторить</button></> : <span className="mono">загрузка…</span>}</div>
      ) : total === 0 ? (
        <div className="state" style={{ flex: "none", padding: "60px 20px" }}><h3>Корзина пуста</h3><p>Удалённые направления, проекты и задачи появятся здесь — их можно будет вернуть.</p></div>
      ) : (
        <>
          <Group title="Направления" items={trash.directions} render={(d: Direction) => (
            <TrashRow key={d.id} color={dirColor(d)} name={d.name} meta={`удалено ${showDateTime(d.deleted_at)} · проекты внутри вернутся вместе с ним`}
              busy={busy === `direction${d.id}`} onRestore={() => restore("direction", d.id)} onPurge={() => purge("direction", d.id, d.name)} />
          )} />
          <Group title="Проекты" items={trash.projects} render={(p: Project) => {
            const dirInTrash = trash.directions.some((d) => d.id === p.direction_id);
            return <TrashRow key={p.id} color={p.color || "var(--line-strong)"} name={p.name} meta={`${dirName(p.direction_id) ?? "направление"} · удалён ${showDateTime(p.deleted_at)}${dirInTrash ? " · направление тоже в корзине — сначала верните его" : ""}`}
              busy={busy === `project${p.id}`} onRestore={() => restore("project", p.id)} onPurge={() => purge("project", p.id, p.name)} />;
          }} />
          <Group title="Задачи" items={trash.tasks} render={(t: Task) => (
            <TrashRow key={t.id} color={t.directions[0] ? dirColor(t.directions[0]) : "var(--line-strong)"} name={t.title} meta={`#${t.id} · ${t.directions.map((d) => d.name).join(", ") || "без направления"} · удалена ${showDateTime(t.deleted_at)}`}
              busy={busy === `task${t.id}`} onRestore={() => restore("task", t.id)} onPurge={() => purge("task", t.id, t.title)} />
          )} />
        </>
      )}
    </div>
  );
}

function Group<T>({ title, items, render }: { title: string; items: T[]; render: (x: T) => React.ReactNode }) {
  if (!items.length) return null;
  return <section className="trash-group"><h3 className="arch-title">{title} <span className="n mono">{items.length}</span></h3>{items.map(render)}</section>;
}

function TrashRow({ color, name, meta, busy, onRestore, onPurge }: { color: string; name: string; meta: string; busy: boolean; onRestore: () => void; onPurge: () => void }) {
  return (
    <div className="arch-row" style={{ ["--dir" as string]: color }}>
      <span className="arch-name"><span className="swatch" style={{ background: color }} />{name}</span>
      <span className="hint">{meta}</span>
      <span className="row">
        <button className="btn primary sm" onClick={onRestore} disabled={busy}>Восстановить</button>
        <button className="btn danger sm" onClick={onPurge} disabled={busy} title="Удалить навсегда">Удалить навсегда…</button>
      </span>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
function summary(t: TrashOut | null) {
  if (!t) return "";
  const parts: string[] = [];
  if (t.directions.length) parts.push(`${t.directions.length} напр.`);
  if (t.projects.length) parts.push(`${t.projects.length} пр.`);
  if (t.tasks.length) parts.push(nTasks(t.tasks.length));
  return parts.join(", ");
}
