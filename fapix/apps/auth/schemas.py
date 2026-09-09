from uuid import UUID

from pydantic import BaseModel, EmailStr


# ==========================================================
# USER
# ==========================================================

class UserRead(BaseModel):

    id: UUID

    email: EmailStr

    username: str | None = None

    role: str

    is_active: bool

    is_verified: bool

    class Config:
        from_attributes = True


# ==========================================================
# SIGNUP
# ==========================================================

class UserCreate(BaseModel):

    email: EmailStr

    username: str | None = None

    password: str


# ==========================================================
# LOGIN
# ==========================================================

class LoginSchema(BaseModel):

    email: EmailStr

    password: str


# ==========================================================
# TOKEN
# ==========================================================

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str
    email: str
    role: str
    
    is_staff: bool = True

class RefreshTokenSchema(BaseModel):

    refresh_token: str


# ==========================================================
# PASSWORD
# ==========================================================

class PasswordChangeSchema(BaseModel):

    old_password: str

    new_password: str


class PasswordResetRequestSchema(BaseModel):

    email: EmailStr


class PasswordResetConfirmSchema(BaseModel):

    token: str

    new_password: str

class UserFullRead(UserRead):
    hashed_password: str  # or 'password', matching the exact attribute name on your User model

    class Config:
        from_attributes = True