// Чистые функции: api.ts (даты, доступ, цвета), Overview.buildReport, Checklist.checklistProgress, plural (через рендер).
// TZ в vitest.config.ts = America/New_York (отрицательный пояс) — чтобы поймать Н6.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  canEdit, dirColor, DIRECTION_COLORS, fromDateTimeInput, isOverdue, isShared, newNodeId, projColor, showDate, toDateInput, toDateTimeInput,
} from "../api";
import { checklistProgress } from "../Checklist";
import DirectionPage from "../DirectionPage";
import { buildReport } from "../Overview";
import { makeDirection, makeProject, makeStore, makeTask } from "./fixtures";

afterEach(() => vi.useRealTimers());

describe("api.ts — isOverdue", () => {
  it("пусто → false", () => {
    expect(isOverdue(null)).toBe(false);
    expect(isOverdue(undefined)).toBe(false);
    expect(isOverdue("")).toBe(false);
  });
  it("прошедшая ISO с Z → true, будущая → false", () => {
    expect(isOverdue("2000-01-01T00:00:00Z")).toBe(true);
    expect(isOverdue("2999-01-01T00:00:00Z")).toBe(false);
  });
  it("строка без Z сравнивается как локальное время: граница 23:59:59 / 00:00:00", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 4, 23, 59, 58));
    expect(isOverdue("2026-09-04T23:59:59")).toBe(false);
    vi.setSystemTime(new Date(2026, 8, 5, 0, 0, 0));
    expect(isOverdue("2026-09-04T23:59:59")).toBe(true);
  });
});

describe("api.ts — showDate (Н6)", () => {
  it("Н6: дата без времени показывается тем же днём в любом часовом поясе", () => {
    expect(new Date(2026, 0, 1).getTimezoneOffset()).toBeGreaterThan(0);   // отрицательный пояс (TZ из vitest.config.ts)
    expect(showDate("2026-09-04")).toBe("04 сент.");
  });
  it("null/undefined → пустая строка", () => {
    expect(showDate(null)).toBe("");
    expect(showDate(undefined)).toBe("");
  });
});

describe("api.ts — преобразование дат для <input>", () => {
  it("round-trip fromDateTimeInput(toDateTimeInput(iso)) сохраняет момент времени", () => {
    const iso = "2026-09-04T10:30:00.000Z";
    expect(fromDateTimeInput(toDateTimeInput(iso))).toBe(iso);
  });
  it("пустые значения", () => {
    expect(fromDateTimeInput("")).toBeNull();
    expect(toDateTimeInput(null)).toBe("");
    expect(toDateInput(null)).toBe("");
    expect(toDateInput("2026-09-04T10:30:00Z")).toBe("2026-09-04");
  });
});

describe("api.ts — доступ и цвета", () => {
  it("canEdit / isShared", () => {
    expect(canEdit(undefined)).toBe(true); expect(canEdit(null)).toBe(true);
    expect(canEdit("owner")).toBe(true); expect(canEdit("edit")).toBe(true);
    expect(canEdit("view")).toBe(false); expect(canEdit("via")).toBe(false); expect(canEdit("assignee")).toBe(false);
    expect(isShared("edit")).toBe(true); expect(isShared("view")).toBe(true);
    expect(isShared("owner")).toBe(false); expect(isShared("via")).toBe(false); expect(isShared("assignee")).toBe(false); expect(isShared(null)).toBe(false);
  });
  it("dirColor: свой цвет приоритетнее палитры; id=0 → первый цвет", () => {
    expect(dirColor(makeDirection({ id: 3, color: "#123456" }))).toBe("#123456");
    expect(dirColor(makeDirection({ id: 0, color: null }))).toBe(DIRECTION_COLORS[0]);
    expect(dirColor(makeDirection({ id: 9, color: null }))).toBe(DIRECTION_COLORS[1]);
  });
  it("projColor: свой цвет → цвет направления → запасной", () => {
    const d = makeDirection({ id: 1, color: "#abcdef" });
    expect(projColor(makeProject({ color: "#000000", direction_id: 1 }), [d])).toBe("#000000");
    expect(projColor(makeProject({ color: null, direction_id: 1 }), [d])).toBe("#abcdef");
    expect(projColor(makeProject({ color: null, direction_id: 77 }), [d])).toBe("var(--line-strong)");
  });
  it("newNodeId: 1–8 символов [a-z0-9], 10 000 вызовов без коллизий", () => {
    const ids = new Set<string>();
    for (let i = 0; i < 10_000; i++) {
      const id = newNodeId();
      expect(id).toMatch(/^[a-z0-9]{1,8}$/);
      ids.add(id);
    }
    expect(ids.size).toBe(10_000);
  });
});

