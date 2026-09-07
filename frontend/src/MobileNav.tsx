// Мобильная навигация (v0.11): нижняя панель вкладок — Карта, Задачи, Поручено, Ещё.
// «Ещё» открывает шторку с той же левой панелью, что на компьютере (разделы, направления, проекты, меню «⋯»),
// поэтому с телефона доступно всё, а код панели один.
import { useEffect, useState } from "react";
import Sidebar, { SidebarProps, View } from "./Sidebar";
import { useEscape } from "./layers";

type Props = SidebarProps;

const isOverview = (v: View) => v.kind === "overview";
const isAllTasks = (v: View) => v.kind === "board" && v.directionId === null && !v.orphans;
const isInbox = (v: View) => v.kind === "inbox";

export default function MobileNav(props: Props) {
  const { view, inboxCount, onView } = props;
  const [more, setMore] = useState(false);
  const close = () => setMore(false);
  useEscape(close, more);
  // Любой переход из шторки закрывает её; смена раздела снаружи — тоже
  useEffect(() => { setMore(false); }, [view]);
  // Пока открыта шторка, страница под ней не прокручивается
  useEffect(() => {
    if (!more) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [more]);

  const go = (v: View) => { setMore(false); onView(v); };
  const inMore = more || !(isOverview(view) || isAllTasks(view) || isInbox(view));

  return (
    <>
      {more && (
        <div className="sheet-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Разделы и направления">
            <div className="sheet-grip" aria-hidden="true" />
            <Sidebar {...props} onView={go} onNewDirection={() => { close(); props.onNewDirection(); }} onNewProject={(d) => { close(); props.onNewProject(d); }}
              onProfile={() => { close(); props.onProfile(); }} />
            <button className="sheet-close btn" onClick={close}>Закрыть</button>
          </div>
        </div>
      )}

      <nav className="tabbar" aria-label="Основные разделы">
        <button className={`tabbar-item ${isOverview(view) && !more ? "on" : ""}`} onClick={() => go({ kind: "overview" })}>
          <MapIcon /><span>Карта</span>
        </button>
        <button className={`tabbar-item ${isAllTasks(view) && !more ? "on" : ""}`} onClick={() => go({ kind: "board", directionId: null })}>
          <TasksIcon /><span>Задачи</span>
        </button>
        <button className={`tabbar-item ${isInbox(view) && !more ? "on" : ""}`} onClick={() => go({ kind: "inbox" })}>
          <InboxIcon />{inboxCount > 0 && <span className="tabbar-badge mono">{inboxCount}</span>}<span>Поручено</span>
        </button>
        <button className={`tabbar-item ${inMore ? "on" : ""}`} onClick={() => setMore((v) => !v)} aria-expanded={more}>
          <MoreIcon /><span>Ещё</span>
        </button>
      </nav>
    </>
  );
}

/* Иконки — штриховые, 22px, под цвет текста; без библиотек. */
const I = ({ children }: { children: React.ReactNode }) => (
  <svg className="tabbar-ico" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const MapIcon = () => <I><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="13" y="3" width="8" height="8" rx="1.5" /><rect x="3" y="13" width="8" height="8" rx="1.5" /><rect x="13" y="13" width="8" height="8" rx="1.5" /></I>;
const TasksIcon = () => <I><path d="M4 7h16M4 12h16M4 17h10" /><circle cx="19" cy="17" r="1.6" fill="currentColor" stroke="none" /></I>;
const InboxIcon = () => <I><path d="M4 4h16v16H4z" /><path d="M4 14h5l1.5 2.5h3L15 14h5" /></I>;
const MoreIcon = () => <I><circle cx="6" cy="12" r="1.7" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" /><circle cx="18" cy="12" r="1.7" fill="currentColor" stroke="none" /></I>;
