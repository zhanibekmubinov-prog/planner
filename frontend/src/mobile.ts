// Мобильный режим (v0.11): один и тот же фронт, на узком экране меняется раскладка.
// Порог совпадает с медиазапросом в styles.css — менять синхронно.
import { useEffect, useState } from "react";

export const MOBILE_QUERY = "(max-width: 900px)";

function matches(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;   // тесты в jsdom
  return window.matchMedia(MOBILE_QUERY).matches;
}

/** true — телефон/узкий экран: нижняя панель вкладок, доска в одну колонку, карточка задачи на весь экран. */
export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState<boolean>(matches);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(MOBILE_QUERY);
    const onChange = () => setMobile(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return mobile;
}
