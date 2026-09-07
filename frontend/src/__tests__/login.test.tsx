// Экран входа (урок 2026-09-07): гость с gmail нажал единственную большую кнопку Microsoft и получил AADSTS50020,
// потому что форма гостя была спрятана за ссылкой. Проверяем тем же симптомом: поля почты и пароля видны сразу, оба входа подписаны.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "../Account";

vi.mock("../api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api")>();
  return { ...orig, api: vi.fn(async () => ({ microsoft: true, guest_login: true })), post: vi.fn() };
});

afterEach(() => vi.restoreAllMocks());

describe("LoginScreen", () => {
  it("форма гостя видна без лишних кликов, оба входа подписаны", async () => {
    render(<LoginScreen />);
    await waitFor(() => expect(screen.getByRole("link", { name: /Войти через Microsoft/ })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Сотрудник CIS" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Внешний участник" })).toBeInTheDocument();
    expect(screen.getByLabelText("Почта")).toBeInTheDocument();
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Войти как внешний участник" })).toBeDisabled();   // пока почта и пароль пустые
    expect(screen.queryByText(/Я внешний участник — вход по паролю/)).toBeNull();                // прежней скрытой ссылки больше нет
  });
});
