// Справочники: Люди и Тулы. Простые таблицы с редактированием на месте.
import { useEffect, useState } from "react";
import { api, del, isOverdue, Person, PersonIn, PersonSummary, post, put, showDate, showDateTime, STATUS_LABEL, Tool, ToolIn, TOOL_TYPE_LABEL, ToolType } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

export function PeoplePage({ store, onOpenTask }: { store: Store; onOpenTask: (id: number) => void }) {
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [summaryFor, setSummaryFor] = useState<Person | null>(null);
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
      <p className="hint">Кому вы поручаете задачи. Нажмите на имя — увидите сводку: сколько поручено, что сделано, что просрочено. Люди с пометкой «в планнере» получают поручения прямо в приложение.</p>
      {summaryFor && <PersonSummaryModal store={store} person={summaryFor} onClose={() => setSummaryFor(null)} onOpenTask={(id) => { setSummaryFor(null); onOpenTask(id); }} />}
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
              <span>
                <button className="person-link" onClick={() => setSummaryFor(p)}>{p.name}</button>
                {p.user_id && <span className="tag in-app">в планнере</span>}
                {p.note && <div className="sub">{p.note}</div>}
              </span>
              <span className="mono hide-m">{p.telegram_chat_id || "—"}</span>
              <span className="hide-m">{p.email || "—"}</span>
              <span className="row"><button className="btn ghost sm" onClick={() => setSummaryFor(p)}>Сводка</button><button className="btn ghost sm" onClick={() => setEditing(p)}>Изменить</button>{!p.user_id && <button className="btn danger sm" onClick={() => remove(p)}>×</button>}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Сводка по человеку: что я ему поручил и как идёт. */
export function PersonSummaryModal({ store, person, onClose, onOpenTask }: { store: Store; person: Person; onClose: () => void; onOpenTask: (id: number) => void }) {
  const [data, setData] = useState<PersonSummary | null>(null);
  useEffect(() => { api<PersonSummary>(`/people/${person.id}/summary`).then(setData).catch((e) => store.setError(String(e))); }, [person.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const pct = data && data.total ? Math.round((data.done / data.total) * 100) : 0;
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal person-summary" role="dialog" aria-modal="true">
        <div className="row">
          <h3 style={{ marginRight: "auto" }}>{person.name}</h3>
          {person.user_id && <span className="tag in-app">в планнере</span>}
          <button className="btn ghost icon" onClick={onClose} aria-label="Закрыть">×</button>
        </div>
        {!data ? <span className="hint">загрузка…</span> : data.total === 0 ? (
          <p className="hint">Вы ещё ничего не поручали {person.name}. Поручение делается из окна задачи → «Поручить».</p>
        ) : (
          <>
            <div className="ps-bar"><span style={{ width: `${pct}%` }} /></div>
            <dl className="stats">
              <div><dt>Поручено</dt><dd className="mono">{data.total}</dd></div>
              <div><dt>Сделано</dt><dd className="mono">{data.done}</dd></div>
              <div><dt>В работе</dt><dd className="mono">{data.open}</dd></div>
              <div className={data.overdue ? "bad" : ""}><dt>Просрочено</dt><dd className="mono">{data.overdue}</dd></div>
              <div className={data.check_due ? "bad" : ""}><dt>Пора проверить</dt><dd className="mono">{data.check_due}</dd></div>
              <div><dt>Выполнение</dt><dd className="mono">{pct}%</dd></div>
            </dl>
            <div className="list">
              {data.tasks.map((t) => {
                const d = data.delegations.find((x) => x.task_id === t.id);
                const late = t.status !== "done" && t.deadline && isOverdue(`${t.deadline}T23:59:59`);
                return (
                  <button key={t.id} className={`item ps-task ${t.status === "done" ? "muted" : ""}`} onClick={() => onOpenTask(t.id)}>
                    <span className="primary">{t.title}</span>
                    <span className="actions"><span className={`status-pill st-${t.status}`}>{STATUS_LABEL[t.status]}</span></span>
                    <span className={`secondary ${late ? "over" : ""}`}>
                      {t.deadline ? `до ${showDate(t.deadline)}` : "без срока"}
                      {d?.check_at ? ` · проверка ${showDateTime(d.check_at)}` : ""}
                      {d?.report ? ` · отчёт: «${d.report}»` : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
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
