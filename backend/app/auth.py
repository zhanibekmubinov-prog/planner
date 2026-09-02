from fastapi import Header, HTTPException, status
from .config import settings


def require_token(x_api_token: str = Header(default="")) -> None:
    if x_api_token != settings.api_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
