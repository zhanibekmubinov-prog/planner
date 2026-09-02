import { useEffect, useState } from "react";
import { api, Direction } from "./api";

// Шаг 0: заглушка, проверяющая связь с API. Настоящий UI — шаг 2.
export default function App() {
  const [dirs, setDirs] = useState<Direction[]>([]);
  const [err, setErr] = useState<string>();
  useEffect(() => { api<Direction[]>("/directions").then(setDirs).catch((e) => setErr(String(e))); }, []);
  return (
    <main style={{ fontFamily: "system-ui", padding: 24 }}>
      <h1>Planner</h1>
      {err && <p style={{ color: "crimson" }}>API недоступен: {err}</p>}
      <ul>{dirs.map((d) => <li key={d.id}>{d.name}</li>)}</ul>
      {!err && dirs.length === 0 && <p>Направлений пока нет — создайте первое через /docs.</p>}
    </main>
  );
}
