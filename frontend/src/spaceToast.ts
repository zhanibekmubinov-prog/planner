// v1.7: тост «Направление … перешло в Организацию · Отменить».
//
// Автоправило переводит направление в рабочий слой при первом доступе или первом поручении.
// Это должно быть заметно и обратимо: «Отменить» возвращает направление в «Личное» и
// пришпиливает слой — больше оно само переезжать не будет.
import { Direction, put } from "./api";
import type { Store } from "./store";

type Show = (text: string, options?: { action?: string; onAction?: () => void | Promise<void>; ms?: number }) => void;

export function notifySpaceMoved(moved: string[] | undefined, store: Store, toast: Show): void {
  if (!moved || !moved.length) return;
  const names = moved.map((n) => `«${n}»`).join(", ");
  const word = moved.length === 1 ? "перешло" : "перешли";
  toast(`${moved.length === 1 ? "Направление" : "Направления"} ${names} ${word} в «Организацию»`, {
    action: "Отменить",
    onAction: async () => {
      const ids = store.directions.filter((d) => moved.includes(d.name)).map((d) => d.id);
      for (const id of ids) await put<Direction>(`/directions/${id}/space`, { space: "personal", revoke_shares: false });
      await store.reloadDirections();
    },
  });
}
