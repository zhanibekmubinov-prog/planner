// Заголовки статики фронта (serve читает dist/serve.json при старте).
//
// Пишем файл на СТАРТЕ, а не при сборке: адрес платформы — переменная окружения Railway
// (PLATFORM_ORIGIN), её меняют без пересборки.
//
// frame-ancestors решает, кто может держать планнер в рамке. По умолчанию — только он сам:
// пока PLATFORM_ORIGIN не задан, чужая страница планнер не встроит (защита от кликджекинга),
// и вкладка «Планнер» в платформе не заработает — это ожидаемо, переменную надо задать.
// X-Frame-Options намеренно не ставим: он умеет только «никому» или «одному», список
// источников выражает именно frame-ancestors, и современные браузеры смотрят на него.
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const dist = resolve(process.cwd(), "dist");
const origins = (process.env.PLATFORM_ORIGIN || "")
  .split(/[\s,]+/)
  .map((s) => s.trim().replace(/\/+$/, ""))
  .filter(Boolean);
const frameAncestors = ["'self'", ...origins].join(" ");

const config = {
  headers: [
    {
      source: "**",
      headers: [
        { key: "Content-Security-Policy", value: `frame-ancestors ${frameAncestors}` },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ],
    },
  ],
};

writeFileSync(resolve(dist, "serve.json"), JSON.stringify(config, null, 2) + "\n");
console.log(`[serve-headers] frame-ancestors ${frameAncestors}`);
