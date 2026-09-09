import inspect
from typing import Any, Callable, Dict, List, Type
from fastapi import APIRouter, Depends


def _get_security_dependency():
    """Lazily imports security instance to prevent top-level circular imports."""
    try:
        from apps.auth.permissions import security
        return security
    except ImportError:
        return None


class DefaultRouter:
    """DRF-style DefaultRouter supporting HTTP endpoints and WebSocket handlers."""

    def __init__(self):
        self.registry: List[Dict[str, Any]] = []

    def _get_lookup_param(self, viewset: Any) -> str:
        """Extracts the primary lookup parameter name from the viewset."""
        lookup = getattr(viewset, "lookup_fields", None) or getattr(viewset, "lookup_field", "pk")
        if isinstance(lookup, (list, tuple)):
            return lookup[0] if lookup else "pk"
        return str(lookup)

    def _get_response_model(self, viewset: Any, action: str) -> Any:
        """Resolves the Pydantic schema model for a specific action."""
        # 1. Dynamic viewset schema resolver (highest precedence)
        if hasattr(viewset, "get_schema"):
            schema = viewset.get_schema(action)
            if schema:
                return schema

        action_schemas = getattr(viewset, "action_schemas", {}) or {}

        # 2. Action-specific schema override
        if action in action_schemas and action_schemas[action]:
            schema = action_schemas[action]
            return List[schema] if action == "list" else schema

        # 3. Fallback to base viewset schema
        schema = getattr(viewset, "schema", None)
        if schema:
            return List[schema] if action == "list" else schema

        return None

    def _resolve_dependencies(self, viewset: Any, action: str) -> List[Any]:
        """Resolves action-level & class-level security dependencies safely without duplicates."""
        security_dep = _get_security_dependency()
        if not security_dep:
            return []

        has_permission = False

        # 1. Check get_permissions(action) on instance
        if hasattr(viewset, "get_permissions"):
            perms = viewset.get_permissions(action)
            if perms:
                has_permission = True

        # 2. Check action_permissions on class
        action_perms = getattr(viewset, "action_permissions", {})
        if not has_permission and action in action_perms and action_perms[action]:
            has_permission = True

        # 3. Check base permission_classes
        if not has_permission and getattr(viewset, "permission_classes", []):
            has_permission = True

        return [Depends(security_dep)] if has_permission else []

    def _resolve_handler(self, viewset: Any, action_name: str) -> Callable:
        """Retrieves dynamically wrapped handler (with typed body) if present."""
        if hasattr(viewset, "get_endpoint_handler"):
            handler = viewset.get_endpoint_handler(action_name)
            if handler:
                return handler
        return getattr(viewset, action_name, None)

    def register(self, prefix: str, viewset: Type[Any], basename: str = ""):
        self.registry.append({
            "prefix": prefix.strip("/"),
            "viewset": viewset,
            "basename": basename or prefix.strip("/"),
        })

    def generate_urlpatterns(self) -> List[Dict[str, Any]]:
        """Generates a standard list of route dictionaries for register_urlpatterns."""
        urlpatterns = []

        for item in self.registry:
            prefix = item["prefix"]
            base_path = f"/{prefix}" if prefix else ""
            viewset_cls = item["viewset"]
            viewset = viewset_cls() if inspect.isclass(viewset_cls) else viewset_cls
            lookup_param = self._get_lookup_param(viewset)

            actions = [
                ("list", "GET", base_path or "/", f"{item['basename']}-list"),
                ("create", "POST", base_path or "/", f"{item['basename']}-create"),
                ("retrieve", "GET", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-detail"),
                ("update", "PUT", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-update"),
                ("destroy", "DELETE", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-delete"),
            ]

            for action_name, method, path, name in actions:
                if hasattr(viewset, action_name):
                    route_dict = {
                        "path": path,
                        "view": self._resolve_handler(viewset, action_name),
                        "method": method,
                        "methods": [method],
                        "name": name,
                        "dependencies": self._resolve_dependencies(viewset, action_name),
                    }
                    response_model = self._get_response_model(viewset, action_name)
                    if response_model:
                        route_dict["response_model"] = response_model

                    urlpatterns.append(route_dict)

            if hasattr(viewset, "handle_connection"):
                urlpatterns.append({
                    "path": f"/ws{base_path}",
                    "view": getattr(viewset_cls, "handle_connection"),
                    "method": "WEBSOCKET",
                    "methods": ["WEBSOCKET"],
                    "name": f"{item['basename']}-ws",
                })

        return urlpatterns

    def register_routes(self, router: APIRouter):
        """Registers routes directly onto a FastAPI APIRouter instance."""
        for item in self.registry:
            prefix = item["prefix"]
            base_path = f"/{prefix}" if prefix else ""
            viewset_cls = item["viewset"]
            viewset = viewset_cls() if inspect.isclass(viewset_cls) else viewset_cls
            lookup_param = self._get_lookup_param(viewset)
            tags = [item["basename"]]

            actions = [
                ("list", "GET", base_path or "/", f"{item['basename']}-list"),
                ("create", "POST", base_path or "/", f"{item['basename']}-create"),
                ("retrieve", "GET", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-detail"),
                ("update", "PUT", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-update"),
                ("destroy", "DELETE", f"{base_path}/{{{lookup_param}}}", f"{item['basename']}-delete"),
            ]

            for action_name, method, path, name in actions:
                if hasattr(viewset, action_name):
                    kwargs = {
                        "path": path,
                        "endpoint": self._resolve_handler(viewset, action_name),
                        "methods": [method],
                        "name": name,
                        "tags": tags,
                        "dependencies": self._resolve_dependencies(viewset, action_name),
                    }
                    response_model = self._get_response_model(viewset, action_name)
                    if response_model:
                        kwargs["response_model"] = response_model

                    router.add_api_route(**kwargs)

            if hasattr(viewset, "handle_connection"):
                router.add_api_websocket_route(
                    f"/ws{base_path}",
                    endpoint=getattr(viewset_cls, "handle_connection"),
                    name=f"{item['basename']}-ws",
                )