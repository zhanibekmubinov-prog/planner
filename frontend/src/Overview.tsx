// Карта направлений: одна страница со всеми направлениями, их задачами и шкалой внимания —
// показывает, какое направление руководитель упускает.
import { useMemo } from "react";
import { Direction, dirColor, isOverdue, showDate, STATUS_LABEL, Task } from "./api";
import { Store } from "./store";

type Level = { key: "focus" | "ok" | "fading" | "lost"; label: string; hint: string };
const LEVELS: Record<Level["key"], Level> = {
  focus: { key: "focus", label: "В фокусе", hint: "Есть движение, сроки под контролем" },
  ok: { key: "ok", label: "Норма", hint: "Работа идёт, но есть что подтянуть" },
  fading: { key: "fading", label: "Ослабло", hint: "Давно нет движения или копятся просрочки" },
  lost: { key: "lost", label: "Упущено", hint: "Направление без внимания — стоит вернуться к нему" },
};

export type DirectionReport = {
  direction: Direction; tasks: Task[]; open: Task[]; done: number; inProgress: number; waiting: number; backlog: number;
  overdue: Task[]; checkDue: Task[]; lastActivity: Date | null; idleDays: number | null; score: number; level: Level;
  reasons: string[];
};

const DAY = 86_400_000;

export function buildReport(direction: Direction, all: Task[], now = Date.now()): DirectionReport {
  const tasks = all.filter((t) => t.directions.some((d) => d.id === direction.id));
  const open = tasks.filter((t) => t.status !== "done");
  const count = (s: Task["status"]) => tasks.filter((t) => t.status === s).length;
  const overdue = open.filter((t) => t.deadline && new Date(`${t.deadline}T23:59:59`).getTime() < now);
  const checkDue = open.filter((t) => isOverdue(t.next_check_at));
  const stamps = tasks.map((t) => new Date(t.updated_at || t.created_at).getTime());
  const last = stamps.length ? Math.max(...stamps) : null;
  const idleDays = last === null ? null : Math.floor((now - last) / DAY);

  // Долг внимания 0–100: чем выше, тем сильнее направление запущено
  const reasons: string[] = [];
  let score = 0;
  if (tasks.length === 0) { score += 45; reasons.push("нет ни одной задачи"); }
  else if (idleDays !== null) {
    const idle = Math.min(idleDays, 30) / 30 * 40;
    score += idle;
    if (idleDays >= 14) reasons.push(`нет движения ${idleDays} дн.`);
    else if (idleDays >= 7) reasons.push(`тихо уже ${idleDays} дн.`);
  }
  if (overdue.length) { score += Math.min(overdue.length * 15, 30); reasons.push(`просрочено ${overdue.length}`); }
  if (checkDue.length) { score += Math.min(checkDue.length * 10, 20); reasons.push(`пропущено проверок ${checkDue.length}`); }
  if (open.length > 0 && count("in_progress") === 0) { score += 10; reasons.push("ничего не в работе"); }
  if (open.length > 0 && open.every((t) => !t.deadline && !t.next_check_at)) { score += 5; reasons.push("ни у одной задачи нет срока"); }
  if (direction.status === "paused") { score = Math.min(score, 15); reasons.length = 0; reasons.push("на паузе"); }
  score = Math.round(Math.min(score, 100));
  const level = score < 20 ? LEVELS.focus : score < 45 ? LEVELS.ok : score < 70 ? LEVELS.fading : LEVELS.lost;

  return {
    direction, tasks, open, done: count("done"), inProgress: count("in_progress"), waiting: count("waiting"), backlog: count("backlog"),
    overdue, checkDue, lastActivity: last === null ? null : new Date(last), idleDays, score, level, reasons,
  };
}

type Props = { store: Store; onOpenDirection: (id: number) => void; onOpenTask: (directionId: number, taskId: number) => void; onNewDirection: () => void; onDirectionMenu: (d: Direction, e: React.MouseEvent) => void };

export default function Overview({ store, onOpenDirection, onOpenTask, onNewDirection, onDirectionMenu }: Props) {
  const reports = useMemo(() => {
    const now = Date.now();
    return store.directions
      .filter((d) => d.status !== "archived" && d.access !== "via")
      .map((d) => buildReport(d, store.tasks, now))
      .sort((a, b) => (a.direction.status === "paused" ? 1 : 0) - (b.direction.status === "paused" ? 1 : 0) || b.score - a.score);
  }, [store.directions, store.tasks]);

  const active = reports.filter((r) => r.direction.status !== "paused");
  const totalOpen = active.reduce((n, r) => n + r.open.length, 0);
  const totalOverdue = active.reduce((n, r) => n + r.overdue.length, 0);
  const neglected = active.filter((r) => r.level.key === "lost" || r.level.key === "fading");
  const unassigned = store.tasks.filter((t) => t.status !== "done" && t.directions.length === 0);

  if (reports.length === 0) {
    return (
      <div className="state">
        <h3>Карта пуста</h3>
        <p>Добавьте направления — здесь будет видно, какое из них требует внимания.</p>
        <button className="btn primary" onClick={onNewDirection}>+ Направление</button>
      </div>
    );
  }

  return (
    <div className="overview">
      <header className="ov-head">
        <div>
          <h2>Карта направлений</h2>
          <p className="ov-sub">
            {active.length} {plural(active.length, "направление", "направления", "направлений")} · {totalOpen} открытых задач
            {totalOverdue > 0 && <> · <span className="over">{totalOverdue} просрочено</span></>}
            {unassigned.length > 0 && <> · {unassigned.length} задач без направления</>}
          </p>
        </div>
        <div className={`ov-verdict ${neglected.length ? "warn" : "ok"}`}>
          {neglected.length === 0
            ? <><strong>Все направления в поле зрения.</strong> Провалов нет.</>
            : <><strong>Требуют внимания:</strong> {neglected.map((r) => r.direction.name).join(", ")}</>}
        </div>
      </header>

      <div className="ov-grid">
        {reports.map((r) => <DirectionCard key={r.direction.id} r={r} onOpen={() => onOpenDirection(r.direction.id)} onTask={(id) => onOpenTask(r.direction.id, id)} onMenu={(e) => onDirectionMenu(r.direction, e)} />)}
      </div>
    </div>
  );
}

