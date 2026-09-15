
import inspect
from typing import Any, Callable, Dict, List, Type, Optional, Union
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel


def _get_security_dependency():
    """Lazily imports security instance to prevent top-level circular imports."""
    try:
        from apps.auth.permissions import security
        return security
    except ImportError:
        return None


class DefaultRouter:
    """DRF-style DefaultRouter supporting separated HTTP and WebSocket routing."""

    def __init__(self):
        self.registry: List[Dict[str, Any]] = []
        self.websocket_registry: List[Dict[str, Any]] = []

    def register(self, prefix: str, viewset: Type[Any], basename: str = ""):
        """Registers an HTTP ViewSet with a specific URL prefix and basename."""
        self.registry.append({
            "prefix": prefix.strip("/"),
            "viewset": viewset,
            "basename": basename or prefix.strip("/"),
        })

    def register_websocket(self, prefix: str, viewset: Type[Any], basename: str = ""):
        """Registers a WebSocket ViewSet."""
        self.websocket_registry.append({
            "prefix": prefix.strip("/"),
            "viewset": viewset,
            "basename": basename or prefix.strip("/"),
        })

    def _get_lookup_param(self, viewset: Any) -> str:
        """Extracts the primary lookup parameter name from the viewset."""
        lookup = getattr(viewset, "lookup_fields", None) or getattr(viewset, "lookup_field", "pk")
        if isinstance(lookup, (list, tuple)):
            return lookup[0] if lookup else "pk"
        return str(lookup)

    def _get_response_model(self, viewset: Any, action: str) -> Any:
        """Resolves the Pydantic schema model for a specific HTTP action."""
        if hasattr(viewset, "get_schema"):
            schema = viewset.get_schema(action)
            if schema:
                return schema

        action_schemas = getattr(viewset, "action_schemas", {}) or {}

        if action in action_schemas and action_schemas[action]:
            schema = action_schemas[action]
            return List[schema] if action == "list" else schema

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

        if hasattr(viewset, "get_permissions"):
            perms = viewset.get_permissions(action)
            if perms:
                has_permission = True

        action_perms = getattr(viewset, "action_permissions", {})
        if not has_permission and action in action_perms and action_perms[action]:
            has_permission = True

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

    # ------------------------------------------------------------------
    # HTTP ROUTE GENERATION
    # ------------------------------------------------------------------

    def generate_urlpatterns(self) -> List[Dict[str, Any]]:
        """Generates a standard list of HTTP route dictionaries for register_urlpatterns."""
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

        return urlpatterns

    def register_routes(self, router: APIRouter):
        """Registers HTTP routes directly onto a FastAPI APIRouter instance."""
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

    # ------------------------------------------------------------------
    # WEBSOCKET MULTIPLEXING
    # ------------------------------------------------------------------

    def generate_websocket_urlpatterns(self, path: str = "/ws") -> List[Dict[str, Any]]:
        """Generates a single WebSocket route for all registered WebSocket ViewSets."""
        if not self.websocket_registry:
            return []

        multiplexer = WebSocketMultiplexer(self.websocket_registry)

        async def websocket_gateway(websocket: WebSocket):
            await multiplexer.handle_gateway_connection(websocket)

        return [{
            "path": path,
            "view": websocket_gateway,
            "endpoint": websocket_gateway,
            "name": "websocket-gateway",
            "websocket": True,
            "include_in_schema": False,
        }]

    def register_websocket_route(self, router: APIRouter, path: str = "/ws"):
        """Registers a single WebSocket endpoint for all registered WebSocket ViewSets."""
        if not self.websocket_registry:
            return

        multiplexer = WebSocketMultiplexer(self.websocket_registry)

        @router.websocket(path)
        async def websocket_gateway(websocket: WebSocket):
            await multiplexer.handle_gateway_connection(websocket)

        for route in router.routes:
            if getattr(route, "path", None) == path and getattr(route, "endpoint", None) == websocket_gateway:
                route.include_in_schema = False


