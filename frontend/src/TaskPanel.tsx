import { useEffect, useRef, useState } from "react";
import {
  api, Channel, CHANNEL_LABEL, del, Delegation, DelegationIn, dirColor, fromDateTimeInput, isOverdue, Person, post, put,
  Reminder, ReminderIn, showDateTime, STATUS_LABEL, STATUSES, Task, TaskIn, TaskStatus, toDateInput, toDateTimeInput, Tool, TOOL_TYPE_LABEL, ToolType,
} from "./api";
import { Store } from "./store";

type Props = { store: Store; task: Task; onClose: () => void; onDeleted: () => void };

const toIn = (t: Task): TaskIn => ({
  title: t.title, description: t.description ?? null, status: t.status, priority: t.priority,
  deadline: t.deadline || null, next_check_at: t.next_check_at || null,
  direction_ids: t.directions.map((d) => d.id), tool_ids: t.tools.map((x) => x.id),
});

export default function TaskPanel({ store, task, onClose, onDeleted }: Props) {
  const [draft, setDraft] = useState<TaskIn>(toIn(task));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const timer = useRef<number | null>(null);

  // Внешние изменения (перетаскивание, другая задача) — подтягиваем, если нет несохранённых правок
  useEffect(() => { if (!dirty) setDraft(toIn(task)); }, [task, dirty]);

  function change(patch: Partial<TaskIn>) {
    setDraft((d) => ({ ...d, ...patch }));
    setDirty(true);
  }

  // Автосохранение с задержкой
  useEffect(() => {
    if (!dirty) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setSaving(true);
      try {
        const saved = await put<Task>(`/tasks/${task.id}`, { ...draft, title: draft.title.trim() || task.title });
        store.patchTask(saved);
        setDirty(false);
      } catch (e) { store.setError(String(e)); } finally { setSaving(false); }
    }, 600);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [draft, dirty, task.id, task.title, store]);

  async function remove() {
    if (!window.confirm(`Удалить задачу «${task.title}»? Делегирования и напоминания удалятся вместе с ней.`)) return;
    try { await del(`/tasks/${task.id}`); await store.reloadTasks(); onDeleted(); } catch (e) { store.setError(String(e)); }
  }

  const toggle = (arr: number[], id: number) => (arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);

  return (
    <aside className="panel" aria-label="Карточка задачи">
      <div className="panel-head">
        <span className="id">#{task.id}</span>
        <span className="saving">{saving ? "сохраняю…" : dirty ? "изменено" : "сохранено"}</span>
        <span className="spacer" />
        <button className="btn ghost icon" onClick={onClose} title="Закрыть" aria-label="Закрыть">×</button>
      </div>

      <div className="panel-body">
        <div className="grow-wrap" data-value={draft.title || "Название задачи"}>
          <textarea
            className="title-input" rows={1} value={draft.title} placeholder="Название задачи"
            onChange={(e) => change({ title: e.target.value.replace(/\n/g, " ") })}
            onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
          />
        </div>

        <div className="grid2">
          <div className="field">
            <label>Статус</label>
            <select className="select" value={draft.status} onChange={(e) => change({ status: e.target.value as TaskStatus })}>
              {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Приоритет</label>
            <select className="select" value={draft.priority} onChange={(e) => change({ priority: Number(e.target.value) })}>
              <option value={1}>P1 — критично</option><option value={2}>P2 — высокий</option><option value={3}>P3 — обычный</option>
              <option value={4}>P4 — низкий</option><option value={5}>P5 — когда-нибудь</option>
            </select>
          </div>
          <div className="field">
            <label>Дедлайн</label>
            <input className="input" type="date" value={toDateInput(draft.deadline)} onChange={(e) => change({ deadline: e.target.value || null })} />
          </div>
          <div className="field">
            <label>Следующая проверка</label>
            <input className="input" type="datetime-local" value={toDateTimeInput(draft.next_check_at)} onChange={(e) => change({ next_check_at: fromDateTimeInput(e.target.value) })} />
          </div>
        </div>

        <div className="field">
          <label>Описание</label>
          <textarea className="textarea" value={draft.description ?? ""} onChange={(e) => change({ description: e.target.value || null })} placeholder="Что нужно сделать, критерий готовности, контекст" />
        </div>

        <div className="section">
          <div className="section-head">Направления <span className="n">{draft.direction_ids.length}</span></div>
          <div className="chips">
            {store.directions.filter((d) => d.status !== "archived" || draft.direction_ids.includes(d.id)).map((d) => (
              <button key={d.id} className={`chip pick ${draft.direction_ids.includes(d.id) ? "on" : ""}`} onClick={() => change({ direction_ids: toggle(draft.direction_ids, d.id) })}>
                <span className="dot" style={{ background: dirColor(d) }} />{d.name}
              </button>
            ))}
            {store.directions.length === 0 && <span className="hint">Направлений ещё нет — добавьте в левой панели.</span>}
          </div>
        </div>

        <ToolsSection store={store} selected={draft.tool_ids} onChange={(ids) => change({ tool_ids: ids })} taskId={task.id} />
        <DelegationsSection store={store} taskId={task.id} />
        <RemindersSection store={store} taskId={task.id} />

        <div className="danger-zone">
          <span className="hint">Создана {showDateTime(task.created_at)}</span>
          <button className="btn danger sm" onClick={remove}>Удалить задачу</button>
        </div>
      </div>
    </aside>
  );
}