function DirectionCard({ r, onOpen, onTask, onMenu }: { r: DirectionReport; onOpen: () => void; onTask: (id: number) => void; onMenu: (e: React.MouseEvent) => void }) {
  const color = dirColor(r.direction);
  const total = r.tasks.length;
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  const paused = r.direction.status === "paused";
  const topTasks = [...r.open].sort((a, b) => a.priority - b.priority || (a.deadline || "9").localeCompare(b.deadline || "9")).slice(0, 5);

  return (
    <article className={`ov-card ${paused ? "paused" : ""} state-${r.level.key}`} style={{ ["--dir" as string]: color }} onContextMenu={onMenu}>
      <header className="ov-card-head">
        <button className="ov-name" onClick={onOpen}>
          <span className="swatch" style={{ background: color }} />
          <span>{r.direction.name}</span>
        </button>
        <span className={`lvl lvl-${r.level.key}`} title={r.level.hint}>{paused ? "На паузе" : r.level.label}</span>
        <button className="more" onClick={onMenu} title="Действия с направлением" aria-label={`Действия: ${r.direction.name}`}>⋯</button>
      </header>
      {(r.direction.access === "edit" || r.direction.access === "view") && (
        <span className="tag shared-tag ov-shared">⇄ открыл {r.direction.owner?.name ?? "коллега"} · {r.direction.access === "edit" ? "редактирование" : "просмотр"}</span>
      )}
      {r.direction.goal && <p className="ov-goal">{r.direction.goal}</p>}

      {/* Шкала внимания: 0 — всё под контролем, 100 — направление брошено */}
      <div className="gauge" aria-label={`Долг внимания ${r.score} из 100`}>
        <div className="gauge-track">
          <span className="seg s1" /><span className="seg s2" /><span className="seg s3" /><span className="seg s4" />
          <span className="needle" style={{ left: `${r.score}%` }} />
        </div>
        <div className="gauge-labels"><span>в фокусе</span><span>упущено</span></div>
      </div>
      <p className="ov-reasons">{r.reasons.length ? r.reasons.join(" · ") : "движение есть, сроки соблюдаются"}</p>

      <div className="stack" title="Состав задач">
        <span style={{ width: `${pct(r.done)}%`, background: "var(--ok)" }} />
        <span style={{ width: `${pct(r.inProgress)}%`, background: color }} />
        <span style={{ width: `${pct(r.waiting)}%`, background: "var(--warn)" }} />
        <span style={{ width: `${pct(r.backlog)}%`, background: "var(--line-strong)" }} />
      </div>
      <dl className="stats">
        <div><dt>Всего</dt><dd className="mono">{total}</dd></div>
        <div><dt>Готово</dt><dd className="mono">{r.done}</dd></div>
        <div><dt>В работе</dt><dd className="mono">{r.inProgress}</dd></div>
        <div><dt>Ждём</dt><dd className="mono">{r.waiting}</dd></div>
        <div><dt>Бэклог</dt><dd className="mono">{r.backlog}</dd></div>
        <div className={r.overdue.length ? "bad" : ""}><dt>Просрочено</dt><dd className="mono">{r.overdue.length}</dd></div>
      </dl>
      <p className="ov-activity">Последнее движение: <span className="mono">{r.lastActivity ? (r.idleDays === 0 ? "сегодня" : r.idleDays === 1 ? "вчера" : `${r.idleDays} дн. назад`) : "—"}</span></p>

      {topTasks.length > 0 ? (
        <ul className="ov-tasks">
          {topTasks.map((t) => {
            const late = t.deadline && isOverdue(`${t.deadline}T23:59:59`);
            return (
              <li key={t.id}>
                <button onClick={() => onTask(t.id)}>
                  <span className={`st st-${t.status}`} title={STATUS_LABEL[t.status]} />
                  <span className="tt">{t.title}</span>
                  <span className={`mono td ${late ? "over" : ""}`}>{t.deadline ? showDate(t.deadline) : ""}</span>
                </button>
              </li>
            );
          })}
          {r.open.length > topTasks.length && <li className="more"><button onClick={onOpen}>ещё {r.open.length - topTasks.length} на доске →</button></li>}
        </ul>
      ) : (
        <p className="ov-empty">{total === 0 ? "Задач нет — добавьте первую на доске." : "Все задачи закрыты."}</p>
      )}
    </article>
  );
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}
