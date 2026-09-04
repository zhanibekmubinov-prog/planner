// К2 (и С4/С9) — диалог подтверждения: фокус, Enter, Escape, повторный вызов.
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmProvider, useConfirm } from "../confirm";

type Opts = Parameters<ReturnType<typeof useConfirm>>[1];

/** Кнопка, открывающая confirm; результат промиса пишем в data-result и в массив results. */
function Harness({ text, opts, results }: { text: string; opts?: Opts; results: (boolean | "pending")[] }) {
  const confirm = useConfirm();
  const [last, setLast] = useState<string>("none");
  return (
    <button data-result={last} onClick={() => {
      const idx = results.push("pending") - 1;
      void confirm(text, opts).then((v) => { results[idx] = v; setLast(String(v)); });
    }}>open</button>
  );
}

async function open(text = "Удалить?", opts?: Opts) {
  const results: (boolean | "pending")[] = [];
  render(<ConfirmProvider><Harness text={text} opts={opts} results={results} /></ConfirmProvider>);
  await act(async () => { fireEvent.click(screen.getByText("open")); });
  const dialog = screen.getByRole("alertdialog");
  return { results, dialog, opener: screen.getByText("open") };
}
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

afterEach(() => vi.restoreAllMocks());

describe("ConfirmProvider — рендер", () => {
  it("открывается как alertdialog; для danger заголовок «Подтвердите удаление», кнопка «Удалить»", async () => {
    const { dialog } = await open("Точно?", { danger: true });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Подтвердите удаление");
    expect(screen.getByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();
    expect(screen.getByText("Точно?")).toBeInTheDocument();
  });

  it("okLabel/title/cancelLabel подставляются", async () => {
    await open("x", { danger: true, okLabel: "Удалить направление", title: "Удалить направление?", cancelLabel: "Нет" });
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Удалить направление?");
    expect(screen.getByRole("button", { name: "Удалить направление" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Нет" })).toBeInTheDocument();
  });
});

describe("ConfirmProvider — К2: опасное действие не должно быть «на Enter»", () => {
  it("К2: при danger в фокусе НЕ красная кнопка (ожидаем фокус на «Отмена»)", async () => {
    await open("Удалить направление?", { danger: true });
    const danger = screen.getByRole("button", { name: "Удалить" });
    const cancel = screen.getByRole("button", { name: "Отмена" });
    expect(document.activeElement).not.toBe(danger);
    expect(document.activeElement).toBe(cancel);
  });

  it("К2: Enter сразу после открытия danger-диалога НЕ подтверждает удаление", async () => {
    const user = userEvent.setup();
    const { results } = await open("Удалить направление?", { danger: true });
    await user.keyboard("{Enter}");
    await flush();
    expect(results[0]).not.toBe(true);
  });

  it("С4/С9: Enter при открытом диалоге не долетает до других window-слушателей", async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    window.addEventListener("keydown", spy);
    try {
      await open("Удалить ветку?", { danger: true });
      spy.mockClear();
      await user.keyboard("{Enter}");
      expect(spy).not.toHaveBeenCalled();
    } finally { window.removeEventListener("keydown", spy); }
  });

  it("повторный ask() при открытом диалоге: первый промис резолвится false, а не висит вечно", async () => {
    const { results } = await open("первый", { danger: true });
    await act(async () => { fireEvent.click(screen.getByText("open")); });   // второй вызов поверх первого
    await flush();
    expect(results[0]).toBe(false);
    expect(results[1]).toBe("pending");
  });
});

describe("ConfirmProvider — регрессия", () => {
  it("клик по OK → true", async () => {
    const { results } = await open("x", { danger: true });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Удалить" })); });
    await flush();
    expect(results[0]).toBe(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("клик по «Отмена» → false", async () => {
    const { results } = await open("x", { danger: true });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Отмена" })); });
    await flush();
    expect(results[0]).toBe(false);
  });

  it("Escape → false и не долетает до других слушателей", async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    window.addEventListener("keydown", spy);
    try {
      const { results } = await open("x", { danger: true });
      spy.mockClear();
      await user.keyboard("{Escape}");
      await flush();
      expect(results[0]).toBe(false);
      expect(spy).not.toHaveBeenCalled();
    } finally { window.removeEventListener("keydown", spy); }
  });

  it("клик по фону → false; клик по тексту внутри модалки — диалог остаётся", async () => {
    const { results, dialog } = await open("Текст вопроса", { danger: true });
    await act(async () => { fireEvent.mouseDown(screen.getByText("Текст вопроса")); });
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    expect(results[0]).toBe("pending");
    await act(async () => { fireEvent.mouseDown(dialog.parentElement!); });
    await flush();
    expect(results[0]).toBe(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
