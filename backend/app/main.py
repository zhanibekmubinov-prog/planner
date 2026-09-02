from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .auth import require_token
from .config import settings
from .routers import directions, simple, tasks, tools

app = FastAPI(title="Planner API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])

@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}

for r in (directions.router, tasks.router, tools.router, simple.people, simple.delegations, simple.reminders):
    app.include_router(r, prefix="/api", dependencies=[Depends(require_token)])
