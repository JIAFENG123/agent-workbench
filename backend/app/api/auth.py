from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Tenant, User
from app.db.session import get_session
from app.deps import Principal, get_principal
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    email = payload.email.lower()

    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Every account gets its own tenant: the isolation boundary is created at signup so no
    # code path can ever produce a user without one.
    tenant = Tenant(name=payload.tenant_name or f"{email} 的工作区")
    session.add(tenant)
    await session.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None

    logger.info("user_registered", user_id=str(user.id), tenant_id=str(tenant.id))
    return TokenResponse(
        access_token=create_access_token(str(user.id), str(tenant.id)),
        expires_in_minutes=settings.jwt_expire_minutes,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    email = payload.email.lower()
    user = await session.scalar(select(User).where(User.email == email))

    # Same error for unknown email and wrong password — do not leak which accounts exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(user.tenant_id)),
        expires_in_minutes=settings.jwt_expire_minutes,
    )


@router.get("/me", response_model=UserOut)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    row = (
        await session.execute(
            select(User, Tenant.name)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(User.id == principal.user_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user, tenant_name = row
    return UserOut(
        id=user.id,
        email=user.email,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        created_at=user.created_at,
    )
