from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from .config import settings

# Security-схема: в Swagger (/docs) появляется кнопка Authorize,
# токен вводится один раз и подставляется во все запросы.
api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)


def require_token(token: str | None = Depends(api_key_header)) -> None:
    if not token or token != settings.api_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
