// v1.5 — планнер вкладкой внутри платформы CIS.
// Симптом, который проверяем: внутри рамки кнопка «Войти через Microsoft» бесполезна (форма Microsoft
// отдаёт X-Frame-Options: DENY и в рамке не открывается). Значит в рамке её быть не должно,
// а вместо неё — объяснение и выход в отдельную вкладку.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "../Account";
import { applyEmbedFlag, isEmbedded } from "../embed";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => ({ microsoft: true, guest_login: true })), post: vi.fn() };
});

/** jsdom: имитируем жизнь в чужой рамке (window.top !== window.self). */
function pretendFramed() {
  const fake = {} as Window;
  vi.spyOn(window, "top", "get").mockReturnValue(fake);
}

afterEach(() => {
  vi.restoreAllMocks();
  delete document.documentElement.dataset.embed;
  window.history.replaceState(null, "", "/");
});

describe("признак «мы в рамке»", () => {
  it("обычная вкладка — не рамка", () => {
    expect(isEmbedded()).toBe(false);
  });

  it("чужая рамка распознаётся и без параметра в адресе", () => {
    pretendFramed();
    expect(isEmbedded()).toBe(true);
  });

  it("?embed=1 в адресе тоже включает режим и ставит признак на <html>", () => {
    window.history.replaceState(null, "", "/?embed=1");
    expect(isEmbedded()).toBe(true);
    applyEmbedFlag();
    expect(document.documentElement.dataset.embed).toBe("1");
  });
});

describe("экран входа внутри платформы", () => {
  it("вместо кнопки Microsoft — объяснение и ссылка в отдельную вкладку", async () => {
    pretendFramed();
    render(<LoginScreen />);
    await waitFor(() => expect(screen.getByText(/Сессия планнера не открылась/)).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /Войти через Microsoft/ })).toBeNull();
    expect(screen.queryByLabelText("Пароль")).toBeNull();
    const out = screen.getByRole("link", { name: /Открыть планнер в отдельной вкладке/ });
    expect(out).toHaveAttribute("target", "_blank");
  });

  it("в обычной вкладке экран входа прежний", async () => {
    render(<LoginScreen />);
    await waitFor(() => expect(screen.getByRole("link", { name: /Войти через Microsoft/ })).toBeInTheDocument());
  });
});
