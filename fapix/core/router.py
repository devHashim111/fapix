import inspect
from typing import List, Dict, Any, Callable, Optional

from fastapi import APIRouter, Depends

from apps.auth.permissions import security


METHOD_ACTION_MAP = {
    "post": "create",
    "put": "update",
    "patch": "update",
    "delete": "destroy",
}


def _resolve_action(view_instance: Any, method: str, explicit_action: str) -> str:
    method = method.lower()

    if explicit_action not in {"dispatch", method}:
        return explicit_action

    if method == "get":
        if hasattr(view_instance, "list_action"):
            return "list"

        if hasattr(view_instance, "retrieve_action"):
            return "retrieve"

        return "get"

    mapped_action = METHOD_ACTION_MAP.get(method)

    if mapped_action:
        if hasattr(view_instance, f"{mapped_action}_action"):
            return mapped_action

        if hasattr(view_instance, mapped_action):
            return mapped_action

    return method


def register_urlpatterns(
    router: APIRouter,
    urlpatterns: List[Dict[str, Any]],
):
    for route in urlpatterns:
        path: str = route["path"]
        view_target: Any = route["view"]
        name: Optional[str] = route.get("name")
        response_model: Any = route.get("response_model")

        dependencies: List[Any] = list(
            route.get("dependencies", [])
        )

        methods: List[str] = [
            m.upper()
            for m in route.get(
                "methods",
                [route.get("method", "GET")],
            )
        ]

        cls_target = (
            view_target
            if inspect.isclass(view_target)
            else getattr(view_target, "view_class", None)
            # BaseViewSet.as_view() returns a closure with `.cls` set to
            # the originating class (not `view_class` or `__self__`, which
            # are Starlette/bound-method conventions this project doesn't
            # use). Without this branch, cls_target was always None for
            # every `SomeView.as_view({...})` registration, which sent it
            # straight to the plain-callable fallback below: no security
            # dependency (no lock icon) and the raw `view(request, **kwargs)`
            # signature exposed to Swagger instead of anything built by
            # get_endpoint_handler() (raw args/kwargs instead of typed params).
            or getattr(view_target, "cls", None)
            or getattr(view_target, "__self__", None)
        )

        actions_map = getattr(
            view_target,
            "actions",
            {},
        ) or {}

        if cls_target:
            view_instance = (
                cls_target()
                if inspect.isclass(cls_target)
                else cls_target
            )

            if actions_map:
                for method_str, explicit_action in actions_map.items():
                    method_upper = method_str.upper()
                    method_lower = method_str.lower()

                    action_name = _resolve_action(
                        view_instance,
                        method_lower,
                        explicit_action,
                    )

                    handler: Optional[Callable] = None

                    if hasattr(view_instance, "get_endpoint_handler"):
                        handler = view_instance.get_endpoint_handler(
                            action_name
                        )

                    if not callable(handler):
                        handler = getattr(
                            view_instance,
                            action_name,
                            None,
                        )

                    if not callable(handler):
                        handler = (
                            view_target
                            if callable(view_target)
                            else view_instance.dispatch
                        )

                    route_deps = list(dependencies)

                    needs_auth = (
                        bool(
                            view_instance.get_permissions(
                                action_name
                            )
                        )
                        if hasattr(view_instance, "get_permissions")
                        else bool(
                            getattr(
                                view_instance,
                                "permission_classes",
                                [],
                            )
                        )
                    )

                    if needs_auth:
                        route_deps.append(
                            Depends(security)
                        )

                    action_schema = (
                        view_instance.get_schema(
                            action_name
                        )
                        if hasattr(view_instance, "get_schema")
                        else response_model
                    )

                    router.add_api_route(
                        path=path,
                        endpoint=handler,
                        methods=[method_upper],
                        name=(
                            f"{name}-{method_lower}"
                            if name
                            else None
                        ),
                        response_model=(
                            action_schema
                            or response_model
                        ),
                        dependencies=route_deps,
                        openapi_extra=(
                            {
                                "security": [
                                    {"HTTPBearer": []}
                                ]
                            }
                            if needs_auth
                            else None
                        ),
                    )

                continue

            for method in methods:
                method_lower = method.lower()

                action_name = _resolve_action(
                    view_instance,
                    method_lower,
                    method_lower,
                )

                handler: Optional[Callable] = None

                if hasattr(
                    view_instance,
                    "get_endpoint_handler",
                ):
                    handler = view_instance.get_endpoint_handler(
                        action_name
                    )

                if not callable(handler):
                    handler = getattr(
                        view_instance,
                        method_lower,
                        None,
                    )

                if not callable(handler):
                    handler = (
                        view_target
                        if callable(view_target)
                        else view_instance.dispatch
                    )

                route_deps = list(dependencies)

                needs_auth = (
                    bool(
                        view_instance.get_permissions(
                            action_name
                        )
                    )
                    if hasattr(view_instance, "get_permissions")
                    else bool(
                        getattr(
                            view_instance,
                            "permission_classes",
                            [],
                        )
                    )
                )

                if needs_auth:
                    route_deps.append(
                        Depends(security)
                    )

                action_schema = (
                    view_instance.get_schema(
                        action_name
                    )
                    if hasattr(view_instance, "get_schema")
                    else response_model
                )

                router.add_api_route(
                    path=path,
                    endpoint=handler,
                    methods=[method],
                    name=name,
                    response_model=(
                        action_schema
                        or response_model
                    ),
                    dependencies=route_deps,
                    openapi_extra=(
                        {
                            "security": [
                                {"HTTPBearer": []}
                            ]
                        }
                        if needs_auth
                        else None
                    ),
                )

            continue

        perm_classes = getattr(
            view_target,
            "permission_classes",
            [],
        )

        needs_auth = bool(perm_classes)

        if needs_auth:
            dependencies.append(
                Depends(security)
            )

        router.add_api_route(
            path=path,
            endpoint=view_target,
            methods=methods,
            name=name,
            response_model=response_model,
            dependencies=dependencies,
            openapi_extra=(
                {
                    "security": [
                        {"HTTPBearer": []}
                    ]
                }
                if needs_auth
                else None
            ),
        )

    return router