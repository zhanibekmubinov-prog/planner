// Окно «Поделиться»: кому открыт объект (направление / проект / задача), добавить по почте, право смотреть/редактировать, отозвать.
import { useEffect, useMemo, useState } from "react";
import { api, del, ENTITY_LABEL, Permission, PERMISSION_LABEL, post, put, Share, ShareEntity, UserBrief } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

export type ShareTarget = { type: ShareEntity; id: number; name: string; color?: string };

const INHERIT: Record<ShareEntity, string> = {
  direction: "Доступ распространяется на все проекты и задачи направления — включая те, что появятся позже.",
  project: "Доступ распространяется на все задачи проекта. Направление коллега увидит только как обложку — без остальных проектов.",
  task: "Открывается только эта задача. Направление и проект коллега увидит как обложку.",
};

export default function ShareModal({ store, target, onClose }: { store: Store; target: ShareTarget; onClose: () => void }) {
  const [items, setItems] = useState<Share[] | null>(null);
  const [people, setPeople] = useState<UserBrief[]>([]);
  const [email, setEmail] = useState("");
  const [perm, setPerm] = useState<Permission>("view");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const confirm = useConfirm();

  const load = async () => {
    try {
      const [s, p] = await Promise.all([api<Share[]>(`/shares?entity_type=${target.type}&entity_id=${target.id}`), api<UserBrief[]>("/shares/people")]);
      setItems(s); setPeople(p);
    } catch (e) { store.setError(String(e)); }
  };
  useEffect(() => { void load(); }, [target.type, target.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = email.trim().toLowerCase();
  const suggestions = useMemo(() => {
    const taken = new Set((items ?? []).map((s) => s.user.email));
    return people.filter((p) => !taken.has(p.email) && (!q || p.email.includes(q) || p.name.toLowerCase().includes(q))).slice(0, 6);
  }, [people, items, q]);

  async function add(target_email = email) {
    const v = target_email.trim().toLowerCase();
    if (!v) return;
    setBusy(true); setErr(null);
    try {
      await post<Share>("/shares", { entity_type: target.type, entity_id: target.id, email: v, permission: perm });
      setEmail(""); await load(); await store.reloadShared();
    } catch (e) {
      const m = String(e); setErr(m.replace(/^\d+\s*/, "").replace(/^\{"detail":"(.*)"\}$/, "$1"));
    } finally { setBusy(false); }
  }
  async function setPermission(s: Share, permission: Permission) {
    try { await put<Share>(`/shares/${s.id}`, { permission }); await load(); } catch (e) { store.setError(String(e)); }
  }
  async function revoke(s: Share) {
    if (!(await confirm(`Закрыть доступ для ${s.user.name}?`, { danger: true, okLabel: "Закрыть доступ" }))) return;
    try { await del(`/shares/${s.id}`); await load(); } catch (e) { store.setError(String(e)); }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Поделиться" style={{ borderTop: `4px solid ${target.color || "var(--accent)"}` }}>
        <div className="share-head">
          <span className="share-kind">{ENTITY_LABEL[target.type]}</span>
          <h3>{target.name}</h3>
        </div>
        <p className="hint">{INHERIT[target.type]}</p>

        <div className="share-add">
          <div className="row">
            <input className="input grow" type="email" placeholder="почта коллеги, например n.abilkhanov@cis.kz" value={email} autoFocus list="share-people"
              onChange={(e) => { setEmail(e.target.value); setErr(null); }} onKeyDown={(e) => { if (e.key === "Enter") void add(); }} />
            <div className="seg" role="radiogroup" aria-label="Право">
              {(["view", "edit"] as Permission[]).map((p) => (
                <button key={p} type="button" role="radio" aria-checked={perm === p} className={perm === p ? "on" : ""} onClick={() => setPerm(p)}>{PERMISSION_LABEL[p]}</button>
              ))}
            </div>
            <button className="btn primary" onClick={() => add()} disabled={busy || !q}>Открыть доступ</button>
          </div>
          {err && <p className="share-err">{err}</p>}
          {q && suggestions.length > 0 && (
            <div className="share-suggest">
              {suggestions.map((p) => (
                <button key={p.id} type="button" className="chip pick" onClick={() => add(p.email)}>{p.name} <span className="mono">{p.email}</span></button>
              ))}
            </div>
          )}
          <span className="hint">Можно пригласить того, кто ещё ни разу не входил: при первом входе через Microsoft всё уже будет открыто. «Редактировать» — менять и добавлять задачи; удалять и делиться дальше может только владелец.</span>
        </div>

        <div className="section">
          <div className="section-head">Кому открыто <span className="n">{items?.length ?? 0}</span></div>
          {items === null ? <span className="hint">Загрузка…</span> : items.length === 0 ? (
            <span className="hint">Пока никому. Введите почту выше.</span>
          ) : (
            <div className="list">
              {items.map((s) => (
                <div key={s.id} className="item share-row">
                  <span className="primary">{s.user.name} <span className="mono share-mail">{s.user.email}</span></span>
                  <span className="actions">
                    <div className="seg sm" role="radiogroup" aria-label={`Право для ${s.user.name}`}>
                      {(["view", "edit"] as Permission[]).map((p) => (
                        <button key={p} type="button" role="radio" aria-checked={s.permission === p} className={s.permission === p ? "on" : ""} onClick={() => setPermission(s, p)}>{PERMISSION_LABEL[p]}</button>
                      ))}
                    </div>
                    <button className="btn danger sm" onClick={() => revoke(s)} aria-label="Закрыть доступ" title="Закрыть доступ">×</button>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="foot"><button className="btn" onClick={onClose}>Готово</button></div>
      </div>
    </div>
  );
}
