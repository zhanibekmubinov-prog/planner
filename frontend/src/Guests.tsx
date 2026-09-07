// Гости — внешние участники (v0.10). Раздел видит и меняет только администратор.
// Запись в списке = разрешение входить по одноразовой ссылке на почту. Удалили — доступ закрыт сразу.
import { useEffect, useState } from "react";
import { api, del, errorText, Guest, GuestIn, post, put, showDateTime } from "./api";
import { useConfirm } from "./confirm";
import { Store } from "./store";

export default function GuestsPage({ store }: { store: Store }) {
  const [rows, setRows] = useState<Guest[] | null>(null);
  const [editing, setEditing] = useState<Guest | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const confirm = useConfirm();

  async function reload() {
    try { setRows(await api<Guest[]>("/guests")); } catch (e) { store.setError(errorText(e)); setRows([]); }
  }
  useEffect(() => { reload(); }, []);

  async function save(form: GuestIn, id?: number) {
    setBusy(true);
    try {
      if (id) await put(`/guests/${id}`, form); else await post("/guests", form);
      setEditing(null); await reload();
    } catch (e) { store.setError(errorText(e)); } finally { setBusy(false); }
  }
  async function resetPassword(g: Guest) {
    if (!(await confirm(`Выслать ${g.name} ссылку для нового пароля?`,
      { details: "Ссылка придёт на его почту, действует 15 минут. Старый пароль работает, пока гость не задаст новый." }))) return;
    setBusy(true);
    try {
      const r = await post<{ message: string }>(`/guests/${g.id}/reset-link`, {});
      store.setError(null); setNote(r.message);
    } catch (e) { store.setError(errorText(e)); } finally { setBusy(false); }
  }
  async function remove(g: Guest) {
    const okDelete = await confirm(
      `Закрыть доступ для ${g.name} (${g.email})?`,
      { danger: true, details: "Гость больше не сможет войти, и его открытые сессии перестанут работать сразу. Задачи и записи, которые он успел создать, останутся." },
    );
    if (!okDelete) return;
    setBusy(true);
    try { await del(`/guests/${g.id}`); await reload(); } catch (e) { store.setError(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <div className="page">
      <div className="topbar" style={{ padding: 0 }}>
        <h2>Гости</h2><span className="spacer" />
        <button className="btn primary" onClick={() => setEditing("new")} disabled={busy}>+ Гость</button>
      </div>
      <p className="hint">
        Внешние участники — подрядчики и партнёры с почтой не нашего домена. Microsoft им не нужен: по вашему
        приглашению гость получает на почту ссылку, задаёт себе пароль и дальше входит почтой и паролем.
        Приглашать, сбрасывать пароль и отключать гостей может только администратор. Права внутри планнера
        у гостя такие же, как у сотрудника, поэтому открывайте ему только нужные направления и проекты.
      </p>
      {note && <p className="hint" style={{ color: "var(--ok)" }}>{note}</p>}
      {editing === "new" && <GuestForm busy={busy} onCancel={() => setEditing(null)} onSave={(f) => save(f)} />}
      {rows === null ? (
        <span className="hint">загружаю…</span>
      ) : rows.length === 0 && editing !== "new" ? (
        <div className="state"><h3>Гостей нет</h3><p>Пока в планнер входят только сотрудники с рабочей почтой.</p></div>
      ) : (
        <div className="table">
          <div className="trow head guest-row"><span>Имя</span><span className="hide-m">Почта</span><span className="hide-m">Пароль</span><span className="hide-m">Последний вход</span><span /></div>
          {rows.map((g) => editing !== "new" && editing?.id === g.id ? (
            <div key={g.id} className="trow editing"><GuestForm guest={g} busy={busy} onCancel={() => setEditing(null)} onSave={(f) => save(f, g.id)} /></div>
          ) : (
            <div key={g.id} className="trow guest-row">
              <span>
                {g.name}
                <span className="tag">гость</span>
                {g.note && <div className="sub">{g.note}</div>}
              </span>
              <span className="hide-m mono">{g.email}</span>
              <span className="hide-m">{g.has_password
                ? <span style={{ color: "var(--ok)" }}>задан</span>
                : <span className="hint">не задан</span>}</span>
              <span className="hide-m">{g.last_login_at ? showDateTime(g.last_login_at) : <span className="hint">ещё не входил</span>}</span>
              <span className="row">
                <button className="btn sm" onClick={() => setEditing(g)} disabled={busy}>Изменить</button>
                <button className="btn sm" onClick={() => resetPassword(g)} disabled={busy} title="Выслать ссылку для нового пароля">Сбросить пароль</button>
                <button className="btn sm danger" onClick={() => remove(g)} disabled={busy}>Закрыть доступ</button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function GuestForm({ guest, busy, onCancel, onSave }: { guest?: Guest; busy: boolean; onCancel: () => void; onSave: (f: GuestIn) => void }) {
  const [email, setEmail] = useState(guest?.email ?? "");
  const [name, setName] = useState(guest?.name ?? "");
  const [note, setNote] = useState(guest?.note ?? "");
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) && name.trim().length > 0;

  return (
    <div className="inline-form">
      <div className="grid2">
        <div className="field">
          <label>Почта</label>
          <input className="input mono" value={email} onChange={(e) => setEmail(e.target.value)} disabled={!!guest}
                 placeholder="partner@podryadchik.kz" autoFocus={!guest} />
        </div>
        <div className="field"><label>Имя</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя и фамилия" autoFocus={!!guest} /></div>
        <div className="field"><label>Пометка</label><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="кто это и по какому вопросу" /></div>
      </div>
      <span className="hint">{guest ? "Почту менять нельзя: закройте доступ и добавьте заново." : "На эту почту гость запросит ссылку, чтобы задать пароль. Письмо он отправляет себе сам с экрана входа."}</span>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn sm" onClick={onCancel} disabled={busy}>Отмена</button>
        <button className="btn primary sm" onClick={() => onSave({ email: email.trim().toLowerCase(), name: name.trim(), note: note.trim() || null })} disabled={busy || !valid}>
          {guest ? "Сохранить" : "Пригласить"}
        </button>
      </div>
    </div>
  );
}
