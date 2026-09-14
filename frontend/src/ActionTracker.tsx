// Action Tracker (v1.6) — все проекты и задачи одной таблицей, как в рабочем протоколе совещания:
// полоса направления → строка проекта → строки задач. У каждой задачи видно ответственного и срок,
// статус, ответственного, срок и план действий можно менять прямо в строке (решение владельца 2026-09-14).
//
// Таблица только собирает то, что уже есть в сторе: отдельных запросов на ответственных нет —
// они приходят в задаче (TaskOut.assignees, v1.6).
import { useMemo, useState } from "react";
import {
  canEdit, del, Direction, dirColor, errorText, isOverdue, nTasks, post, Project, projColor, put, showDate,
  STATUS_LABEL, STATUSES, Task, TaskStatus, toIn,
} from "./api";
import { copyText, fileName, saveFile } from "./mindmapExport";
import { Store } from "./store";
import { useToast } from "./toast";

type Props = { store: Store; onOpenTask: (t: Task) => void; onOpenProject: (p: Project) => void; onOpenDirection: (d: Direction) => void };

type Row = { task: Task; project: Project | null };
type Group = { direction: Direction; projects: { project: Project | null; rows: Row[] }[]; total: number; overdue: number };

const NO_PROJECT = "Без проекта";

export default function ActionTracker({ store, onOpenTask, onOpenProject, onOpenDirection }: Props) {
  const [hideDone, setHideDone] = useState(true);
  const [onlyMine, setOnlyMine] = useState(false);
  const [onlyLate, setOnlyLate] = useState(false);
  const [q, setQ] = useState("");
  const [dirFilter, setDirFilter] = useState<number | "all">("all");
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();

  const groups = useMemo(
    () => buildGroups(store, { hideDone, onlyMine, onlyLate, q: q.trim().toLowerCase(), dirFilter }),
    [store.tasks, store.projects, store.directions, store.me, hideDone, onlyMine, onlyLate, q, dirFilter], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const rows = groups.flatMap((g) => g.projects.flatMap((p) => p.rows));
  const late = rows.filter((r) => r.task.status !== "done" && r.task.deadline && isOverdue(`${r.task.deadline}T23:59:59`)).length;
  const noOwner = rows.filter((r) => r.task.status !== "done" && !(r.task.assignees ?? []).length).length;

  // ── Правка прямо в строке ───────────────────────────────────────────────
  async function patch(t: Task, changes: Partial<Task>) {
    setBusy(t.id);
    const before = t;
    store.patchTask({ ...t, ...changes });
    try {
      const body = { ...toIn({ ...t, ...changes }), updated_at: t.updated_at };
      store.patchTask(await put<Task>(`/tasks/${t.id}`, body));
    } catch (e) { store.patchTask(before); store.setError(errorText(e)); void store.reloadTasks(); } finally { setBusy(null); }
  }

  async function setStatus(t: Task, status: TaskStatus) {
    if (t.status === status) return;
    if (t.access === "assignee") {   // исполнителю разрешён только статус — отдельным запросом
      setBusy(t.id);
      store.patchTask({ ...t, status });
      try { store.patchTask(await post<Task>(`/tasks/${t.id}/status`, { status })); }
      catch (e) { store.patchTask(t); store.setError(errorText(e)); void store.reloadTasks(); } finally { setBusy(null); }
      return;
    }
    await patch(t, { status });
  }

  /** Ответственный: одно поручение на задачу в этой таблице — меняем на выбранного, пусто — снимаем. */
  async function setAssignee(t: Task, personId: number | null) {
    const current = (t.assignees ?? [])[0] ?? null;
    if ((current?.person_id ?? null) === personId) return;
    setBusy(t.id);
    try {
      if (current) await del(`/delegations/${current.delegation_id}`);
      if (personId) await post("/delegations", { task_id: t.id, person_id: personId, status: "open" });
      await store.reloadTasks();
    } catch (e) { store.setError(errorText(e)); void store.reloadTasks(); } finally { setBusy(null); }
  }

  // ── Выгрузка ────────────────────────────────────────────────────────────
  const table = () => tableRows(groups);
  async function copyAll() {
    const ok = await copyText(table().map((r) => r.join("\t")).join("\n"));
    toast(ok ? "Таблица скопирована — вставьте в письмо или в Excel" : "Скопировать не удалось — выделите таблицу вручную");
  }
  async function toExcel() {
    // ; как разделитель и BOM — чтобы Excel с русской локалью открыл файл сразу и без «кракозябр»
    const csv = table().map((r) => r.map(csvCell).join(";")).join("\r\n");
    await saveFile(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }), fileName(`Action Tracker ${new Date().toLocaleDateString("ru-RU")}`, "csv"));
    toast("Файл для Excel скачан");
  }

  const people = store.people;

  return (
    <div className="page tracker-page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2><span className="swatch tracker" />Action Tracker</h2>
        <span className="spacer" />
        <button className="btn ghost sm" onClick={copyAll} disabled={!rows.length}>Скопировать</button>
        <button className="btn ghost sm" onClick={toExcel} disabled={!rows.length}>Excel…</button>
      </div>
      <p className="hint">
        Всё, что в работе, одним листом: направление → проект → задачи. Статус, ответственного, срок и план действий
        можно менять прямо в строке — это те же задачи, что на досках.
      </p>

      <div className="tracker-bar">
        <input className="input sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="найти задачу, проект или человека…" aria-label="Поиск по таблице" />
        <select className="select sm" value={dirFilter} onChange={(e) => setDirFilter(e.target.value === "all" ? "all" : Number(e.target.value))} aria-label="Направление">
          <option value="all">Все направления</option>
          {store.directions.filter((d) => d.status !== "archived").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <label className="tab check"><input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} /> скрыть готовые</label>
        <label className="tab check"><input type="checkbox" checked={onlyLate} onChange={(e) => setOnlyLate(e.target.checked)} /> только просроченные</label>
        <label className="tab check"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /> только мои</label>
        <span className="spacer" />
        <span className="hint mono">{nTasks(rows.length)}{late ? ` · ${late} просрочено` : ""}{noOwner ? ` · ${noOwner} без ответственного` : ""}</span>
      </div>

      {rows.length === 0 ? (
        <div className="state" style={{ flex: "none", padding: "60px 20px" }}>
          <h3>Нечего показать</h3>
          <p>{store.tasks.length ? "Под фильтры ничего не попало — снимите «скрыть готовые» или выберите другое направление." : "Задачи появятся здесь, как только вы их заведёте."}</p>
        </div>
      ) : (
        <div className="tracker-wrap">
          <table className="tracker">
            <thead>
              <tr>
                <th className="c-task">Задача</th>
                <th className="c-who">Ответственный</th>
                <th className="c-due">Срок</th>
                <th className="c-st">Статус</th>
                <th className="c-plan">План действий</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const color = dirColor(g.direction);
                return (
                  <TrackerGroup key={g.direction.id} g={g} color={color} store={store} people={people} busy={busy}
                    onOpenTask={onOpenTask} onOpenProject={onOpenProject} onOpenDirection={onOpenDirection}
                    onStatus={setStatus} onAssignee={setAssignee} onPatch={patch} />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TrackerGroup({ g, color, store, people, busy, onOpenTask, onOpenProject, onOpenDirection, onStatus, onAssignee, onPatch }: {
  g: Group; color: string; store: Store; people: Store["people"]; busy: number | null;
  onOpenTask: (t: Task) => void; onOpenProject: (p: Project) => void; onOpenDirection: (d: Direction) => void;
  onStatus: (t: Task, s: TaskStatus) => void; onAssignee: (t: Task, id: number | null) => void; onPatch: (t: Task, c: Partial<Task>) => void;
}) {
  return (
    <>
      <tr className="tr-dir" style={{ ["--dir" as string]: color }}>
        <th colSpan={5} scope="colgroup">
          <button className="tr-dir-name" onClick={() => onOpenDirection(g.direction)} title="Открыть карту проектов">
            <span className="swatch" style={{ background: color }} />{g.direction.name}
          </button>
          <span className="hint mono">{nTasks(g.total)}{g.overdue ? ` · ${g.overdue} просрочено` : ""}</span>
        </th>
      </tr>
      {g.projects.map(({ project, rows }) => (
        <ProjectBlock key={project?.id ?? "none"} project={project} rows={rows} color={project ? projColor(project, store.directions) : color}
          people={people} busy={busy} onOpenTask={onOpenTask} onOpenProject={onOpenProject}
          onStatus={onStatus} onAssignee={onAssignee} onPatch={onPatch} />
      ))}
    </>
  );
}

function ProjectBlock({ project, rows, color, people, busy, onOpenTask, onOpenProject, onStatus, onAssignee, onPatch }: {
  project: Project | null; rows: Row[]; color: string; people: Store["people"]; busy: number | null;
  onOpenTask: (t: Task) => void; onOpenProject: (p: Project) => void;
  onStatus: (t: Task, s: TaskStatus) => void; onAssignee: (t: Task, id: number | null) => void; onPatch: (t: Task, c: Partial<Task>) => void;
}) {
  return (
    <>
      <tr className="tr-proj" style={{ ["--dir" as string]: color }}>
        <th colSpan={5} scope="colgroup">
          {project ? (
            <button className="tr-proj-name" onClick={() => onOpenProject(project)} title="Открыть доску проекта">
              <span className="swatch" style={{ background: color }} />{project.name}
              {project.status === "paused" && <span className="tag">на паузе</span>}
            </button>
          ) : (
            <span className="tr-proj-name muted"><span className="swatch hollow" style={{ borderColor: color }} />{NO_PROJECT}</span>
          )}
          {project?.goal && <span className="hint">{project.goal}</span>}
        </th>
      </tr>
      {rows.map(({ task }) => (
        <TaskRow key={task.id} t={task} color={color} people={people} busy={busy === task.id}
          onOpen={() => onOpenTask(task)} onStatus={onStatus} onAssignee={onAssignee} onPatch={onPatch} />
      ))}
    </>
  );
}

function TaskRow({ t, color, people, busy, onOpen, onStatus, onAssignee, onPatch }: {
  t: Task; color: string; people: Store["people"]; busy: boolean; onOpen: () => void;
  onStatus: (t: Task, s: TaskStatus) => void; onAssignee: (t: Task, id: number | null) => void; onPatch: (t: Task, c: Partial<Task>) => void;
}) {
  const editable = canEdit(t.access);
  const assignee = (t.assignees ?? [])[0] ?? null;
  const overdue = t.status !== "done" && !!t.deadline && isOverdue(`${t.deadline}T23:59:59`);
  const [plan, setPlan] = useState(t.description ?? "");
  const [dateOpen, setDateOpen] = useState(false);
  const [planId, setPlanId] = useState(t.id);
  if (planId !== t.id) { setPlanId(t.id); setPlan(t.description ?? ""); }   // строка переиспользована под другую задачу

  return (
    <tr className={`tr-task ${t.status === "done" ? "done" : ""} ${busy ? "busy" : ""}`} style={{ ["--dir" as string]: color }}>
      <td className="c-task">
        <button className="tr-title" onClick={onOpen} title="Открыть карточку задачи">
          <span className={`st st-${t.status}`} aria-hidden="true" />
          <span className="tt">{t.title}</span>
        </button>
        <span className="mono code">#{t.id}</span>
      </td>
      <td className="c-who">
        {editable ? (
          <select className="cell-edit" value={assignee?.person_id ?? ""} disabled={busy}
            onChange={(e) => onAssignee(t, e.target.value ? Number(e.target.value) : null)}
            aria-label={`Ответственный: ${t.title}`}>
            <option value="">— не назначен —</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            {assignee && !people.some((p) => p.id === assignee.person_id) && <option value={assignee.person_id}>{assignee.name}</option>}
          </select>
        ) : (
          <span className={assignee ? "" : "muted"}>{assignee?.name ?? "—"}</span>
        )}
      </td>
      <td className={`c-due ${overdue ? "over" : ""}`}>
        {!editable ? (
          <span className="mono">{t.deadline ? showDate(t.deadline) : "—"}</span>
        ) : t.deadline || dateOpen ? (
          <input type="date" className="cell-edit mono" value={t.deadline ?? ""} disabled={busy} autoFocus={dateOpen && !t.deadline}
            onChange={(e) => onPatch(t, { deadline: e.target.value || null })}
            onBlur={() => setDateOpen(false)} aria-label={`Срок: ${t.title}`} />
        ) : (
          /* пустое поле даты рисует «mm/dd/yyyy» в каждой строке — шумно; показываем прочерк до клика */
          <button className="cell-edit empty-date mono" onClick={() => setDateOpen(true)} aria-label={`Срок: ${t.title}`}>—</button>
        )}
      </td>
      <td className="c-st">
        {editable || t.access === "assignee" ? (
          <select className={`cell-edit st-select st-${t.status}`} value={t.status} disabled={busy}
            onChange={(e) => onStatus(t, e.target.value as TaskStatus)} aria-label={`Статус: ${t.title}`}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        ) : (
          <span className={`tag st-tag st-${t.status}`}>{STATUS_LABEL[t.status]}</span>
        )}
      </td>
      <td className="c-plan">
        {editable ? (
          <textarea className="cell-edit plan" rows={1} value={plan} disabled={busy} placeholder="что делаем дальше…"
            onChange={(e) => setPlan(e.target.value)}
            onBlur={() => { if (plan !== (t.description ?? "")) onPatch(t, { description: plan || null }); }}
            onKeyDown={(e) => { if (e.key === "Escape") { setPlan(t.description ?? ""); (e.target as HTMLTextAreaElement).blur(); } }}
            aria-label={`План действий: ${t.title}`} />
        ) : (
          <span className="plan-ro">{t.description || "—"}</span>
        )}
      </td>
    </tr>
  );
}

// ── Сборка таблицы ────────────────────────────────────────────────────────

type Filters = { hideDone: boolean; onlyMine: boolean; onlyLate: boolean; q: string; dirFilter: number | "all" };

/** Направление → проекты (и «Без проекта») → задачи. Направления без подходящих задач не показываем. */
export function buildGroups(store: Store, f: Filters): Group[] {
  const myPersonIds = new Set(store.people.filter((p) => store.me && p.user_id === store.me.id).map((p) => p.id));
  const keep = (t: Task) => {
    if (f.hideDone && t.status === "done") return false;
    if (f.onlyLate && !(t.status !== "done" && t.deadline && isOverdue(`${t.deadline}T23:59:59`))) return false;
    if (f.onlyMine && !(t.assigned_to_me || (t.assignees ?? []).some((a) => myPersonIds.has(a.person_id)))) return false;
    if (f.q) {
      const hay = `${t.title} ${t.description ?? ""} ${(t.assignees ?? []).map((a) => a.name).join(" ")}`.toLowerCase();
      if (!hay.includes(f.q)) return false;
    }
    return true;
  };
  const byOrder = (a: Task, b: Task) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.priority - b.priority || (a.deadline || "9").localeCompare(b.deadline || "9");
  const dirs = store.directions.filter((d) => d.status !== "archived" && (f.dirFilter === "all" || d.id === f.dirFilter));
  const out: Group[] = [];
  for (const d of dirs) {
    const mine = store.tasks.filter((t) => t.directions.some((x) => x.id === d.id) && keep(t));
    const ps = store.projects.filter((p) => p.direction_id === d.id && p.status !== "archived")
      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id);
    const blocks: Group["projects"] = [];
    for (const p of ps) {
      const rows = mine.filter((t) => t.project_id === p.id).sort(byOrder).map((task) => ({ task, project: p }));
      if (rows.length) blocks.push({ project: p, rows });
    }
    const loose = mine.filter((t) => t.project_id == null || !store.projects.some((p) => p.id === t.project_id)).sort(byOrder).map((task) => ({ task, project: null }));
    if (loose.length) blocks.push({ project: null, rows: loose });
    const total = blocks.reduce((s, b) => s + b.rows.length, 0);
    if (total) {
      out.push({
        direction: d, projects: blocks, total,
        overdue: blocks.flatMap((b) => b.rows).filter((r) => r.task.status !== "done" && r.task.deadline && isOverdue(`${r.task.deadline}T23:59:59`)).length,
      });
    }
  }
  return out;
}

/** Плоская таблица для копирования и Excel: шапка + по строке на задачу. */
export function tableRows(groups: Group[]): string[][] {
  const rows: string[][] = [["Направление", "Проект", "Задача", "Ответственный", "Срок", "Статус", "План действий"]];
  for (const g of groups) {
    for (const b of g.projects) {
      for (const { task } of b.rows) {
        rows.push([
          g.direction.name, b.project?.name ?? NO_PROJECT, task.title,
          (task.assignees ?? []).map((a) => a.name).join(", "),
          task.deadline ?? "", STATUS_LABEL[task.status], (task.description ?? "").replace(/\s*\n\s*/g, " "),
        ]);
      }
    }
  }
  return rows;
}

const csvCell = (s: string) => (/[";\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
