// К1 / С1 — правая кнопка на карточке «Без проекта» и на строке задачи не должна открывать меню направления.
// Тесты описывают ОЖИДАЕМОЕ поведение: пока баг не исправлен, они падают (это подтверждение находки).
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DirectionPage from "../DirectionPage";
import { makeDirection, makeProject, makeStore, makeTask } from "./fixtures";

function renderPage(opts: { projects?: ReturnType<typeof makeProject>[]; tasks?: ReturnType<typeof makeTask>[] } = {}) {
  const direction = makeDirection();
  const store = makeStore({ directions: [direction], projects: opts.projects ?? [], tasks: opts.tasks ?? [makeTask()] });
  const onDirectionMenu = vi.fn();
  const onProjectMenu = vi.fn();
  render(
    <DirectionPage store={store} direction={direction}
      onOpenBoard={vi.fn()} onOpenTask={vi.fn()} onNewProject={vi.fn()} onEditDirection={vi.fn()}
      onDirectionMenu={onDirectionMenu} onProjectMenu={onProjectMenu} onShare={vi.fn()} onOpenMindmap={vi.fn()} onMindmaps={vi.fn()} />,
  );
  return { onDirectionMenu, onProjectMenu };
}

describe("DirectionPage — контекстное меню (К1, С1)", () => {
  it("К1: ПКМ на карточке «Без проекта» НЕ открывает меню направления", () => {
    const { onDirectionMenu } = renderPage();
    const card = screen.getByText("Без проекта").closest("article")!;
    expect(card).toHaveClass("loose");
    fireEvent.contextMenu(card);
    expect(onDirectionMenu).not.toHaveBeenCalled();
  });

  it("С1: ПКМ на строке задачи внутри «Без проекта» НЕ открывает меню направления", () => {
    const { onDirectionMenu } = renderPage();
    const row = screen.getByText("Согласовать КП").closest("li")!;
    fireEvent.contextMenu(row);
    expect(onDirectionMenu).not.toHaveBeenCalled();
  });

  it("К1: у карточки «Без проекта» есть своя кнопка действий «⋯»", () => {
    renderPage();
    const card = screen.getByText("Без проекта").closest("article")!;
    const more = card.querySelector("button.more");
    expect(more).not.toBeNull();
  });

  it("регрессия: ПКМ на карточке проекта открывает меню проекта, а не направления", () => {
    const project = makeProject();
    const { onDirectionMenu, onProjectMenu } = renderPage({ projects: [project], tasks: [makeTask({ project_id: project.id })] });
    const card = screen.getByText("Договор основной").closest("article")!;
    expect(card).toHaveClass("proj-card");
    fireEvent.contextMenu(card);
    expect(onProjectMenu).toHaveBeenCalledTimes(1);
    expect(onProjectMenu.mock.calls[0][0]).toMatchObject({ id: project.id });
    expect(onDirectionMenu).not.toHaveBeenCalled();
  });

  it("регрессия: у карточки проекта есть кнопка «⋯», и она открывает меню проекта", () => {
    const project = makeProject();
    const { onProjectMenu } = renderPage({ projects: [project], tasks: [] });
    fireEvent.click(screen.getByLabelText(`Действия: ${project.name}`));
    expect(onProjectMenu).toHaveBeenCalledTimes(1);
  });

  it("регрессия: ПКМ на шапке направления открывает меню направления", () => {
    const { onDirectionMenu } = renderPage();
    fireEvent.contextMenu(screen.getByRole("heading", { level: 2 }));
    expect(onDirectionMenu).toHaveBeenCalledTimes(1);
  });
});
