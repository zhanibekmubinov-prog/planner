// Конфиг тестов. Отдельный от vite.config.ts, чтобы не тянуть PWA-плагин в jsdom.
// Запуск: npm test  (= vitest run).  TZ фиксируем, чтобы тесты дат не зависели от машины.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

process.env.TZ = process.env.TZ || "America/New_York";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
    css: false,
  },
});
