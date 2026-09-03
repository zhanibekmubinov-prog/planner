// Раздел «Общие»: то, что коллеги открыли мне — направления, проекты, задачи, сгруппировано по человеку.
import { useMemo } from "react";
import { del, ENTITY_LABEL, PERMISSION_LABEL, SharedWithMe, showDate } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

type Props = { store: Store; onOpen: (s: SharedWithMe) => void };

export default function SharedPage({ store, onOpen }: Props) {
  const confirm = useConfirm();
  const groups = useMemo(() => {
    const m = new Map<string, { who: string; items: SharedWithMe[] }>();
    for (const s of store.shared) {
      const key = s.shared_by?.email ?? "?";
      const g = m.get(key) ?? { who: s.shared_by?.name ?? "Коллега", items: [] };
      g.items.push(s); m.set(key, g);
    }
    return [...m.values()].sort((a, b) => b.items.length - a.items.length);
  }, [store.shared]);

  const openCount = (s: SharedWithMe) => {
    if (s.entity_type === "task") return null;
    const ts = store.tasks.filter((t) => t.status !== "done" && (s.entity_type === "project" ? t.project_id === s.entity_id : t.directions.some((d) => d.id === s.entity_id)));
    return ts.length;
  };

  async function leave(s: SharedWithMe) {
    if (!(await confirm(`Отказаться от доступа к «${s.name}»? Снова открыть его сможет только ${s.shared_by?.name ?? "владелец"}.`, { danger: true, okLabel: "Отказаться" }))) return;
    try {
      // свой доступ можно снять самому: находим id шары через список «мне открыли» нет — удаляем по составному ключу
      await del(`/shares/mine?entity_type=${s.entity_type}&entity_id=${s.entity_id}`);
      await Promise.all([store.reloadShared(), store.reloadDirections(), store.reloadProjects(), store.reloadTasks()]);
    } catch (e) { store.setError(String(e)); }
  }

  return (
    <div className="page shared-page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2><span className="swatch shared" style={{ width: 14, height: 14 }} />Общие</h2>
        <span className="spacer" />
        <span className="hint">{store.shared.length ? `${store.shared.length} объект${store.shared.length === 1 ? "" : store.shared.length < 5 ? "а" : "ов"} открыто вам` : ""}</span>
      </div>
      {store.shared.length === 0 ? (
        <div className="state" style={{ flex: "none", padding: "60px 20px" }}>
          <h3>Вам пока ничего не открыли</h3>
          <p>Когда коллега поделится направлением, проектом или задачей, они появятся здесь — и в левой панели среди направлений с пометкой ⇄.<br />
            Поделиться своим: правая кнопка на направлении или проекте → «Поделиться…», в задаче — кнопка ⇄ в шапке.</p>
        </div>
      ) : groups.map((g) => (
        <section key={g.who} className="shared-group">
          <h3 className="shared-who"><span className="avatar-sm">{initials(g.who)}</span>{g.who} <span className="hint">открыл{g.items.length === 1 ? "" : "и"} вам</span></h3>
          <div className="table">
            <div className="trow head shared-row"><span>Что</span><span>Тип</span><span className="hide-m">Право</span><span className="hide-m">Открытых задач</span><span /></div>
            {g.items.map((s) => {
              const n = openCount(s);
              return (
                <div key={`${s.entity_type}-${s.entity_id}`} className="trow shared-row">
                  <span><button className="person-link" onClick={() => onOpen(s)}>{s.name}</button><div className="sub">с {showDate(s.created_at)}</div></span>
                  <span className={`tag kind-${s.entity_type}`}>{ENTITY_LABEL[s.entity_type]}</span>
                  <span className={`tag perm-${s.permission} hide-m`}>{PERMISSION_LABEL[s.permission]}</span>
                  <span className="mono hide-m">{n === null ? "—" : n}</span>
                  <span className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn sm" onClick={() => onOpen(s)}>Открыть</button>
                    <button className="btn ghost sm" onClick={() => leave(s)} title="Отказаться от доступа">Отказаться</button>
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
