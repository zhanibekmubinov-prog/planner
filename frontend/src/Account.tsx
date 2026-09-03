// Вход через Microsoft, чип пользователя в панели и окно профиля.
import { useEffect, useState } from "react";
import { api, API_BASE, getSession, post, put, setSession, User } from "./api";
import { Store } from "./store";

/** Забирает #token=… после возврата от Microsoft. Возвращает true, если сессия есть. */
export function pickUpSession(): boolean {
  const m = window.location.hash.match(/token=([^&]+)/);
  if (m) { setSession(decodeURIComponent(m[1])); window.history.replaceState(null, "", window.location.pathname + window.location.search); }
  return !!getSession() || !!import.meta.env.VITE_API_TOKEN;
}

export function LoginScreen({ error }: { error?: string | null }) {
  const [cfg, setCfg] = useState<{ microsoft: boolean } | null>(null);
  useEffect(() => { api<{ microsoft: boolean }>("/auth/config").then(setCfg).catch(() => setCfg({ microsoft: false })); }, []);
  return (
    <div className="login">
      <div className="login-card">
        <div className="brand"><h1>CIS Planner</h1></div>
        <p className="login-lead">Направления, задачи, поручения и майндмапы — в одном месте. Войдите рабочей учётной записью.</p>
        {cfg === null ? <span className="hint">проверяю настройки…</span> : cfg.microsoft ? (
          <a className="btn primary login-ms" href={`${API_BASE}/api/auth/login`}>
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1" y="1" width="6.5" height="6.5" fill="#f25022"/><rect x="8.5" y="1" width="6.5" height="6.5" fill="#7fba00"/><rect x="1" y="8.5" width="6.5" height="6.5" fill="#00a4ef"/><rect x="8.5" y="8.5" width="6.5" height="6.5" fill="#ffb900"/></svg>
            Войти через Microsoft
          </a>
        ) : (
          <p className="hint">Вход через Microsoft не настроен на сервере (переменные MS_REDIRECT_URI и др.).</p>
        )}
        {error && <p className="login-error">{error}</p>}
        <p className="hint login-foot">Caspian Integrated Services · доступ по учётным записям компании</p>
      </div>
    </div>
  );
}

export function UserChip({ me, onClick }: { me: User; onClick: () => void }) {
  const initials = me.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <button className="user-chip" onClick={onClick} title="Профиль и выход">
      <span className="avatar">{initials}</span>
      <span className="user-name">{me.name}</span>
    </button>
  );
}

export function ProfileModal({ store, onClose }: { store: Store; onClose: () => void }) {
  const me = store.me!;
  const [name, setName] = useState(me.name);
  const [chat, setChat] = useState(me.telegram_chat_id ?? "");
  const [digest, setDigest] = useState(me.digest_enabled);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function save() {
    setBusy(true); setMsg(null);
    try { store.setMe(await put<User>("/auth/me", { name: name.trim() || me.name, telegram_chat_id: chat.trim() || null, digest_enabled: digest })); setMsg("Сохранено"); }
    catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }
  async function test(channel: string) {
    setBusy(true); setMsg(null);
    try { await post("/notify/test", { channel }); setMsg(channel === "telegram" ? "Сообщение отправлено в Telegram" : "Письмо отправлено"); }
    catch (e) { setMsg(String(e).replace(/^\d+ /, "")); } finally { setBusy(false); }
  }
  function logout() { setSession(null); window.location.reload(); }

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Профиль">
        <h3>Профиль</h3>
        <div className="field"><label>Имя</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label>Почта</label><input className="input" value={me.email} disabled /></div>
        <div className="field">
          <label>Telegram chat id</label>
          <div className="row"><input className="input mono grow" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="напишите боту /start, id узнайте у @userinfobot" />
            <button className="btn sm" onClick={() => test("telegram")} disabled={busy || !me.telegram_chat_id}>Тест</button></div>
          <span className="hint">Сюда придут напоминания, поручения и утренняя сводка.</span>
        </div>
        <div className="row"><button className="btn sm" onClick={() => test("email")} disabled={busy}>Тест письма на {me.email}</button></div>
        <label className="checks" style={{ cursor: "pointer" }}><input type="checkbox" checked={digest} onChange={(e) => setDigest(e.target.checked)} /> Присылать утреннюю сводку</label>
        {msg && <span className="hint" style={{ color: msg.startsWith("Сохранено") || msg.includes("отправлен") ? "var(--ok)" : "var(--danger)" }}>{msg}</span>}
        <div className="foot">
          <button className="btn danger" onClick={logout} style={{ marginRight: "auto" }}>Выйти</button>
          <button className="btn" onClick={onClose}>Закрыть</button>
          <button className="btn primary" onClick={save} disabled={busy}>Сохранить</button>
        </div>
      </div>
    </div>
  );
}
