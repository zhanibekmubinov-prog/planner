// Планнер умеет жить вкладкой внутри платформы CIS (v1.5): платформа держит его в рамке
// и сама отдаёт вход одноразовым билетом (см. backend GET /api/auth/platform).
// Признак «мы в рамке» нужен интерфейсу: свой логотип не рисуем (шапка платформы уже сверху),
// а на экране входа не предлагаем кнопку Microsoft — её форма в рамке не открывается
// (login.microsoftonline.com отдаёт X-Frame-Options: DENY).

/** Мы внутри чужой рамки или пришли по ссылке из платформы (?embed=1). */
export function isEmbedded(): boolean {
  try {
    if (window.self !== window.top) return true;
  } catch {
    return true; // доступ к window.top закрыт политикой — значит, рамка чужого происхождения
  }
  try {
    return new URLSearchParams(window.location.search).get("embed") === "1";
  } catch {
    return false;
  }
}

/** Ставит признак на <html>, чтобы правила в styles.css могли на него опереться. */
export function applyEmbedFlag(): void {
  if (isEmbedded()) document.documentElement.dataset.embed = "1";
}
