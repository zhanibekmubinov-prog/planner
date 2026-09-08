// «Потянуть сверху вниз — обновить» (v1.1). В PWA с экрана «Домой» браузерного жеста нет, а в самом
// приложении он и так отключён (`overscroll-behavior: none` в styles.css), поэтому жест свой.
// Хук вешается на прокручиваемый контейнер (на телефоне это `.main`): срабатывает только когда список
// прокручен в самый верх и палец идёт вниз. Никакого preventDefault — слушатели пассивные, прокрутка не тормозится.
import { useEffect, useRef, useState } from "react";

export type PullPhase = "idle" | "pulling" | "armed" | "refreshing" | "done";
export type PullState = { phase: PullPhase; distance: number };

export const PULL_THRESHOLD = 64;   // px индикатора, после которых отпускание запускает обновление
const PULL_MAX = 96;                // дальше палец тянет «в пустоту»
const DONE_MS = 420;                // сколько держать галочку после успеха

/** Сопротивление: первые сантиметры идут почти 1:1, дальше всё туже. */
function damp(dy: number): number {
  const d = dy * 0.55;
  return Math.min(PULL_MAX, d > PULL_THRESHOLD ? PULL_THRESHOLD + (d - PULL_THRESHOLD) * 0.4 : d);
}

/**
 * @param ref       контейнер с прокруткой (overflow-y: auto)
 * @param onRefresh что делать при отпускании — ждём промис, пока он идёт крутится спиннер
 * @param enabled   только на телефоне; false — слушатели не вешаются
 */
export function usePullToRefresh(ref: React.RefObject<HTMLElement>, onRefresh: () => Promise<unknown>, enabled: boolean): PullState {
  const [state, setState] = useState<PullState>({ phase: "idle", distance: 0 });
  const startY = useRef<number | null>(null);
  const busy = useRef(false);
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;

  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    let pulling = false;
    let distance = 0;

    const onStart = (e: TouchEvent) => {
      if (busy.current || e.touches.length !== 1 || el.scrollTop > 0) { startY.current = null; return; }
      startY.current = e.touches[0].clientY;
      pulling = false; distance = 0;
    };
    const onMove = (e: TouchEvent) => {
      if (startY.current === null || busy.current) return;
      const dy = e.touches[0].clientY - startY.current;
      if (!pulling) {
        // Начали тянуть, только если список всё ещё вверху и палец пошёл вниз хотя бы на 6px (не путать с тапом)
        if (dy < 6 || el.scrollTop > 0) { if (dy < 0 || el.scrollTop > 0) startY.current = null; return; }
        pulling = true;
      }
      distance = damp(Math.max(0, dy));
      setState({ phase: distance >= PULL_THRESHOLD ? "armed" : "pulling", distance });
    };
    const finish = () => {
      if (startY.current === null) return;
      startY.current = null;
      if (!pulling) return;
      pulling = false;
      if (distance < PULL_THRESHOLD) { setState({ phase: "idle", distance: 0 }); return; }
      busy.current = true;
      setState({ phase: "refreshing", distance: PULL_THRESHOLD });
      void Promise.resolve()
        .then(() => refreshRef.current())
        .then(() => { setState({ phase: "done", distance: PULL_THRESHOLD }); return new Promise((r) => setTimeout(r, DONE_MS)); },
              () => undefined)   // ошибку показывает плашка store.error — здесь просто убираем индикатор
        .then(() => { busy.current = false; setState({ phase: "idle", distance: 0 }); });
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: true });
    el.addEventListener("touchend", finish);
    el.addEventListener("touchcancel", finish);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", finish);
      el.removeEventListener("touchcancel", finish);
    };
  }, [ref, enabled]);

  return state;
}

/**
 * Индикатор в духе Huly/Linear: тонкое кольцо цвета акцента выезжает из-под верхнего края и дорисовывается
 * по мере натяжения; при отпускании крутится, после успеха на миг становится галочкой. Без подписей.
 */
export function PullIndicator({ state }: { state: PullState }) {
  const { phase, distance } = state;
  if (phase === "idle") return null;
  const progress = Math.min(1, distance / PULL_THRESHOLD);      // 0..1 — сколько кольца дорисовано
  const label = phase === "refreshing" ? "Обновляю…" : phase === "done" ? "Обновлено" : phase === "armed" ? "Отпустите, чтобы обновить" : "Потяните, чтобы обновить";
  const r = 9, c = 2 * Math.PI * r;
  return (
    <div className={`ptr ptr-${phase}`} role="status" aria-live="polite" aria-label={label}
         style={{ "--ptr-y": `${distance}px`, "--ptr-p": progress } as React.CSSProperties}>
      <div className="ptr-disc">
        <svg className="ptr-ring" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <circle className="ptr-track" cx="12" cy="12" r={r} />
          <circle className="ptr-arc" cx="12" cy="12" r={r} strokeDasharray={c} strokeDashoffset={phase === "refreshing" ? c * 0.3 : phase === "done" ? 0 : c * (1 - progress * 0.85)} />
          {phase === "done" && <path className="ptr-check" d="M7.5 12.5l3 3 6-6.5" />}
        </svg>
      </div>
    </div>
  );
}
