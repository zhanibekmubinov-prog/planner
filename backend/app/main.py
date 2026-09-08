import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .auth import require_token
from .config import settings
from .routers import auth as auth_router, directions, guests, mcp, mcp_oauth, mindmaps, notify, projects, shares, simple, tasks, telegram, tools
from .scheduler import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx на INFO печатает полный URL запроса — для Telegram это /bot<TOKEN>/sendMessage; в логах Railway токену не место
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(run_forever(stop)) if settings.scheduler_enabled else None
    menu = asyncio.create_task(telegram.sync_commands())   # меню команд у бота: ставится само при старте
    yield
    menu.cancel()
    stop.set()
    if task:
        await task


app = FastAPI(title="CIS Planner API", version="1.4.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}


# Роутеры сами требуют current_user; общий Depends оставлен для Swagger-кнопки Authorize
for r in (directions.router, projects.router, shares.router, tasks.router, tools.router, simple.people, simple.delegations, simple.reminders, notify.router, mindmaps.router, guests.router):
    app.include_router(r, prefix="/api", dependencies=[Depends(require_token)])
app.include_router(auth_router.router, prefix="/api")  # /auth/login и /auth/callback — без токена
app.include_router(telegram.router, prefix="/api")     # вебхук бота (своя проверка секрета) и /telegram/link
# MCP-коннектор для Claude: OAuth (/oauth/*, /.well-known/*) и сам эндпоинт /mcp — со своей проверкой Bearer-токена
app.include_router(mcp_oauth.router)
app.include_router(mcp.router)
