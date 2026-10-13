from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant, User
from app.db.session import get_session
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False, description="JWT issued by /api/auth/login")


@dataclass(frozen=True)
class Principal:
    """The authenticated caller.

    ``tenant_id`` is the isolation boundary — every query in the API layer must filter on it.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token")

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise _unauthorized("Invalid or expired token")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        raise _unauthorized("Malformed token subject") from None

    # Re-read the user on every request so a deleted account or a moved tenant takes effect
    # immediately rather than at token expiry.
    stmt = (
        select(User, Tenant.name)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == user_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise _unauthorized("Account no longer exists")

    user, tenant_name = row
    return Principal(user_id=user.id, tenant_id=user.tenant_id, email=user.email)
