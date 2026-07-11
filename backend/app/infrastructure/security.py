from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import User

password_hash = PasswordHash.recommended()


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(self, email: str, password: str) -> str:
        user = User(email=email.lower(), password_hash=password_hash.hash(password))
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                "EMAIL_ALREADY_EXISTS", "Email already registered", status_code=409
            ) from exc
        await self.session.refresh(user)
        return self._create_token(user.id)

    async def login(self, email: str, password: str) -> str:
        user = await self.session.scalar(select(User).where(User.email == email.lower()))
        if user is None or not password_hash.verify(password, user.password_hash):
            raise ApplicationError(
                "INVALID_CREDENTIALS", "Invalid email or password", status_code=401
            )
        if user.status != "ACTIVE":
            raise ApplicationError("USER_DISABLED", "User account is disabled", status_code=403)
        return self._create_token(user.id)

    def _create_token(self, user_id: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user_id,
                "iat": now,
                "exp": now + timedelta(minutes=self.settings.jwt_expire_minutes),
            },
            self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )
