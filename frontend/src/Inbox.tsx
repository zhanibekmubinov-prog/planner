// «Мне поручено»: задачи, которые поручили другие. Исполнитель меняет статус и пишет отчёт.
import { useEffect, useState } from "react";
import { api, Delegation, isOverdue, post, put, showDate, showDateTime, STATUS_LABEL, STATUSES, Task, TaskStatus } from "./api";
import { Store } from "./store";

export default function InboxPage({ store }: { store: Store }) {
  const [delegs, setDelegs] = useState<Delegation[]>([]);
  const [open, setOpen] = useState<number | null>(null);

  const load = async () => { try { setDelegs(await api<Delegation[]>("/delegations?mine=true")); } catch (e) { store.setError(String(e)); } };
  useEffect(() => { void load(); }, [store.inbox.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const byTask = new Map<number, Delegation>();
  delegs.forEach((d) => { if (!byTask.has(d.task_id) || d.status === "open") byTask.set(d.task_id, d); });
  const active = store.inbox.filter((t) => t.status !== "done").sort((a, b) => a.priority - b.priority || (a.deadline || "9").localeCompare(b.deadline || "9"));
  const done = store.inbox.filter((t) => t.status === "done");

  return (
    <div className="page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2>Мне поручено</h2><span className="spacer" />
        <span className="hint">{active.length} в работе · {done.length} закрыто</span>
      </div>
      <p className="hint">Задачи, которые вам поручили коллеги и руководство. Меняйте статус по ходу работы и оставляйте короткий отчёт — автор задачи увидит его у себя.</p>

      {store.inbox.length === 0 ? (
        <div className="state"><h3>Входящих поручений нет</h3><p>Когда кто-то поручит вам задачу, она появится здесь и придёт уведомлением.</p></div>
      ) : (
        <div className="list inbox-list">
          {[...active, ...done].map((t) => {
            const d = byTask.get(t.id);
            const late = t.status !== "done" && t.deadline && isOverdue(`${t.deadline}T23:59:59`);
            return (
              <div key={t.id} className={`inbox-item ${t.status === "done" ? "muted" : ""} ${open === t.id ? "open" : ""}`}>
                <button className="inbox-head" onClick={() => setOpen(open === t.id ? null : t.id)}>
                  <span className={`st st-${t.status}`} />
                  <span className="inbox-title">{t.title}</span>
                  <span className="inbox-from">от {t.owner?.name ?? "—"}</span>
                  {t.deadline && <span className={`mono ${late ? "over" : ""}`}>{late ? "⚑ " : ""}до {showDate(t.deadline)}</span>}
                  <span className={`pri p${t.priority}`}>P{t.priority}</span>
                </button>
                {open === t.id && <InboxDetail store={store} task={t} delegation={d} onChanged={load} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InboxDetail({ store, task, delegation, onChanged }: { store: Store; task: Task; delegation?: Delegation; onChanged: () => void }) {
  const [report, setReport] = useState(delegation?.report ?? "");
  const [busy, setBusy] = useState(false);

  async function setStatus(status: TaskStatus) {
    setBusy(true);
    try { store.patchTask(await post<Task>(`/tasks/${task.id}/status`, { status })); } catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }
  async function saveReport(done: boolean) {
    if (!delegation) return;
    setBusy(true);
    try {
      await put(`/delegations/${delegation.id}/report`, { status: done ? "done" : "open", report: report.trim() || null });
      if (done && task.status !== "done") store.patchTask(await post<Task>(`/tasks/${task.id}/status`, { status: "done" }));
      onChanged();
    } catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="inbox-body">
      {task.description && <p className="inbox-desc">{task.description}</p>}
      {delegation?.comment && <p className="inbox-desc"><b>Что ждут:</b> {delegation.comment}</p>}
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="hint">Статус:</span>
        {STATUSES.map((s) => (
          <button key={s} className={`chip ${task.status === s ? "on" : ""}`} disabled={busy} onClick={() => setStatus(s)}>{STATUS_LABEL[s]}</button>
        ))}
        {delegation?.check_at && <span className="hint" style={{ marginLeft: "auto" }}>проверка {showDateTime(delegation.check_at)}</span>}
      </div>
      {delegation && (
        <div className="field">
          <label>Отчёт для {task.owner?.name ?? "автора"}</label>
          <textarea className="textarea" rows={3} value={report} onChange={(e) => setReport(e.target.value)} placeholder="Что сделано, что мешает, когда будет готово" />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn sm" onClick={() => saveReport(false)} disabled={busy}>Сохранить отчёт</button>
            <button className="btn primary sm" onClick={() => saveReport(true)} disabled={busy}>Выполнено</button>
          </div>
          {delegation.status === "done" && <span className="hint">Поручение отмечено выполненным{delegation.report ? ` · «${delegation.report}»` : ""}</span>}
        </div>
      )}
    </div>
  );
}
