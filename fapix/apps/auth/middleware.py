# apps/auth/middleware.py
from uuid import UUID
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from .models import User
from .views import decode_token


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user = None
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                payload = decode_token(token)
                if payload.get("type") == "access":
                    raw_user_id = payload.get("sub")
                    try:
                        user_id = UUID(str(raw_user_id))
                    except (ValueError, TypeError):
                        user_id = raw_user_id

                    # Fetch user model instance and attach to request state
                    request.state.user = await User.filter(id=user_id, is_active=True).first()
            except Exception:
                request.state.user = None

        response = await call_next(request)
        return response