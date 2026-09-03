// Справочники: Люди и Тулы. Простые таблицы с редактированием на месте.
import { useState } from "react";
import { del, Person, PersonIn, post, put, Tool, ToolIn, TOOL_TYPE_LABEL, ToolType } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

export function PeoplePage({ store }: { store: Store }) {
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const confirm = useConfirm();

  async function save(form: PersonIn, id?: number) {
    try {
      if (id) await put(`/people/${id}`, form); else await post("/people", form);
      await store.reloadPeople(); setEditing(null);
    } catch (e) { store.setError(String(e)); }
  }
  async function remove(p: Person) {
    if (!(await confirm(`Удалить ${p.name} из списка? Если на этого человека есть поручения, удаление не пройдёт.`, { danger: true }))) return;
    try { await del(`/people/${p.id}`); await store.reloadPeople(); } catch (e) { store.setError(String(e)); }
  }

  return (
    <div className="page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2>Люди</h2><span className="spacer" />
        <button className="btn primary" onClick={() => setEditing("new")}>+ Человек</button>
      </div>
      <p className="hint">Кому вы делегируете задачи. Telegram chat id и email нужны для напоминаний исполнителям (шаг 4).</p>
      {editing === "new" && <PersonForm onCancel={() => setEditing(null)} onSave={(f) => save(f)} />}
      {store.people.length === 0 && editing !== "new" ? (
        <div className="state"><h3>Список пуст</h3><p>Добавьте людей, которым будете поручать задачи.</p></div>
      ) : (
        <div className="table">
          <div className="trow head"><span>Имя</span><span className="hide-m">Telegram</span><span className="hide-m">Email</span><span /></div>
          {store.people.map((p) => editing !== "new" && editing?.id === p.id ? (
            <div key={p.id} className="trow editing"><PersonForm person={p} onCancel={() => setEditing(null)} onSave={(f) => save(f, p.id)} /></div>
          ) : (
            <div key={p.id} className="trow">
              <span><div>{p.name}</div>{p.note && <div className="sub">{p.note}</div>}</span>
              <span className="mono hide-m">{p.telegram_chat_id || "—"}</span>
              <span className="hide-m">{p.email || "—"}</span>
              <span className="row"><button className="btn ghost sm" onClick={() => setEditing(p)}>Изменить</button><button className="btn danger sm" onClick={() => remove(p)}>×</button></span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PersonForm({ person, onSave, onCancel }: { person?: Person; onSave: (f: PersonIn) => void; onCancel: () => void }) {
  const [f, setF] = useState<PersonIn>({ name: person?.name ?? "", telegram_chat_id: person?.telegram_chat_id ?? "", email: person?.email ?? "", note: person?.note ?? "" });
  const norm = (): PersonIn => ({ name: f.name.trim(), telegram_chat_id: f.telegram_chat_id?.trim() || null, email: f.email?.trim() || null, note: f.note?.trim() || null });
  return (
    <div className="inline-form">
      <div className="grid2">
        <div className="field"><label>Имя</label><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus /></div>
        <div className="field"><label>Telegram chat id</label><input className="input mono" value={f.telegram_chat_id ?? ""} onChange={(e) => setF({ ...f, telegram_chat_id: e.target.value })} placeholder="123456789" /></div>
        <div className="field"><label>Email</label><input className="input" type="email" value={f.email ?? ""} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        <div className="field"><label>Заметка</label><input className="input" value={f.note ?? ""} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="Роль, отдел" /></div>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn sm" onClick={onCancel}>Отмена</button>
        <button className="btn primary sm" onClick={() => onSave(norm())} disabled={!f.name.trim()}>Сохранить</button>
      </div>
    </div>
  );
}

export function ToolsPage({ store }: { store: Store }) {
  const [editing, setEditing] = useState<Tool | "new" | null>(null);
  const confirm = useConfirm();

  const usage = (id: number) => store.tasks.filter((t) => t.tools.some((x) => x.id === id));

  async function save(form: Omit<ToolIn, "task_ids" | "direction_ids">, tool?: Tool) {
    try {
      const body: ToolIn = { ...form, task_ids: tool ? usage(tool.id).map((t) => t.id) : [], direction_ids: [] };
      if (tool) await put(`/tools/${tool.id}`, body); else await post("/tools", body);
      await store.reloadTools(); await store.reloadTasks(); setEditing(null);
    } catch (e) { store.setError(String(e)); }
  }
  async function remove(t: Tool) {
    if (!(await confirm(`Тул «${t.name}» будет удалён и отвязан от всех задач.`, { danger: true, okLabel: "Удалить тул" }))) return;
    try { await del(`/tools/${t.id}`); await store.reloadTools(); await store.reloadTasks(); } catch (e) { store.setError(String(e)); }
  }

  return (
    <div className="page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2>Тулы</h2><span className="spacer" />
        <button className="btn primary" onClick={() => setEditing("new")}>+ Тул</button>
      </div>
      <p className="hint">Таблицы, боты и документы, через которые ведутся задачи. Позже агенты будут читать их и отчитываться о заполнении.</p>
      {editing === "new" && <ToolForm onCancel={() => setEditing(null)} onSave={(f) => save(f)} />}
      {store.tools.length === 0 && editing !== "new" ? (
        <div className="state"><h3>Тулов пока нет</h3><p>Добавьте первый — например, реестр в Google Sheets или Excel на SharePoint.</p></div>
      ) : (
        <div className="table">
          <div className="trow head"><span>Название</span><span className="hide-m">Тип</span><span className="hide-m">Где используется</span><span /></div>
          {store.tools.map((t) => editing !== "new" && editing?.id === t.id ? (
            <div key={t.id} className="trow editing"><ToolForm tool={t} onCancel={() => setEditing(null)} onSave={(f) => save(f, t)} /></div>
          ) : (
            <div key={t.id} className="trow">
              <span>
                <div>{t.url ? <a href={t.url} target="_blank" rel="noreferrer">{t.name} ↗</a> : t.name}</div>
                {t.note && <div className="sub">{t.note}</div>}
              </span>
              <span className="hide-m">{TOOL_TYPE_LABEL[t.type]}</span>
              <span className="sub hide-m">{usage(t.id).length ? usage(t.id).map((x) => x.title).join(", ") : "—"}</span>
              <span className="row"><button className="btn ghost sm" onClick={() => setEditing(t)}>Изменить</button><button className="btn danger sm" onClick={() => remove(t)}>×</button></span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolForm({ tool, onSave, onCancel }: { tool?: Tool; onSave: (f: Omit<ToolIn, "task_ids" | "direction_ids">) => void; onCancel: () => void }) {
  const [name, setName] = useState(tool?.name ?? "");
  const [type, setType] = useState<ToolType>(tool?.type ?? "google_sheet");
  const [url, setUrl] = useState(tool?.url ?? "");
  const [note, setNote] = useState(tool?.note ?? "");
  const [ref, setRef] = useState(tool?.source_ref ? JSON.stringify(tool.source_ref) : "");
  const [refErr, setRefErr] = useState<string | null>(null);

  function submit() {
    let source_ref: Record<string, unknown> | null = null;
    if (ref.trim()) {
      try { source_ref = JSON.parse(ref); } catch { setRefErr("Это должен быть JSON, например {\"spreadsheet_id\": \"…\"}"); return; }
    }
    onSave({ name: name.trim(), type, url: url.trim() || null, note: note.trim() || null, source_ref });
  }

  return (
    <div className="inline-form">
      <div className="grid2">
        <div className="field"><label>Название</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></div>
        <div className="field"><label>Тип</label>
          <select className="select" value={type} onChange={(e) => setType(e.target.value as ToolType)}>
            {(Object.keys(TOOL_TYPE_LABEL) as ToolType[]).map((k) => <option key={k} value={k}>{TOOL_TYPE_LABEL[k]}</option>)}
          </select>
        </div>
        <div className="field"><label>Ссылка</label><input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></div>
        <div className="field"><label>Заметка</label><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></div>
      </div>
      <div className="field">
        <label>Идентификатор источника для агентов (JSON, необязательно)</label>
        <input className="input mono" value={ref} onChange={(e) => { setRef(e.target.value); setRefErr(null); }} placeholder='{"spreadsheet_id": "1AbC…"}' />
        {refErr && <span className="hint" style={{ color: "var(--danger)" }}>{refErr}</span>}
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn sm" onClick={onCancel}>Отмена</button>
        <button className="btn primary sm" onClick={submit} disabled={!name.trim()}>Сохранить</button>
      </div>
    </div>
  );
}
