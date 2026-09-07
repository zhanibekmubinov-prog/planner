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
        <div className="brand"><h1><img className="brand-mark" src="/cis-mark.png" alt="CIS" /><span className="brand-name">Planner</span></h1></div>
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

type TgLink = { ready: boolean; bot: string | null; code: string | null; url: string | null; connected?: boolean; hint?: string };

export function ProfileModal({ store, onClose }: { store: Store; onClose: () => void }) {
  const me = store.me!;
  const [name, setName] = useState(me.name);
  const [chat, setChat] = useState(me.telegram_chat_id ?? "");
  const [digest, setDigest] = useState(me.digest_enabled);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [link, setLink] = useState<TgLink | null>(null);
  const [manual, setManual] = useState(false);
  const [waiting, setWaiting] = useState(false);   // ссылку открыли, ждём нажатия «Запустить» в Telegram

  // chat id мог измениться сам (бот привязал чат) — поле не должно затирать его при сохранении
  useEffect(() => { setChat(me.telegram_chat_id ?? ""); }, [me.telegram_chat_id]);
  useEffect(() => { api<TgLink>("/telegram/link").then(setLink).catch(() => setLink({ ready: false, bot: null, code: null, url: null })); }, []);

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
  function connectTelegram() {
    if (!link?.url) return;
    window.open(link.url, "_blank", "noopener");
    setWaiting(true); setMsg(null);
  }
  /** Перечитываем профиль: если бот уже получил /start, chat id появится сам. */
  async function checkTelegram() {
    setBusy(true); setMsg(null);
    try {
      const fresh = await api<User>("/auth/me");
      store.setMe(fresh);
      if (fresh.telegram_chat_id) { setWaiting(false); setMsg("Telegram подключён"); api<TgLink>("/telegram/link").then(setLink).catch(() => {}); }
      else setMsg("Пока не вижу. Откройте бота и нажмите «Запустить» (кнопка внизу чата), затем «Проверить» ещё раз.");
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }
  async function disconnectTelegram() {
    setBusy(true); setMsg(null);
    try { store.setMe(await put<User>("/auth/me", { name: name.trim() || me.name, telegram_chat_id: null, digest_enabled: digest })); setMsg("Telegram отключён"); }
    catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }
  function logout() { setSession(null); window.location.reload(); }

  const connected = !!me.telegram_chat_id;

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Профиль">
        <h3>Профиль</h3>
        <div className="field"><label>Имя</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label>Почта</label><input className="input" value={me.email} disabled /></div>

        <div className="field">
          <label>Telegram</label>
          {connected ? (
            <div className="row">
              <span className="hint" style={{ color: "var(--ok)" }}>Подключён · chat id <span className="mono">{me.telegram_chat_id}</span></span>
              <button className="btn sm" onClick={() => test("telegram")} disabled={busy} style={{ marginLeft: "auto" }}>Тест</button>
              <button className="btn sm" onClick={disconnectTelegram} disabled={busy}>Отключить</button>
            </div>
          ) : link?.ready ? (
            <>
              <div className="row">
                <button className="btn primary sm" onClick={connectTelegram} disabled={busy}>Подключить Telegram</button>
                {waiting && <button className="btn sm" onClick={checkTelegram} disabled={busy}>Проверить</button>}
              </div>
              <span className="hint">
                Откроется бот <span className="mono">@{link.bot}</span> — нажмите в нём «Запустить», и я сам привяжу чат.
                {waiting ? " Нажали? Тогда нажмите «Проверить»." : ""}
              </span>
            </>
          ) : (
            <span className="hint">{link?.hint ?? "Проверяю настройки бота…"}</span>
          )}
          <div className="row">
            <button className="btn sm ghost" onClick={() => setManual(!manual)}>{manual ? "Скрыть ручной ввод" : "Вписать chat id вручную"}</button>
          </div>
          {manual && (
            <>
              <div className="row">
                <input className="input mono grow" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="напишите боту /id — он пришлёт ваш chat id" />
                <button className="btn sm" onClick={save} disabled={busy}>Сохранить id</button>
              </div>
              <span className="hint">Напишите боту команду <span className="mono">/id</span> — он ответит вашим chat id.</span>
            </>
          )}
          <span className="hint">Сюда придут напоминания, поручения и утренняя сводка.</span>
        </div>

        <div className="row"><button className="btn sm" onClick={() => test("email")} disabled={busy}>Тест письма на {me.email}</button></div>
        <label className="checks" style={{ cursor: "pointer" }}><input type="checkbox" checked={digest} onChange={(e) => setDigest(e.target.checked)} /> Присылать утреннюю сводку</label>
        {msg && <span className="hint" style={{ color: msg.startsWith("Сохранено") || msg.includes("отправлен") || msg.includes("подключён") ? "var(--ok)" : "var(--danger)" }}>{msg}</span>}
        <div className="foot">
          <button className="btn danger" onClick={logout} style={{ marginRight: "auto" }}>Выйти</button>
          <button className="btn" onClick={onClose}>Закрыть</button>
          <button className="btn primary" onClick={save} disabled={busy}>Сохранить</button>
        </div>
      </div>
    </div>
  );
}
