from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_session
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import User

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


async def require_admin(user_id: CurrentUserId, session: Session) -> str:
    role = await session.scalar(select(User.role).where(User.id == user_id))
    if role != "ADMIN":
        raise ApplicationError("ADMIN_REQUIRED", "Administrator access required", status_code=403)
    return user_id


AdminUserId = Annotated[str, Depends(require_admin)]
