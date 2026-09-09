from enum import Enum
from functools import wraps
from typing import Any, Optional, Union
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import User, UserRole
from .views import decode_token


security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    if credentials is None or not credentials.credentials:
        return None

    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        return None

    if not isinstance(payload, dict) or payload.get("type") != "access":
        return None

    raw_user_id = payload.get("sub")

    if not raw_user_id:
        return None

    try:
        user_id = UUID(str(raw_user_id))
    except (ValueError, TypeError):
        user_id = raw_user_id

    return await User.filter(
        id=user_id,
        is_active=True,
    ).first()


async def get_current_active_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return user


def _extract_role_str(role: Any) -> str:
    if role is None:
        return ""

    if isinstance(role, Enum):
        return str(role.value).lower()

    if hasattr(role, "value"):
        return str(role.value).lower()

    return str(role).lower()


class BasePermission:

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        return True

    async def __call__(
        self,
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided.",
            )

        if not await self.has_permission(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )

        return user


class IsAuthenticated(BasePermission):

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        return user is not None and user.is_active


class IsSuperUser(BasePermission):

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        if not user:
            return False

        user_role = _extract_role_str(user.role)
        target_role = _extract_role_str(UserRole.SUPERUSER)

        return user_role == target_role or user_role in ["superuser", "admin"]


class IsUser(BasePermission):

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        if not user:
            return False

        user_role = _extract_role_str(user.role)
        target_role = _extract_role_str(UserRole.USER)

        return user_role == target_role


class HasRole(BasePermission):

    def __init__(
        self,
        *roles: Union[str, Enum],
    ):
        self.roles = [_extract_role_str(role) for role in roles]

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        if not user:
            return False

        return _extract_role_str(user.role) in self.roles


class IsSuperUserOrRole(BasePermission):

    def __init__(
        self,
        *roles: Union[str, Enum],
    ):
        self.roles = [_extract_role_str(role) for role in roles]

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        if not user:
            return False

        user_role = _extract_role_str(user.role)
        superuser_role = _extract_role_str(UserRole.SUPERUSER)

        if user_role == superuser_role or user_role in ["superuser", "admin"]:
            return True

        return user_role in self.roles


class IsVerified(BasePermission):

    async def has_permission(
        self,
        user: Optional[User],
    ) -> bool:
        if not user:
            return False

        return getattr(user, "is_verified", False)


class AnyPermission:

    def __init__(
        self,
        *permissions: BasePermission,
    ):
        self.permissions = permissions

    async def __call__(
        self,
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided.",
            )

        for permission in self.permissions:
            if await permission.has_permission(user):
                return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )


class AllPermissions:

    def __init__(
        self,
        *permissions: BasePermission,
    ):
        self.permissions = permissions

    async def __call__(
        self,
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided.",
            )

        for permission in self.permissions:
            if not await permission.has_permission(user):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to perform this action.",
                )

        return user


def permission_required(
    permission: BasePermission,
):
    perm = permission() if isinstance(permission, type) else permission

    async def dependency(
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided.",
            )

        if not await perm.has_permission(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied.",
            )

        return user

    return dependency