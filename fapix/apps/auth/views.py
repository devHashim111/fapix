from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import security as auth_settings
from fastapi import (
    HTTPException,
    status,
)


from jose import jwt, JWTError

from passlib.context import CryptContext

from .models import User
from .schemas import (
    UserCreate,
    LoginSchema,
    TokenResponse,
    RefreshTokenSchema,
    PasswordChangeSchema,
)


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# ==========================================================
# PASSWORD
# ==========================================================

def hash_password(password: str) -> str:

    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:

    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


# ==========================================================
# JWT
# ==========================================================

def create_access_token(user: User) -> str:

    expire = datetime.now(
        timezone.utc
    ) + timedelta(
        minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "type": "access",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        auth_settings.SECRET_KEY,
        algorithm=auth_settings.ALGORITHM,
    )


def create_refresh_token(user: User) -> str:

    expire = datetime.now(
        timezone.utc
    ) + timedelta(
        days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        auth_settings.SECRET_KEY,
        algorithm=auth_settings.ALGORITHM,
    )


def decode_token(token: str):

    try:

        payload = jwt.decode(
            token,
            auth_settings.SECRET_KEY,
            algorithms=[
                auth_settings.ALGORITHM
            ],
        )

        return payload

    except JWTError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# ==========================================================
# SIGNUP
# ==========================================================

async def signup_user(
    data: UserCreate,
):

    existing_user = await User.filter(
        email=data.email
    ).first()

    if existing_user:

        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )
    
    user = await User.create(
        email=data.email,
        username=data.username,
        hashed_password=hash_password(
            data.password
        ),
     
    )

    return user


# ==========================================================
# LOGIN
# ==========================================================

async def login_user(
    data: LoginSchema,
):

    user = await User.filter(
        email=data.email
    ).first()

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(
        data.password,
        user.hashed_password,
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not user.is_active:

        raise HTTPException(
            status_code=403,
            detail="User account is inactive",
        )

    access_token = create_access_token(
        user
    )

    refresh_token = create_refresh_token(
        user
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


# ==========================================================
# REFRESH
# ==========================================================

async def refresh_access_token(
    data: RefreshTokenSchema,
):

    payload = decode_token(
        data.refresh_token
    )

    if payload.get("type") != "refresh":

        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
        )

    user_id = payload.get("sub")

    user = await User.filter(
        id=user_id
    ).first()

    if not user:

        raise HTTPException(
            status_code=401,
            detail="User not found",
        )

    access_token = create_access_token(
        user
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# ==========================================================
# CHANGE PASSWORD
# ==========================================================

async def change_password(
    user: User,
    data: PasswordChangeSchema,
):

    if not verify_password(
        data.old_password,
        user.hashed_password,
    ):

        raise HTTPException(
            status_code=400,
            detail="Incorrect current password",
        )

    user.hashed_password = hash_password(
        data.new_password
    )

    await user.save()

    return {
        "detail": "Password changed successfully"
    }
    
