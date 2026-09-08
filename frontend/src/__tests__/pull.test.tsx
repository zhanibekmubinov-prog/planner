// v1.1: «потянуть сверху вниз — обновить» на телефоне. Жест срабатывает только из самого верха списка и только
// при достаточном натяжении; пока идёт обновление — крутится индикатор; на компьютере слушателей нет.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { PULL_THRESHOLD, PullIndicator, usePullToRefresh } from "../PullToRefresh";

function Probe({ onRefresh, enabled = true }: { onRefresh: () => Promise<unknown>; enabled?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const state = usePullToRefresh(ref, onRefresh, enabled);
  return (
    <div>
      <PullIndicator state={state} />
      <div data-testid="scroller" ref={ref} style={{ overflowY: "auto", height: 200 }}><div style={{ height: 2000 }}>список</div></div>
    </div>
  );
}

const touch = (y: number) => ({ touches: [{ clientY: y, clientX: 100 }] });
/** Тянем пальцем от y=100 вниз на dy пикселей и отпускаем. */
function pull(el: HTMLElement, dy: number) {
  fireEvent.touchStart(el, touch(100));
  fireEvent.touchMove(el, touch(100 + dy / 2));
  fireEvent.touchMove(el, touch(100 + dy));
  fireEvent.touchEnd(el);
}
// Длина жеста, при которой индикатор доходит до порога (damp = dy * 0.55 до порога)
const ENOUGH = Math.ceil(PULL_THRESHOLD / 0.55) + 20;

describe("Потянуть-обновить", () => {
  it("достаточное натяжение из верха списка запускает обновление; пока оно идёт — индикатор «Обновляю…»", async () => {
    let done!: () => void;
    const onRefresh = vi.fn(() => new Promise<void>((r) => { done = r; }));
    render(<Probe onRefresh={onRefresh} />);
    const el = screen.getByTestId("scroller");
    fireEvent.touchStart(el, touch(100));
    fireEvent.touchMove(el, touch(130));
    expect(screen.getByRole("status")).toHaveAccessibleName("Потяните, чтобы обновить");
    fireEvent.touchMove(el, touch(100 + ENOUGH));
    expect(screen.getByRole("status")).toHaveAccessibleName("Отпустите, чтобы обновить");
    fireEvent.touchEnd(el);
    await act(async () => {});
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveAccessibleName("Обновляю…");
    await act(async () => { done(); });
    expect(screen.getByRole("status")).toHaveAccessibleName("Обновлено");
    await act(async () => { await new Promise((r) => setTimeout(r, 500)); });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("короткое натяжение — ничего не происходит, индикатор убирается", () => {
    const onRefresh = vi.fn(async () => {});
    render(<Probe onRefresh={onRefresh} />);
    pull(screen.getByTestId("scroller"), 30);
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("если список прокручен не в самый верх — жест не срабатывает (это обычная прокрутка)", () => {
    const onRefresh = vi.fn(async () => {});
    render(<Probe onRefresh={onRefresh} />);
    const el = screen.getByTestId("scroller");
    Object.defineProperty(el, "scrollTop", { value: 120, configurable: true });
    pull(el, ENOUGH);
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("повторный жест во время обновления не запускает второе", async () => {
    let done!: () => void;
    const onRefresh = vi.fn(() => new Promise<void>((r) => { done = r; }));
    render(<Probe onRefresh={onRefresh} />);
    const el = screen.getByTestId("scroller");
    pull(el, ENOUGH);
    await act(async () => {});
    pull(el, ENOUGH);
    await act(async () => {});
    expect(onRefresh).toHaveBeenCalledTimes(1);
    await act(async () => { done(); });
  });

  it("на компьютере (enabled=false) жест ничего не делает", () => {
    const onRefresh = vi.fn(async () => {});
    render(<Probe onRefresh={onRefresh} enabled={false} />);
    pull(screen.getByTestId("scroller"), ENOUGH);
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
