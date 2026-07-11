from fastapi import APIRouter, status

from app.api.dependencies import Session, SettingsDependency
from app.api.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.infrastructure.security import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: Session,
    settings: SettingsDependency,
) -> TokenResponse:
    token = await AuthService(session, settings).register(payload.email, payload.password)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: Session,
    settings: SettingsDependency,
) -> TokenResponse:
    token = await AuthService(session, settings).login(payload.email, payload.password)
    return TokenResponse(access_token=token)
