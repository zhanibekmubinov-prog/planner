import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .auth import require_token
from .config import settings
from .routers import directions, mindmaps, notify, simple, tasks, tools
from .scheduler import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(run_forever(stop)) if settings.scheduler_enabled else None
    yield
    stop.set()
    if task:
        await task


app = FastAPI(title="Planner API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}


for r in (directions.router, tasks.router, tools.router, simple.people, simple.delegations, simple.reminders, notify.router, mindmaps.router):
    app.include_router(r, prefix="/api", dependencies=[Depends(require_token)])
