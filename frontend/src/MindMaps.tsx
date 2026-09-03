// Раздел «Майндмапы»: все карты — свободные, по направлениям, по задачам. Плюс общая кнопка-глиф.
import { useState } from "react";
import { Direction, dirColor, MIND_COLOR, MindMap, MindMapIn, post, showDateTime, Task } from "./api";
import { Store } from "./store";

/** Создать пустой майндмап и вернуть его. */
export async function createMindMap(store: Store, title: string, link: { direction_id?: number | null; task_id?: number | null } = {}): Promise<MindMap> {
  const body: MindMapIn = { title, direction_id: link.direction_id ?? null, task_id: link.task_id ?? null, data: { id: "root", text: title, children: [] } };
  const m = await post<MindMap>("/mindmaps", body);
  await store.reloadMindmaps();
  return m;
}

/** Кнопка-глиф майндмапа: узнаваемая форма (ветви), фирменный цвет. */
export function MindGlyph({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="2.4" fill="currentColor" />
      <circle cx="2.5" cy="3.5" r="1.6" fill="currentColor" /><circle cx="13.5" cy="3.5" r="1.6" fill="currentColor" /><circle cx="13.5" cy="12.5" r="1.6" fill="currentColor" /><circle cx="2.5" cy="12.5" r="1.6" fill="currentColor" />
      <path d="M6.2 6.6 3.6 4.4M9.8 6.6l2.6-2.2M9.8 9.4l2.6 2.2M6.2 9.4l-2.6 2.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

type BtnProps = { count: number; onClick: () => void; size?: "sm" | "md"; label?: string; title?: string };
export function MindButton({ count, onClick, size = "md", label, title }: BtnProps) {
  return (
    <button className={`mind-btn ${size} ${count ? "has" : ""}`} onClick={(e) => { e.stopPropagation(); onClick(); }} title={title ?? (count ? `Майндмапы: ${count}` : "Создать майндмап")}>
      <MindGlyph size={size === "sm" ? 12 : 14} />
      {label !== undefined ? label : count ? `Майндмап${count > 1 ? ` · ${count}` : ""}` : "Майндмап"}
    </button>
  );
}

type PageProps = { store: Store; filterDirection?: number | null; onOpen: (id: number) => void; onOpenTask: (taskId: number) => void };

export default function MindMapsPage({ store, filterDirection, onOpen, onOpenTask }: PageProps) {
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [linkDir, setLinkDir] = useState<number | "">(filterDirection ?? "");
  const [busy, setBusy] = useState(false);

  const maps = filterDirection ? store.mindmaps.filter((m) => m.direction_id === filterDirection) : store.mindmaps;
  const dirOf = (m: MindMap): Direction | undefined => store.directions.find((d) => d.id === m.direction_id);
  const taskOf = (m: MindMap): Task | undefined => store.tasks.find((t) => t.id === m.task_id);
  const filterDir = filterDirection ? store.directions.find((d) => d.id === filterDirection) : undefined;

  async function create() {
    if (!title.trim()) return;
    setBusy(true);
    try { const m = await createMindMap(store, title.trim(), { direction_id: linkDir === "" ? null : Number(linkDir) }); setCreating(false); setTitle(""); onOpen(m.id); }
    catch (e) { store.setError(String(e)); } finally { setBusy(false); }
  }

  const groups: { key: string; label: string; color?: string; items: MindMap[] }[] = [];
  const free = maps.filter((m) => !m.direction_id && !m.task_id);
  if (free.length) groups.push({ key: "free", label: "Свободные", items: free });
  for (const d of store.directions) {
    const items = maps.filter((m) => m.direction_id === d.id);
    if (items.length) groups.push({ key: `d${d.id}`, label: d.name, color: dirColor(d), items });
  }
  const orphanTask = maps.filter((m) => m.task_id && !m.direction_id);
  if (orphanTask.length) groups.push({ key: "tasks", label: "Привязаны к задачам", items: orphanTask });

  return (
    <div className="page mm-page" style={{ ["--mind" as string]: MIND_COLOR }}>
      <div className="topbar" style={{ padding: 0 }}>
        <h2><span className="mm-glyph" aria-hidden="true" />{filterDir ? `Майндмапы · ${filterDir.name}` : "Майндмапы"}</h2>
        <span className="spacer" />
        <button className="btn mind-primary" onClick={() => setCreating((v) => !v)}><MindGlyph /> Новый майндмап</button>
      </div>
      <p className="hint">Свободное поле для мыслей: разложить проблему, спланировать направление, набросать структуру задачи. Каждый майндмап можно привязать к направлению или задаче.</p>

      {creating && (
        <div className="inline-form">
          <div className="row">
            <input className="input grow" placeholder="Название — станет центральной темой" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") void create(); if (e.key === "Escape") setCreating(false); }} />
            <select className="select" style={{ width: 200 }} value={linkDir} onChange={(e) => setLinkDir(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">Без направления</option>
              {store.directions.filter((d) => d.status !== "archived").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
            <button className="btn mind-primary sm" onClick={create} disabled={busy || !title.trim()}>Создать</button>
          </div>
        </div>
      )}

      {maps.length === 0 && !creating ? (
        <div className="state">
          <h3>Майндмапов пока нет</h3>
          <p>Начните с одного — например, «Что мешает закупу» или «План на квартал».</p>
          <button className="btn mind-primary" onClick={() => setCreating(true)}><MindGlyph /> Новый майндмап</button>
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.key} className="mm-group">
            <h3 className="mm-group-title">{g.color && <span className="dot" style={{ background: g.color }} />}{g.label} <span className="n mono">{g.items.length}</span></h3>
            <div className="mm-grid">
              {g.items.map((m) => {
                const t = taskOf(m); const d = dirOf(m);
                const nodes = count(m.data) - 1;
                return (
                  <button key={m.id} className="mm-card" onClick={() => onOpen(m.id)} style={{ ["--c" as string]: d ? dirColor(d) : MIND_COLOR }}>
                    <MiniMap map={m} />
                    <div className="mm-card-body">
                      <div className="mm-card-title">{m.title}</div>
                      <div className="mm-card-meta">
                        {nodes} {plural(nodes, "узел", "узла", "узлов")} · {showDateTime(m.updated_at)}
                        {t && <> · <span className="link" onClick={(e) => { e.stopPropagation(); onOpenTask(t.id); }}>задача: {t.title}</span></>}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function count(n: MindMap["data"]): number { return (n?.children ?? []).reduce((s, c) => s + count(c), 1); }
function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

/** Миниатюра: центр и ветви первого уровня — достаточно, чтобы узнать карту. */
function MiniMap({ map }: { map: MindMap }) {
  const kids = map.data?.children ?? [];
  const n = kids.length;
  return (
    <svg className="mm-mini" viewBox="0 0 120 70" aria-hidden="true">
      {kids.slice(0, 8).map((k, i) => {
        const side = i % 2 === 0 ? 1 : -1; const row = Math.floor(i / 2); const rows = Math.ceil(Math.min(n, 8) / 2);
        const y = 35 + (row - (rows - 1) / 2) * 16; const x = 60 + side * 42;
        const color = ["#2F6FED", "#0E9F6E", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#BE185D", "#65A30D"][i % 8];
        return (
          <g key={k.id}>
            <path d={`M 60 35 C ${60 + side * 20} 35, ${x - side * 12} ${y}, ${x} ${y}`} stroke={color} strokeWidth="2" fill="none" />
            <rect x={x - (side === 1 ? 0 : 22)} y={y - 4} width="22" height="8" rx="4" fill={color} opacity="0.85" />
          </g>
        );
      })}
      <rect x="42" y="27" width="36" height="16" rx="8" fill="var(--c)" />
    </svg>
  );
}