describe("Checklist.checklistProgress", () => {
  it("пусто → нули", () => {
    expect(checklistProgress(undefined)).toEqual({ total: 0, done: 0, pct: 0 });
    expect(checklistProgress(null)).toEqual({ total: 0, done: 0, pct: 0 });
    expect(checklistProgress([])).toEqual({ total: 0, done: 0, pct: 0 });
  });
  it("[done, done, open] → 3/2/67; всё выполнено → 100", () => {
    const it_ = (done: boolean, i: number) => ({ id: String(i), text: "x", done });
    expect(checklistProgress([it_(true, 1), it_(true, 2), it_(false, 3)])).toEqual({ total: 3, done: 2, pct: 67 });
    expect(checklistProgress([it_(true, 1), it_(true, 2)])).toEqual({ total: 2, done: 2, pct: 100 });
  });
});

describe("Overview.buildReport", () => {
  const dir = makeDirection({ id: 1 });
  const NOW = new Date(2026, 8, 4, 12, 0, 0).getTime();   // 4 сентября 2026, полдень локально
  const DAY = 86_400_000;
  const at = (ms: number) => new Date(ms).toISOString();

  it("нет задач → score 45, причина «нет ни одной задачи», уровень fading (45 не < 45)", () => {
    const r = buildReport(dir, [], NOW);
    expect(r.score).toBe(45);
    expect(r.reasons).toEqual(["нет ни одной задачи"]);
    expect(r.level.key).toBe("fading");
    expect(r.idleDays).toBeNull();
    expect(r.lastActivity).toBeNull();
  });

  it("пауза → score ≤ 15 и единственная причина «на паузе», даже при просрочках", () => {
    const tasks = [1, 2, 3].map((i) => makeTask({ id: i, deadline: "2026-01-01", updated_at: at(NOW - 40 * DAY) }));
    const r = buildReport({ ...dir, status: "paused" }, tasks, NOW);
    expect(r.score).toBeLessThanOrEqual(15);
    expect(r.reasons).toEqual(["на паузе"]);
    expect(r.overdue).toHaveLength(3);
  });

  it("просрочка по локальному 23:59:59: дедлайн «сегодня» не просрочен в 23:00, просрочен в 00:00 следующего дня", () => {
    const t = makeTask({ deadline: "2026-09-04", updated_at: at(NOW) });
    expect(buildReport(dir, [t], new Date(2026, 8, 4, 23, 0, 0).getTime()).overdue).toHaveLength(0);
    expect(buildReport(dir, [t], new Date(2026, 8, 5, 0, 0, 0).getTime()).overdue).toHaveLength(1);
  });

  it("idleDays: минуту назад → 0; 6 дн. → без причины; 7 и 13 → «тихо уже»; 14 → «нет движения»", () => {
    const mk = (msAgo: number) => [makeTask({ status: "in_progress", deadline: "2999-01-01", updated_at: at(NOW - msAgo) })];
    expect(buildReport(dir, mk(60_000), NOW).idleDays).toBe(0);
    const r6 = buildReport(dir, mk(6 * DAY), NOW);
    expect(r6.idleDays).toBe(6);
    expect(r6.reasons.some((x) => x.includes("дн."))).toBe(false);
    expect(buildReport(dir, mk(7 * DAY), NOW).reasons).toContain("тихо уже 7 дн.");
    expect(buildReport(dir, mk(13 * DAY), NOW).reasons).toContain("тихо уже 13 дн.");
    expect(buildReport(dir, mk(14 * DAY), NOW).reasons).toContain("нет движения 14 дн.");
  });

  it("updated_at в будущем (расхождение часов) не даёт отрицательный idleDays", () => {
    const r = buildReport(dir, [makeTask({ updated_at: at(NOW + 3_600_000) })], NOW);
    expect(r.idleDays).toBeGreaterThanOrEqual(0);
  });

  it("верхние границы: 5 просрочек → +30 (не +75); 3 пропущенные проверки → +20; итог ≤ 100 и целый", () => {
    const fresh = { status: "in_progress" as const, updated_at: at(NOW) };
    const over5 = [1, 2, 3, 4, 5].map((i) => makeTask({ id: i, deadline: "2026-01-01", ...fresh }));
    expect(buildReport(dir, over5, NOW).score).toBe(30);
    const over1 = [makeTask({ id: 1, deadline: "2026-01-01", ...fresh })];
    expect(buildReport(dir, over1, NOW).score).toBe(15);

    vi.useFakeTimers(); vi.setSystemTime(NOW);   // isOverdue(next_check_at) смотрит на Date.now()
    const checks3 = [1, 2, 3].map((i) => makeTask({ id: i, deadline: "2999-01-01", next_check_at: at(NOW - DAY), ...fresh }));
    expect(buildReport(dir, checks3, NOW).score).toBe(20);

    const worst = [1, 2, 3, 4, 5].map((i) => makeTask({ id: i, status: "backlog", deadline: "2026-01-01", next_check_at: at(NOW - DAY), updated_at: at(NOW - 45 * DAY) }));
    const r = buildReport(dir, worst, NOW);
    expect(r.score).toBeLessThanOrEqual(100);
    expect(Number.isInteger(r.score)).toBe(true);
    expect(r.level.key).toBe("lost");
  });

  it("фильтрация по направлению: чужие задачи не учитываются, задача в двух направлениях — в обоих", () => {
    const d2 = makeDirection({ id: 2, name: "Команда" });
    const only1 = makeTask({ id: 1, directions: [dir] });
    const only2 = makeTask({ id: 2, directions: [d2] });
    const both = makeTask({ id: 3, directions: [dir, d2] });
    expect(buildReport(dir, [only1, only2, both], NOW).tasks.map((t) => t.id)).toEqual([1, 3]);
    expect(buildReport(d2, [only1, only2, both], NOW).tasks.map((t) => t.id)).toEqual([2, 3]);
  });

  it("счётчики статусов при пустом наборе — нули, без NaN", () => {
    const r = buildReport(dir, [], NOW);
    expect([r.done, r.inProgress, r.waiting, r.backlog]).toEqual([0, 0, 0, 0]);
  });
});

