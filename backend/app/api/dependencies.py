from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_session
from app.infrastructure.errors import ApplicationError

Session = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(HTTPBearer(auto_error=False)),
]


async def get_current_user_id(
    credentials: BearerCredentials,
    settings: SettingsDependency,
) -> str:
    if credentials is None:
        raise ApplicationError("AUTH_REQUIRED", "Authentication required", status_code=401)
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise InvalidTokenError
        return user_id
    except InvalidTokenError as exc:
        raise ApplicationError(
            "INVALID_TOKEN", "Invalid or expired token", status_code=401
        ) from exc


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
