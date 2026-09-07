import { useEffect, useRef, useState } from "react";
import {
  api, canEdit, Channel, CHANNEL_LABEL, del, Delegation, DelegationIn, dirColor, errorText, fromDateTimeInput, isApiStatus, isOverdue, Person, post, projColor, put,
  Recipient, RECIPIENT_LABEL, Reminder, ReminderIn, showDateTime, STATUS_LABEL, STATUSES, Task, TaskIn, TaskStatus, toDateInput, toDateTimeInput, toIn, Tool, TOOL_TYPE_LABEL, ToolType,
} from "./api";
import Checklist from "./Checklist";
import { useConfirm } from "./confirm";
import { useDeletion } from "./deletion";
import { useDirtyFlag, useEscape } from "./layers";
import { createMindMap, MindButton } from "./MindMaps";
import { Store } from "./store";

type Props = { store: Store; task: Task; onClose: () => void; onDeleted: () => void; onOpenMindmap: (id: number) => void; onShare: () => void };

const SAVE_DELAY = 600;

export default function TaskPanel({ store, task, onClose, onDeleted, onOpenMindmap, onShare }: Props) {
  const [draft, setDraft] = useState<TaskIn>(toIn(task));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);   // «название пустое — не сохраняю» и т. п.
  // В1/В2: черновик и флаг «есть несохранённое» живут в ref — таймер, размонтирование и ответ сервера читают их напрямую,
  // а не замыкание на устаревший state. revision растёт при каждой правке: ответ сервера на старую версию не откатывает поле.
  const draftRef = useRef(draft);
  const dirtyRef = useRef(false);
  const revision = useRef(0);
  const baseUpdatedAt = useRef(task.updated_at);       // С10: версия, от которой правим — сервер сверяет и отвечает 409
  const timer = useRef<number | null>(null);
  const inflight = useRef<Promise<void> | null>(null);
  const storeRef = useRef(store); storeRef.current = store;
  const taskRef = useRef(task); taskRef.current = task;
  const confirm = useConfirm();
  const { deleteTask } = useDeletion(store);
  useDirtyFlag(dirty);

  // Внешние изменения (перетаскивание, коллега) — подтягиваем, только если нет несохранённых правок
  useEffect(() => {
    if (dirtyRef.current) return;
    draftRef.current = toIn(task); setDraft(draftRef.current); baseUpdatedAt.current = task.updated_at;
  }, [task]);

  function change(patch: Partial<TaskIn>) {
    draftRef.current = { ...draftRef.current, ...patch }; revision.current++;
    dirtyRef.current = true;
    setDraft(draftRef.current); setDirty(true); setNote(null);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), SAVE_DELAY);
  }

  /** Отправить черновик. Если ответ пришёл на уже устаревшую версию — поле не трогаем, а сохраняем ещё раз. */
  async function flush(): Promise<void> {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    if (!dirtyRef.current) return;
    if (inflight.current) { await inflight.current; return flush(); }
    const t = taskRef.current, st = storeRef.current;
    const body = draftRef.current, rev = revision.current;
    if (!body.title.trim()) { setNote("Название не может быть пустым — правка не сохранена."); return; }   // Н9
    setSaving(true);
    const run = (async () => {
      try {
        const saved = t.access === "assignee"
          ? await post<Task>(`/tasks/${t.id}/status`, { status: body.status })
          : await put<Task>(`/tasks/${t.id}`, { ...body, title: body.title.trim(), updated_at: baseUpdatedAt.current });
        baseUpdatedAt.current = saved.updated_at;
        // ответ на устаревшую версию (печатали дальше) — в стор не кладём, следующий flush отправит актуальное
        if (revision.current === rev) { dirtyRef.current = false; setDirty(false); draftRef.current = toIn(saved); setDraft(draftRef.current); st.patchTask(saved); }
      } catch (e) {
        if (isApiStatus(e, 409)) {
          dirtyRef.current = false; setDirty(false);
          const reload = await confirm("Задачу изменили в другом окне. Загрузить новую версию? Ваши несохранённые правки будут заменены.", { title: "Задача изменилась", okLabel: "Загрузить новую версию", cancelLabel: "Оставить мою" });
          if (reload) { try { const fresh = await api<Task>(`/tasks/${t.id}`); baseUpdatedAt.current = fresh.updated_at; draftRef.current = toIn(fresh); setDraft(draftRef.current); st.patchTask(fresh); } catch (e2) { st.setError(errorText(e2)); } }
          else { dirtyRef.current = true; setDirty(true); try { const fresh = await api<Task>(`/tasks/${t.id}`); baseUpdatedAt.current = fresh.updated_at; } catch { /* оставим версию как есть */ } }
        } else st.setError(errorText(e));
      } finally { setSaving(false); }
    })();
    inflight.current = run;
    try { await run; } finally { inflight.current = null; }
    if (dirtyRef.current && revision.current !== rev) void flush();
  }

  // В1: закрыли раньше таймера — досохраняем при размонтировании
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); if (dirtyRef.current) void flush(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => { void flush(); onClose(); };
  useEscape(close);   // С9: Esc закрывает только карточку, если поверх нет меню/окна

  async function remove() {
    if (timer.current) window.clearTimeout(timer.current);
    dirtyRef.current = false;                      // удаляем — досохранять нечего
    if (await deleteTask(task)) onDeleted(); else dirtyRef.current = dirty;
  }

  const toggle = (arr: number[], id: number) => (arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);

  const dirs = store.directions.filter((d) => draft.direction_ids.includes(d.id));
  const project = store.projects.find((p) => p.id === draft.project_id) ?? null;
  const accent = project ? projColor(project, store.directions) : dirs.length ? dirColor(dirs[0]) : "var(--line-strong)";
  const editable = canEdit(task.access);           // владелец или редактор
  const isOwner = !task.access || task.access === "owner";
  const readOnly = task.access === "view" || task.access === "assignee";
  // Проекты, доступные для выбора: из выбранных направлений (или всех редактируемых, если направления не выбраны)
  const projectOptions = store.projects.filter((p) => p.status !== "archived" && canEdit(p.access) && (draft.direction_ids.length === 0 || draft.direction_ids.includes(p.direction_id)) || p.id === draft.project_id);
  function setProject(id: number | null) {
    const p = store.projects.find((x) => x.id === id);
    change({ project_id: id, direction_ids: p && !draft.direction_ids.includes(p.direction_id) ? [...draft.direction_ids, p.direction_id] : draft.direction_ids });
  }

  return (
    <div className="backdrop task-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className={`task-modal ${readOnly ? "ro" : ""}`} role="dialog" aria-modal="true" aria-label="Карточка задачи" style={{ ["--dir" as string]: accent }}>
        <div className="tm-head">
          <span className="tm-rail">{(dirs.length ? dirs : [null]).map((d, i) => <span key={i} style={{ background: d ? dirColor(d) : "var(--line-strong)" }} />)}</span>
          <span className="id">#{task.id}</span>
          <span className={`status-pill st-${draft.status}`}>{STATUS_LABEL[draft.status]}</span>
          <span className={`pri p${draft.priority}`}>P{draft.priority}</span>
          {readOnly
            ? <span className="tag ro-tag">{task.access === "view" ? "только просмотр" : "поручено вам"} · {task.owner?.name ?? "коллега"}</span>
            : !isOwner ? <span className="tag shared-tag">⇄ открыл {task.owner?.name ?? "коллега"}</span>
            : <span className="saving">{saving ? "сохраняю…" : dirty ? "изменено" : "сохранено"}</span>}
          {!isOwner && !readOnly && <span className="saving">{saving ? "сохраняю…" : dirty ? "изменено" : "сохранено"}</span>}
          <span className="spacer" />
          {isOwner && <button className="btn ghost sm" onClick={onShare} title="Открыть задачу коллеге">⇄ Поделиться</button>}
          <button className="btn ghost icon" onClick={close} title="Закрыть (Esc)" aria-label="Закрыть">×</button>
        </div>

        <div className="tm-body">
          <fieldset className="tm-main" disabled={readOnly}>
            {note && <div className="tm-note" role="alert">{note}</div>}
            <div className="grow-wrap" data-value={draft.title || "Название задачи"}>
              <textarea
                className="title-input" rows={1} value={draft.title} placeholder="Название задачи"
                onChange={(e) => change({ title: e.target.value.replace(/\n/g, " ") })}
                onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
              />
            </div>

            <div className="section">
              <div className="section-head">Направления <span className="n">{draft.direction_ids.length}</span></div>
              <div className="chips">
                {store.directions.filter((d) => (d.status !== "archived" && canEdit(d.access) && d.access !== "via") || draft.direction_ids.includes(d.id)).map((d) => (
                  <button key={d.id} className={`chip pick ${draft.direction_ids.includes(d.id) ? "on" : ""}`} style={{ ["--pick" as string]: dirColor(d) }}
                    disabled={project?.direction_id === d.id} title={project?.direction_id === d.id ? "Направление проекта — снимается вместе с проектом" : undefined}
                    onClick={() => change({ direction_ids: toggle(draft.direction_ids, d.id) })}>
                    <span className="dot" style={{ background: dirColor(d) }} />{d.name}
                  </button>
                ))}
                {store.directions.length === 0 && <span className="hint">Направлений ещё нет — добавьте в левой панели.</span>}
              </div>
            </div>

            <div className="field">
              <label>Описание</label>
              <textarea className="textarea" rows={5} value={draft.description ?? ""} onChange={(e) => change({ description: e.target.value || null })} placeholder="Что нужно сделать, критерий готовности, контекст" />
            </div>

            <Checklist items={draft.checklist} onChange={(checklist) => change({ checklist })} readOnly={readOnly} />

            <ToolsSection store={store} selected={draft.tool_ids} onChange={(ids) => change({ tool_ids: ids })} taskId={task.id} attached={task.tools} editable={!readOnly} />

            <div className="section">
              <div className="section-head">Майндмап<span className="spacer" /></div>
              {(() => {
                const maps = store.mindmaps.filter((m) => m.task_id === task.id);
                return maps.length ? (
                  <div className="list">{maps.map((m) => (
                    <div key={m.id} className="item">
                      <span className="primary">{m.title}</span>
                      <span className="actions"><MindButton count={1} label="Открыть" onClick={() => onOpenMindmap(m.id)} /></span>
                    </div>
                  ))}</div>
                ) : readOnly ? <span className="hint">Майндмапа нет.</span> : (
                  <div className="row">
                    <MindButton count={0} label="Создать майндмап задачи" onClick={async () => {
                      try { const d0 = store.directions.find((d) => draft.direction_ids.includes(d.id) && canEdit(d.access) && d.access !== "via");
                      const m = await createMindMap(store, task.title, { task_id: task.id, direction_id: d0?.id ?? null }); onOpenMindmap(m.id); } catch (e) { store.setError(errorText(e)); }
                    }} />
                    <span className="hint">Разложить задачу на шаги, риски, вопросы.</span>
                  </div>
                );
              })()}
            </div>

            <div className="danger-zone">
              <span className="hint">Создана {showDateTime(task.created_at)}{task.owner && !isOwner ? ` · ${task.owner.name}` : ""}</span>
              {isOwner && <button className="btn danger sm" onClick={remove}>Удалить задачу…</button>}
            </div>
          </fieldset>

          <div className="tm-side">
            <div className="tm-props">
              <div className="field">
                <label>Статус</label>
                <select className={`select st-${draft.status}`} value={draft.status} disabled={task.access === "view"} onChange={(e) => change({ status: e.target.value as TaskStatus })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Проект</label>
                <select className="select" value={draft.project_id ?? ""} disabled={readOnly} onChange={(e) => setProject(e.target.value ? Number(e.target.value) : null)}>
                  <option value="">Без проекта</option>
                  {projectOptions.map((p) => {
                    const d = store.directions.find((x) => x.id === p.direction_id);
                    return <option key={p.id} value={p.id}>{p.name}{d && draft.direction_ids.length !== 1 ? ` · ${d.name}` : ""}</option>;
                  })}
                </select>
              </div>
              <div className="field">
                <label>Приоритет</label>
                <select className="select" value={draft.priority} disabled={readOnly} onChange={(e) => change({ priority: Number(e.target.value) })}>
                  <option value={1}>P1 — критично</option><option value={2}>P2 — высокий</option><option value={3}>P3 — обычный</option>
                  <option value={4}>P4 — низкий</option><option value={5}>P5 — когда-нибудь</option>
                </select>
              </div>
              <div className="field">
                <label>Дедлайн</label>
                <input className="input" type="date" value={toDateInput(draft.deadline)} disabled={readOnly} onChange={(e) => change({ deadline: e.target.value || null })} />
              </div>
              <div className="field">
                <label>Следующая проверка</label>
                <input className="input" type="datetime-local" value={toDateTimeInput(draft.next_check_at)} disabled={readOnly} onChange={(e) => change({ next_check_at: fromDateTimeInput(e.target.value) })} />
              </div>
            </div>

            <DelegationsSection store={store} taskId={task.id} editable={editable} />
            {editable ? <RemindersSection store={store} taskId={task.id} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Тулы ---------- */
function ToolsSection({ store, selected, onChange, taskId, attached, editable }: { store: Store; selected: number[]; onChange: (ids: number[]) => void; taskId: number; attached: Tool[]; editable: boolean }) {
  // тулы автора задачи, которых нет в моём справочнике (общая задача) — показываем, снимать нельзя
  const foreign = attached.filter((t) => selected.includes(t.id) && !store.tools.some((x) => x.id === t.id));
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState<ToolType>("google_sheet");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);   // С2: двойной клик/Enter — один POST

  async function create() {
    if (!name.trim() || busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try {
      const t = await post<Tool>("/tools", { name: name.trim(), type, url: url.trim() || null, source_ref: null, note: null, task_ids: [taskId], direction_ids: [] });
      await store.reloadTools();
      onChange([...selected, t.id]);
      setName(""); setUrl(""); setAdding(false);
    } catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  const toggle = (id: number) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="section">
      <div className="section-head">Тулы <span className="n">{selected.length}</span><span className="spacer" />
        {editable && <button className="btn ghost sm" onClick={() => setAdding((v) => !v)}>{adding ? "Отмена" : "+ Новый тул"}</button>}
      </div>
      {adding && (
        <div className="inline-form">
          <div className="row">
            <input className="input grow" placeholder="Название (например, «Реестр закупок»)" value={name} onChange={(e) => setName(e.target.value)} autoFocus onKeyDown={(e) => { if (e.key === "Enter") void create(); }} />
            <select className="select" style={{ width: 170 }} value={type} onChange={(e) => setType(e.target.value as ToolType)}>
              {(Object.keys(TOOL_TYPE_LABEL) as ToolType[]).map((k) => <option key={k} value={k}>{TOOL_TYPE_LABEL[k]}</option>)}
            </select>
          </div>
          <div className="row">
            <input className="input grow" placeholder="Ссылка (необязательно)" value={url} onChange={(e) => setUrl(e.target.value)} />
            <button className="btn primary sm" onClick={create} disabled={busy || !name.trim()}>Создать и привязать</button>
          </div>
        </div>
      )}
      <div className="chips">
        {foreign.map((t) => <span key={t.id} className="chip pick on" title={`${TOOL_TYPE_LABEL[t.type]} · тул автора задачи`}>{t.name}</span>)}
        {store.tools.map((t) => (
          <button key={t.id} className={`chip pick ${selected.includes(t.id) ? "on" : ""}`} onClick={() => toggle(t.id)} title={TOOL_TYPE_LABEL[t.type]}>
            {t.name}
          </button>
        ))}
        {store.tools.length === 0 && foreign.length === 0 && !adding && <span className="hint">{editable ? "Тулов пока нет. Тул — это таблица, бот или документ, через который ведётся задача." : "Тулов нет."}</span>}
      </div>
      {selected.length > 0 && (
        <div className="list">
          {[...foreign, ...store.tools.filter((t) => selected.includes(t.id))].map((t) => (
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
function DelegationsSection({ store, taskId, editable }: { store: Store; taskId: number; editable: boolean }) {
  const [items, setItems] = useState<Delegation[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [personId, setPersonId] = useState<number | "new">(store.people[0]?.id ?? "new");
  const [newName, setNewName] = useState("");
  const [checkAt, setCheckAt] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const confirm = useConfirm();

  const load = async () => { try { setItems(await api<Delegation[]>(`/tasks/${taskId}/delegations`)); } catch (e) { store.setError(errorText(e)); } };
  useEffect(() => { setItems(null); void load(); }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (personId === "new" && store.people[0]) setPersonId(store.people[0].id); }, [store.people]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
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
    } catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  async function setStatus(d: Delegation, status: "open" | "done") {
    try {
      await put(`/delegations/${d.id}`, { task_id: d.task_id, person_id: d.person_id, check_at: d.check_at ?? null, comment: d.comment ?? null, status });
      await load();
    } catch (e) { store.setError(errorText(e)); }
  }
  async function remove(d: Delegation) {
    if (!(await confirm(`Поручение с ${d.person.name} будет снято; напоминания исполнителю по нему больше не уйдут.`, { title: "Снять поручение?", danger: true, okLabel: "Снять" }))) return;
    try { await del(`/delegations/${d.id}`); await load(); } catch (e) { store.setError(errorText(e)); }
  }

  const open = items?.filter((d) => d.status === "open") ?? [];
  return (
    <div className="section">
      <div className="section-head">Кому поручено <span className="n">{open.length}</span><span className="spacer" />
        {editable && <button className="btn ghost sm" onClick={() => setAdding((v) => !v)}>{adding ? "Отмена" : "+ Поручить"}</button>}
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
            <button className="btn primary sm" onClick={create} disabled={busy || (personId === "new" && !newName.trim())}>Поручить</button>
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
                {editable && <span className="actions">
                  {d.status === "open"
                    ? <button className="btn ghost sm" onClick={() => setStatus(d, "done")}>Выполнено</button>
                    : <button className="btn ghost sm" onClick={() => setStatus(d, "open")}>Вернуть</button>}
                  <button className="btn danger sm" onClick={() => remove(d)} aria-label="Снять">×</button>
                </span>}
                <span className={`secondary ${late ? "over" : ""}`}>
                  {d.check_at ? `${late ? "⚑ просрочена проверка " : "проверить "}${showDateTime(d.check_at)}` : `поручено ${showDateTime(d.assigned_at)}`}
                  {d.comment ? ` · ${d.comment}` : ""}
                  {d.report ? ` · отчёт: «${d.report}»` : ""}
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
  const [recipient, setRecipient] = useState<Recipient>("owner");
  const [assignees, setAssignees] = useState<string[]>([]); // имена исполнителей по открытым поручениям — для подсказки
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const confirm = useConfirm();

  const load = async () => {
    try {
      const [rs, ds] = await Promise.all([api<Reminder[]>(`/tasks/${taskId}/reminders`), api<Delegation[]>(`/tasks/${taskId}/delegations`)]);
      setItems(rs); setAssignees(ds.filter((d) => d.status === "open").map((d) => d.person.name));
    } catch (e) { store.setError(errorText(e)); }
  };
  useEffect(() => { setItems(null); void load(); }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    const iso = fromDateTimeInput(fireAt);
    if (!iso || channels.length === 0 || busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try {
      await post<Reminder>("/reminders", { task_id: taskId, fire_at: iso, channels, message: message.trim() || null, recipient } satisfies ReminderIn);
      setAdding(false); setFireAt(""); setMessage("");
      await load();
    } catch (e) { store.setError(errorText(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  // С3: крестик — через вопрос; событие в календаре Outlook сервер не трогает — говорим об этом
  async function remove(r: Reminder) {
    const outlook = r.channels.includes("outlook_calendar");
    if (!(await confirm(`Напоминание на ${showDateTime(r.fire_at)} (${r.channels.map((c) => CHANNEL_LABEL[c]).join(", ")}) будет удалено${r.sent_at ? " из истории" : ""}.${outlook ? " Событие в календаре Outlook останется — удалите его в календаре сами." : ""}`, { title: "Удалить напоминание?", danger: true, okLabel: "Удалить" }))) return;
    try { await del(`/reminders/${r.id}`); await load(); } catch (e) { store.setError(errorText(e)); }
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
          <div className="field">
            <label>Кому</label>
            <div className="seg" role="radiogroup" aria-label="Кому напомнить">
              {(Object.keys(RECIPIENT_LABEL) as Recipient[]).map((r) => (
                <button key={r} role="radio" aria-checked={recipient === r} className={recipient === r ? "on" : ""} onClick={() => setRecipient(r)}>{RECIPIENT_LABEL[r]}</button>
              ))}
            </div>
            {recipient !== "owner" && (
              <span className="hint">{assignees.length ? `Исполнители сейчас: ${assignees.join(", ")}. Получат те, у кого открыто поручение в момент отправки — в Telegram (если указан chat id) или на почту.` : "У задачи пока нет открытых поручений — сначала поручите её кому-нибудь, иначе исполнителю отправлять будет некому."}</span>
            )}
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn primary sm" onClick={create} disabled={busy || !fireAt || channels.length === 0}>Добавить</button>
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
              <span className="secondary">{r.channels.map((c) => CHANNEL_LABEL[c]).join(", ")}{r.recipient && r.recipient !== "owner" ? ` · ${RECIPIENT_LABEL[r.recipient].toLowerCase()}` : ""}{r.message ? ` · ${r.message}` : ""}{r.sent_at ? " · отправлено" : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
