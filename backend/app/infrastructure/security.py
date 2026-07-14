from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
        user = User(email=email.lower(), password_hash=password_hash.hash(password), role="USER")
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

    async def admin_login(self, username: str, password: str) -> str:
        if not self.settings.admin_username or not self.settings.admin_password:
            raise ApplicationError(
                "ADMIN_LOGIN_NOT_CONFIGURED",
                "Administrator login is not configured",
                status_code=503,
            )
        if username != self.settings.admin_username or password != self.settings.admin_password:
            raise ApplicationError(
                "INVALID_CREDENTIALS", "Invalid administrator credentials", status_code=401
            )
        email = f"{self.settings.admin_username}@example.com".lower()
        user = await self.session.scalar(select(User).where(User.email == email))
        hashed_password = password_hash.hash(password)
        if user is None:
            user = User(email=email, password_hash=hashed_password, role="ADMIN")
            self.session.add(user)
        else:
            user.password_hash = hashed_password
            user.role = "ADMIN"
            user.status = "ACTIVE"
        await self.session.commit()
        await self.session.refresh(user)
        return self._create_token(user.id)

    async def visitor_access(self, access_key: str) -> str:
        if not self.settings.visitor_access_key:
            raise ApplicationError(
                "VISITOR_ACCESS_NOT_CONFIGURED",
                "Visitor access is not configured",
                status_code=503,
            )
        if access_key != self.settings.visitor_access_key:
            raise ApplicationError("INVALID_ACCESS_KEY", "Invalid access key", status_code=401)
        user = User(
            email=f"visitor-{uuid4()}@example.com",
            password_hash=password_hash.hash(str(uuid4())),
            role="USER",
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
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
