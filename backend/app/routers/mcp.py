"""MCP-эндпоинт (Streamable HTTP, stateless JSON-ответы) для Claude.

POST /mcp с Bearer-токеном (выдан /oauth/token или служебный API_TOKEN = владелец).
Поддерживаются методы initialize, ping, tools/list, tools/call; уведомления без id подтверждаются 202.
"""
import json
import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import mcp_tools, models
from ..db import get_db
from .mcp_oauth import bearer_user, issuer

log = logging.getLogger("mcp")
router = APIRouter(tags=["mcp"])
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_VERSION = "1.0.0"


def _unauthorized(request: Request) -> JSONResponse:
    return JSONResponse({"error": "invalid_token"}, status_code=401, headers={
        "WWW-Authenticate": f'Bearer realm="mcp", resource_metadata="{issuer(request)}/.well-known/oauth-protected-resource/mcp"'})


def _result(req_id, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}, status_code=status)


def _handle(msg: dict, user: models.User, db: Session):
    method, req_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if req_id is None:  # уведомление (notifications/initialized и т.п.)
        return Response(status_code=202)
    if method == "initialize":
        client_ver = params.get("protocolVersion")
        return _result(req_id, {
            "protocolVersion": client_ver if client_ver in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "CIS Planner", "version": SERVER_VERSION},
            "instructions": mcp_tools.instructions_for(user),
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": mcp_tools.tools_for(user)})
    if method == "tools/call":
        name = params.get("name") or ""
        text, is_error = mcp_tools.call_tool(db, user, name, params.get("arguments"))
        log.info("mcp tools/call %s by %s -> %s", name, user.email, "error" if is_error else "ok")
        return _result(req_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
    if method in ("resources/list", "prompts/list"):
        return _result(req_id, {"resources": []} if method == "resources/list" else {"prompts": []})
    return _error(req_id, -32601, f"метод не поддерживается: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request, db: Session = Depends(get_db)):
    user = bearer_user(request, db)
    if user is None:
        return _unauthorized(request)
    try:
        msg = json.loads(await request.body())
    except ValueError:
        return _error(None, -32700, "ошибка разбора JSON", status=400)
    if isinstance(msg, list):  # batch
        out = [r for r in (_handle(m, user, db) for m in msg if isinstance(m, dict)) if isinstance(r, JSONResponse)]
        return JSONResponse([json.loads(r.body) for r in out]) if out else Response(status_code=202)
    if not isinstance(msg, dict):
        return _error(None, -32600, "ожидается JSON-RPC объект", status=400)
    return _handle(msg, user, db)


@router.get("/mcp")
def mcp_get():
    """SSE-поток не поддерживаем (stateless) — клиенту достаточно POST."""
    return JSONResponse({"error": "method_not_allowed"}, status_code=405)


@router.delete("/mcp")
def mcp_delete():
    return Response(status_code=204)