describe("DirectionPage — plural и доли шкалы (через рендер)", () => {
  function renderWith(projects: ReturnType<typeof makeProject>[]) {
    const direction = makeDirection();
    const store = makeStore({ directions: [direction], projects, tasks: [makeTask()] });
    return render(
      <DirectionPage store={store} direction={direction} onOpenBoard={vi.fn()} onOpenTask={vi.fn()} onNewProject={vi.fn()} onEditDirection={vi.fn()}
        onDirectionMenu={vi.fn()} onProjectMenu={vi.fn()} onShare={vi.fn()} onOpenMindmap={vi.fn()} onMindmaps={vi.fn()} />,
    );
  }
  const mk = (n: number) => Array.from({ length: n }, (_, i) => makeProject({ id: 10 + i, name: `П${i}` }));
  const sub = () => document.querySelector(".ov-sub")!.textContent!;

  it("plural: 0 → проектов, 1 → проект, 2 → проекта, 5 → проектов, 21 → проект, 22 → проекта, 11 → проектов", () => {
    for (const [n, word] of [[0, "0 проектов"], [1, "1 проект "], [2, "2 проекта"], [5, "5 проектов"], [11, "11 проектов"], [21, "21 проект "], [22, "22 проекта"]] as const) {
      const { unmount } = renderWith(mk(n));
      expect(sub()).toContain(word);
      unmount();
    }
  });

  it("проект без задач: доли шкалы 0%, а не NaN%", () => {
    renderWith(mk(1));
    const card = screen.getByText("П0").closest("article")!;
    const spans = card.querySelectorAll(".stack span");
    expect(spans.length).toBe(4);
    spans.forEach((s) => expect((s as HTMLElement).style.width).toBe("0%"));
  });
});

describe("toIn (DirectionPage/TaskPanel)", () => {
  it.todo("deadline '' → null, checklist undefined → [], project_id из аргумента — функция не экспортирована из модуля; экспортировать и включить тест");
});