class WebSocketMultiplexer:
    """
    Multiplexes single-connection WebSocket requests to registered WebSocket ViewSets.
    Expects frames formatted as:
    {
        "viewset": "products",
        "action": "list",
        "payload": {...},
        "params": {...}
    }
    """

    def __init__(self, registry: List[Dict[str, Any]]):
        self.viewset_map: Dict[str, Any] = {}

        for item in registry:
            viewset_cls = item["viewset"]
            key = item["basename"].lower()
            self.viewset_map[key] = viewset_cls

            prefix = item["prefix"].lower()
            if prefix:
                self.viewset_map[prefix] = viewset_cls

    async def handle_gateway_connection(self, websocket: WebSocket):
        """Manages lifecycle of the single WebSocket connection per client."""

        auth_viewset_cls = next(iter(self.viewset_map.values()), None)

        if not auth_viewset_cls:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        auth_viewset = auth_viewset_cls()
        token = websocket.query_params.get("token")

        if hasattr(auth_viewset, "authenticate_websocket"):
            is_allowed = await auth_viewset.authenticate_websocket(websocket, token)

            if not is_allowed:
                await websocket.accept()
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Unauthorized or invalid token"
                )
                return

        manager = getattr(auth_viewset, "manager", None)

        if manager:
            await manager.connect(websocket)
        else:
            await websocket.accept()

        try:
            while True:
                data = await websocket.receive_json()

                target_viewset_key = data.get("viewset", "").lower()
                action = data.get("action")
                payload = data.get("payload", {})
                params = data.get("params", {})

                if not target_viewset_key or target_viewset_key not in self.viewset_map:
                    message = {
                        "status": "error",
                        "message": f"Invalid or missing viewset: '{target_viewset_key}'"
                    }

                    if manager:
                        await manager.send_personal_message(message, websocket)
                    else:
                        await websocket.send_json(message)

                    continue

                if not action:
                    message = {
                        "status": "error",
                        "message": "Missing 'action' field in WS frame"
                    }

                    if manager:
                        await manager.send_personal_message(message, websocket)
                    else:
                        await websocket.send_json(message)

                    continue

                target_cls = self.viewset_map[target_viewset_key]
                viewset_instance = target_cls()

                try:
                    response = await viewset_instance.dispatch_ws_action(
                        websocket,
                        action,
                        payload,
                        params
                    )

                    if isinstance(response, BaseModel):
                        response = response.model_dump(mode="json")

                    message = {
                        "viewset": target_viewset_key,
                        "action": action,
                        "data": response,
                        "status": "success"
                    }

                    auto_broadcast = getattr(viewset_instance, "auto_broadcast", False)
                    broadcast_on_actions = getattr(viewset_instance, "broadcast_on_actions", [])

                    if auto_broadcast and action in broadcast_on_actions and manager:
                        broadcast_self = getattr(viewset_instance, "broadcast_self", True)
                        broadcast_scope = getattr(viewset_instance, "broadcast_scope", "global")
                        sender_to_skip = None if broadcast_self else websocket

                        conn_user = getattr(websocket.state, "user", None)
                        user_id = getattr(conn_user, "id", None) if conn_user else None

                        await manager.broadcast(
                            message,
                            sender=sender_to_skip,
                            scope=broadcast_scope,
                            target_user_id=user_id
                        )

                    elif manager:
                        await manager.send_personal_message(message, websocket)

                    else:
                        await websocket.send_json(message)

                except Exception as e:
                    message = {
                        "viewset": target_viewset_key,
                        "action": action,
                        "status": "error",
                        "message": str(e)
                    }

                    if manager:
                        await manager.send_personal_message(message, websocket)
                    else:
                        await websocket.send_json(message)

        except WebSocketDisconnect:
            if manager:
                result = manager.disconnect(websocket)
                if inspect.isawaitable(result):
                    await result

        except Exception:
            if manager:
                result = manager.disconnect(websocket)
                if inspect.isawaitable(result):
                    await result

