import functools
import inspect
from typing import Any, Callable, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from apps.auth.permissions import get_current_user, security


def _add_security_to_signature(func: Callable) -> None:
    if getattr(func, "_security_signature_added", False):
        return

    try:
        signature = inspect.signature(func)
        parameters = list(signature.parameters.values())

        parameters = [
            param
            for param in parameters
            if param.name not in {"auth"}
            and param.kind not in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }
        ]

        parameters.append(
            inspect.Parameter(
                "auth",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Optional[HTTPAuthorizationCredentials],
                default=Depends(security),
            )
        )

        func.__signature__ = signature.replace(parameters=parameters)
        func._security_signature_added = True
    except (TypeError, ValueError):
        pass


def action(
    methods: Optional[List[str]] = None,
    detail: bool = False,
    url_path: Optional[str] = None,
    url_name: Optional[str] = None,
    **kwargs: Any,
) -> Callable:
    if methods is None:
        methods = ["get"]

    methods = [m.lower() for m in methods]

    def decorator(func: Callable) -> Callable:
        func.is_action = True
        func.action_methods = methods
        func.action_detail = detail
        func.action_url_path = url_path or func.__name__
        func.action_url_name = url_name or func.__name__
        func.action_kwargs = kwargs
        return func

    return decorator


def permission_classes(perms: List[Any]) -> Callable:
    def decorator(func: Callable) -> Callable:
        func.permission_classes = perms

        if getattr(func, "_is_api_view", False):
            _add_security_to_signature(func)

        return func

    return decorator


def api_view(http_methods: Optional[List[str]] = None) -> Callable:
    allowed_methods = [m.upper() for m in (http_methods or ["GET"])]

    def decorator(func: Callable) -> Callable:
        perms = getattr(func, "permission_classes", [])

        @functools.wraps(func)
        async def wrapper(
            request: Request,
            *args: Any,
            auth: Optional[HTTPAuthorizationCredentials] = None,
            **kwargs: Any,
        ):
            if request.method.upper() not in allowed_methods:
                raise HTTPException(
                    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                    detail=f"Method '{request.method}' not allowed."
                )

            user = getattr(request.state, "user", None)

            if not user and auth:
                user = await get_current_user(auth)
                request.state.user = user

            current_perms = getattr(
                wrapper,
                "permission_classes",
                getattr(func, "permission_classes", [])
            )

            for perm_cls in current_perms:
                perm = perm_cls() if isinstance(perm_cls, type) else perm_cls

                if not hasattr(perm, "has_permission"):
                    continue

                result = perm.has_permission(user)

                if inspect.isawaitable(result):
                    result = await result

                if not result:
                    if not user:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentication credentials were not provided."
                        )

                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Permission denied."
                    )

            return await func(request, *args, **kwargs)

        wrapper.http_methods = allowed_methods
        wrapper._is_api_view = True

        if perms:
            _add_security_to_signature(wrapper)

        return wrapper

    return decorator