/* ---------- Тулы ---------- */
function ToolsSection({ store, selected, onChange, taskId }: { store: Store; selected: number[]; onChange: (ids: number[]) => void; taskId: number }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState<ToolType>("google_sheet");
  const [url, setUrl] = useState("");

  async function create() {
    if (!name.trim()) return;
    try {
      const t = await post<Tool>("/tools", { name: name.trim(), type, url: url.trim() || null, source_ref: null, note: null, task_ids: [taskId], direction_ids: [] });
      await store.reloadTools();
      onChange([...selected, t.id]);
      setName(""); setUrl(""); setAdding(false);
    } catch (e) { store.setError(String(e)); }
  }
  const toggle = (id: number) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="section">
      <div className="section-head">Тулы <span className="n">{selected.length}</span><span className="spacer" />
        <button className="btn ghost sm" onClick={() => setAdding((v) => !v)}>{adding ? "Отмена" : "+ Новый тул"}</button>
      </div>
      {adding && (
        <div className="inline-form">
          <div className="row">
            <input className="input grow" placeholder="Название (например, «Реестр закупок»)" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <select className="select" style={{ width: 170 }} value={type} onChange={(e) => setType(e.target.value as ToolType)}>
              {(Object.keys(TOOL_TYPE_LABEL) as ToolType[]).map((k) => <option key={k} value={k}>{TOOL_TYPE_LABEL[k]}</option>)}
            </select>
          </div>
          <div className="row">
            <input className="input grow" placeholder="Ссылка (необязательно)" value={url} onChange={(e) => setUrl(e.target.value)} />
            <button className="btn primary sm" onClick={create} disabled={!name.trim()}>Создать и привязать</button>
          </div>
        </div>
      )}
      <div className="chips">
        {store.tools.map((t) => (
          <button key={t.id} className={`chip pick ${selected.includes(t.id) ? "on" : ""}`} onClick={() => toggle(t.id)} title={TOOL_TYPE_LABEL[t.type]}>
            {t.name}
          </button>
        ))}
        {store.tools.length === 0 && !adding && <span className="hint">Тулов пока нет. Тул — это таблица, бот или документ, через который ведётся задача.</span>}
      </div>
      {selected.length > 0 && (
        <div className="list">
          {store.tools.filter((t) => selected.includes(t.id)).map((t) => (
            <div key={t.id} className="item">
              <span className="primary">{t.name}</span>
              <span className="actions">{t.url && <a className="btn ghost sm" href={t.url} target="_blank" rel="noreferrer">Открыть ↗</a>}</span>
              <span className="secondary">{TOOL_TYPE_LABEL[t.type]}{t.note ? ` · ${t.note}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Делегирование ---------- */
function DelegationsSection({ store, taskId }: { store: Store; taskId: number }) {
  const [items, setItems] = useState<Delegation[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [personId, setPersonId] = useState<number | "new">(store.people[0]?.id ?? "new");
  const [newName, setNewName] = useState("");
  const [checkAt, setCheckAt] = useState("");
  const [comment, setComment] = useState("");

  const load = async () => { try { setItems(await api<Delegation[]>(`/tasks/${taskId}/delegations`)); } catch (e) { store.setError(String(e)); } };
  useEffect(() => { setItems(null); void load(); }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (personId === "new" && store.people[0]) setPersonId(store.people[0].id); }, [store.people]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    try {
      let pid = personId;
      if (pid === "new") {
        if (!newName.trim()) return;
        const p = await post<Person>("/people", { name: newName.trim(), telegram_chat_id: null, email: null, note: null });
        await store.reloadPeople(); pid = p.id;
      }
      await post<Delegation>("/delegations", { task_id: taskId, person_id: pid, check_at: fromDateTimeInput(checkAt), comment: comment.trim() || null, status: "open" } satisfies DelegationIn);
      setAdding(false); setNewName(""); setCheckAt(""); setComment("");
      await load();
    } catch (e) { store.setError(String(e)); }
  }
  async function setStatus(d: Delegation, status: "open" | "done") {
    try {
      await put(`/delegations/${d.id}`, { task_id: d.task_id, person_id: d.person_id, check_at: d.check_at ?? null, comment: d.comment ?? null, status });
      await load();
    } catch (e) { store.setError(String(e)); }
  }
  async function remove(d: Delegation) {
    if (!window.confirm(`Снять поручение с ${d.person.name}?`)) return;
    try { await del(`/delegations/${d.id}`); await load(); } catch (e) { store.setError(String(e)); }
  }

  const open = items?.filter((d) => d.status === "open") ?? [];
  return (
    <div className="section">
      <div className="section-head">Кому поручено <span className="n">{open.length}</span><span className="spacer" />
        <button className="btn ghost sm" onClick={() => setAdding((v) => !v)}>{adding ? "Отмена" : "+ Поручить"}</button>
      </div>
      {adding && (
        <div className="inline-form">
          <div className="row">
            <select className="select grow" value={personId} onChange={(e) => setPersonId(e.target.value === "new" ? "new" : Number(e.target.value))}>
              {store.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              <option value="new">+ Новый человек…</option>
            </select>
            {personId === "new" && <input className="input grow" placeholder="Имя" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus />}
          </div>
          <div className="row">
            <div className="field grow"><label>Проверить</label><input className="input" type="datetime-local" value={checkAt} onChange={(e) => setCheckAt(e.target.value)} /></div>
            <div className="field grow"><label>Комментарий</label><input className="input" placeholder="Что именно ждём" value={comment} onChange={(e) => setComment(e.target.value)} /></div>
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn primary sm" onClick={create} disabled={personId === "new" && !newName.trim()}>Поручить</button>
          </div>
        </div>
      )}
      {items === null ? <span className="hint">Загрузка…</span> : items.length === 0 && !adding ? (
        <span className="hint">Задача пока ни за кем не закреплена.</span>
      ) : (
        <div className="list">
          {items.map((d) => {
            const late = d.status === "open" && isOverdue(d.check_at);
            return (
              <div key={d.id} className={`item ${d.status === "done" ? "muted" : ""}`}>
                <span className="primary">{d.person.name}</span>
                <span className="actions">
                  {d.status === "open"
                    ? <button className="btn ghost sm" onClick={() => setStatus(d, "done")}>Выполнено</button>
                    : <button className="btn ghost sm" onClick={() => setStatus(d, "open")}>Вернуть</button>}
                  <button className="btn danger sm" onClick={() => remove(d)} aria-label="Снять">×</button>
                </span>
                <span className={`secondary ${late ? "over" : ""}`}>
                  {d.check_at ? `${late ? "⚑ просрочена проверка " : "проверить "}${showDateTime(d.check_at)}` : `поручено ${showDateTime(d.assigned_at)}`}
                  {d.comment ? ` · ${d.comment}` : ""}
                  {d.notified_at ? " · напоминание отправлено" : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ---------- Напоминания ---------- */
function RemindersSection({ store, taskId }: { store: Store; taskId: number }) {
  const [items, setItems] = useState<Reminder[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [fireAt, setFireAt] = useState("");
  const [channels, setChannels] = useState<Channel[]>(["telegram"]);
  const [message, setMessage] = useState("");

  const load = async () => { try { setItems(await api<Reminder[]>(`/tasks/${taskId}/reminders`)); } catch (e) { store.setError(String(e)); } };
  useEffect(() => { setItems(null); void load(); }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    const iso = fromDateTimeInput(fireAt);
    if (!iso || channels.length === 0) return;
    try {
      await post<Reminder>("/reminders", { task_id: taskId, fire_at: iso, channels, message: message.trim() || null } satisfies ReminderIn);
      setAdding(false); setFireAt(""); setMessage("");
      await load();
    } catch (e) { store.setError(String(e)); }
  }
  async function remove(r: Reminder) {
    try { await del(`/reminders/${r.id}`); await load(); } catch (e) { store.setError(String(e)); }
  }
  const toggle = (c: Channel) => setChannels((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));

  return (
    <div className="section">
      <div className="section-head">Напоминания <span className="n">{items?.filter((r) => !r.sent_at).length ?? 0}</span><span className="spacer" />
        <button className="btn ghost sm" onClick={() => setAdding((v) => !v)}>{adding ? "Отмена" : "+ Напомнить"}</button>
      </div>
      {adding && (
        <div className="inline-form">
          <div className="row">
            <div className="field grow"><label>Когда</label><input className="input" type="datetime-local" value={fireAt} onChange={(e) => setFireAt(e.target.value)} autoFocus /></div>
            <div className="field grow"><label>Текст</label><input className="input" placeholder="По умолчанию — название задачи" value={message} onChange={(e) => setMessage(e.target.value)} /></div>
          </div>
          <div className="checks">
            {(Object.keys(CHANNEL_LABEL) as Channel[]).map((c) => (
              <label key={c}><input type="checkbox" checked={channels.includes(c)} onChange={() => toggle(c)} /> {CHANNEL_LABEL[c]}</label>
            ))}
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn primary sm" onClick={create} disabled={!fireAt || channels.length === 0}>Добавить</button>
          </div>
          <span className="hint">Сервер проверяет напоминания раз в минуту и шлёт по выбранным каналам. Календарь Outlook — создаёт событие на это время.</span>
        </div>
      )}
      {items === null ? <span className="hint">Загрузка…</span> : items.length === 0 && !adding ? (
        <span className="hint">Напоминаний нет.</span>
      ) : (
        <div className="list">
          {items.map((r) => (
            <div key={r.id} className={`item ${r.sent_at ? "muted" : ""}`}>
              <span className="primary mono">{showDateTime(r.fire_at)}</span>
              <span className="actions"><button className="btn danger sm" onClick={() => remove(r)} aria-label="Удалить">×</button></span>
              <span className="secondary">{r.channels.map((c) => CHANNEL_LABEL[c]).join(", ")}{r.message ? ` · ${r.message}` : ""}{r.sent_at ? " · отправлено" : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
