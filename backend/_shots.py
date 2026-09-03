import asyncio, sys, re
from playwright.async_api import async_playwright
JACK, NUR = [l.split(" ", 1)[1].strip() for l in open("/tmp/ui.log") if l.startswith(("JACK", "NUR"))]
OUT = "/root/work/shots"
import os; os.makedirs(OUT, exist_ok=True)

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        async def page_as(token, w=1440, h=900):
            ctx = await b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            await ctx.add_init_script(f"localStorage.setItem('planner.session', '{token}')")
            p = await ctx.new_page(); p.on("pageerror", lambda e: print("PAGEERROR", e)); p.on("console", lambda m: print("CONSOLE", m.type, m.text) if m.type == "error" else None)
            await p.goto("http://localhost:8000/"); await p.wait_for_selector(".side-dirs .side-item.dir"); return p
        p = await page_as(JACK)
        # 1. Карта направлений (стартовая) + сайдбар
        await p.wait_for_timeout(400); await p.screenshot(path=f"{OUT}/01_overview.png")
        # раскрыть проекты Эмбы
        await p.click(".side-item.dir:has-text('Эмба') .chev-btn"); await p.wait_for_timeout(200)
        # 2. Страница направления — карта проектов
        await p.click(".side-item.dir:has-text('Эмба') .name"); await p.wait_for_selector(".dir-page"); await p.wait_for_timeout(300)
        await p.screenshot(path=f"{OUT}/02_direction_projects.png")
        # 3. Доска проекта с вкладками
        await p.click(".side-item.proj:has-text('Договор основной') .name"); await p.wait_for_selector(".board"); await p.wait_for_timeout(300)
        await p.screenshot(path=f"{OUT}/03_project_board_tabs.png")
        await p.screenshot(path=f"{OUT}/03b_tabs_crop.png", clip={"x": 236, "y": 0, "width": 1204, "height": 150})
        # 4. Контекстное меню проекта
        await p.click(".side-item.proj:has-text('Договор мини') .name", button="right"); await p.wait_for_selector(".ctx-menu"); await p.wait_for_timeout(150)
        await p.screenshot(path=f"{OUT}/04_project_menu.png"); await p.keyboard.press("Escape")
        # 5. Карточка задачи с проектом
        await p.click(".card:has-text('Сделать ГРП')"); await p.wait_for_selector(".task-modal"); await p.wait_for_timeout(300)
        await p.screenshot(path=f"{OUT}/05_task_modal.png")
        # 6. Поделиться задачей
        await p.click(".task-modal .tm-head button:has-text('Поделиться')"); await p.wait_for_selector(".share-modal"); await p.wait_for_timeout(200)
        await p.fill(".share-modal input[type=email]", "n.ab"); await p.wait_for_timeout(200)
        await p.screenshot(path=f"{OUT}/06_share_modal.png"); await p.keyboard.press("Escape"); await p.wait_for_timeout(150); await p.keyboard.press("Escape")
        # 7. Поделиться направлением через меню
        await p.click(".side-item.dir:has-text('Эмба') .name", button="right"); await p.wait_for_selector(".ctx-menu"); await p.wait_for_timeout(120)
        await p.screenshot(path=f"{OUT}/07_direction_menu.png")
        await p.click(".ctx-menu button:has-text('Поделиться')"); await p.wait_for_selector(".share-modal"); await p.wait_for_timeout(200)
        await p.screenshot(path=f"{OUT}/08_share_direction.png"); await p.keyboard.press("Escape")
        # 8. Общие (у Джека — направление Нурлана)
        await p.click(".side-top .side-item:has-text('Общие')"); await p.wait_for_selector(".shared-page"); await p.wait_for_timeout(300)
        await p.screenshot(path=f"{OUT}/09_shared_page.png")
        # 9. Открыть общее направление (view)
        await p.click(".shared-page .person-link"); await p.wait_for_selector(".dir-page"); await p.wait_for_timeout(300)
        await p.screenshot(path=f"{OUT}/10_shared_direction_view.png")
        # Новый проект
        await p.click(".side-item.dir:has-text('Закуп') .chev-btn"); await p.wait_for_timeout(150)
        await p.click(".side-item.add-proj"); await p.wait_for_selector(".modal"); await p.wait_for_timeout(200)
        await p.screenshot(path=f"{OUT}/11_new_project_modal.png"); await p.keyboard.press("Escape")
        # Нурлан: доска общего проекта edit + КК view
        n = await page_as(NUR)
        await n.click(".side-top .side-item:has-text('Общие')"); await n.wait_for_selector(".shared-page"); await n.wait_for_timeout(300)
        await n.screenshot(path=f"{OUT}/12_nur_shared.png")
        await n.click(".side-item.dir:has-text('Эмба') .chev-btn"); await n.wait_for_timeout(150)
        await n.click(".side-item.proj:has-text('Договор основной') .name"); await n.wait_for_selector(".board"); await n.wait_for_timeout(300)
        await n.screenshot(path=f"{OUT}/13_nur_shared_project_edit.png")
        await n.click(".side-item.dir:has-text('КК') .name"); await n.wait_for_selector(".dir-page"); await n.wait_for_timeout(200)
        await n.click(".dir-actions button:has-text('Все задачи')"); await n.wait_for_selector(".board"); await n.wait_for_timeout(200)
        await n.click(".card:has-text('наставничества')"); await n.wait_for_selector(".task-modal"); await n.wait_for_timeout(300)
        await n.screenshot(path=f"{OUT}/14_nur_task_view_only.png")
        # ноутбук 1366 и телефон
        s = await page_as(JACK, 1366, 768); await s.click(".side-item.dir:has-text('Эмба') .chev-btn"); await s.click(".side-item.proj:has-text('Договор основной') .name"); await s.wait_for_selector(".board"); await s.wait_for_timeout(300)
        await s.screenshot(path=f"{OUT}/15_laptop_1366.png")
        m = await page_as(JACK, 390, 844); await m.wait_for_timeout(300); await m.screenshot(path=f"{OUT}/16_mobile.png")
        await b.close()
asyncio.run(main())
print("shots done")
