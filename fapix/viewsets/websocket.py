import inspect
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union, Callable, Set
from fastapi import WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ValidationError

from .base import BaseViewSet, DefaultPagination
from .tortoise.mixins import (
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    BulkDeleteSchema,
)


class BroadcastScope(str, Enum):
    GLOBAL = "global"               # All connected sockets
    AUTHENTICATED = "authenticated" # Authenticated sockets only
    USER = "user"                   # Sockets matching target user ID
    ROLE = "role"                   # Sockets matching target user role (e.g. 'admin', 'superuser')
    GROUP = "group"                 # Sockets matching target group/team ID
    DYNAMIC = "dynamic"             # Target matching a specific attribute key-value pair on user state


class WebSocketManager:
    """Standalone/Reusable Manager with targeted Broadcast Scopes."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        print("websocket initiated")
    async def connect(self, websocket: WebSocket):
        # Always accept handshake if not already accepted
        if websocket.client_state.name == "CONNECTING":
            await websocket.accept()
            print("connection established")
        self.active_connections.add(websocket)
        print("adding connections")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        print("disconnecting ...")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    async def broadcast(
        self, 
        message: dict, 
        sender: Optional[WebSocket] = None,
        scope: BroadcastScope = BroadcastScope.GLOBAL,
        target_user_id: Optional[Any] = None,
        target_role: Optional[str] = None,
        target_group_id: Optional[Any] = None,
        dynamic_attr_name: Optional[str] = None,
        dynamic_attr_value: Optional[Any] = None,
    ):
        dead_connections: Set[WebSocket] = set()

        for connection in list(self.active_connections):
            if sender and connection == sender:
                continue

            conn_user = getattr(getattr(connection, "state", None), "user", None)

            # Scope Filtering Logic
            if scope == BroadcastScope.AUTHENTICATED and not conn_user:
                continue

            if scope == BroadcastScope.USER:
                if not conn_user:
                    continue
                conn_user_id = getattr(conn_user, "id", None) or getattr(conn_user, "pk", None)
                if str(conn_user_id) != str(target_user_id):
                    continue

            if scope == BroadcastScope.ROLE:
                if not conn_user:
                    continue
                user_role = getattr(conn_user, "role", None)
                if is_superuser := getattr(conn_user, "is_superuser", False):
                    user_role = "superuser" if not user_role else user_role
                if str(user_role) != str(target_role):
                    continue

            if scope == BroadcastScope.GROUP:
                if not conn_user:
                    continue
                conn_group_id = getattr(conn_user, "group_id", None) or getattr(conn_user, "team_id", None)
                if str(conn_group_id) != str(target_group_id):
                    continue

            if scope == BroadcastScope.DYNAMIC:
                if not conn_user or not dynamic_attr_name:
                    continue
                val = getattr(conn_user, dynamic_attr_name, None)
                if str(val) != str(dynamic_attr_value):
                    continue

            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        for dead in dead_connections:
            self.disconnect(dead)


# Global connection manager shared across viewsets
global_ws_manager = WebSocketManager()


class DummyRequest:
    """Mock Request object mapping WebSocket properties for HTTP-compatible Mixins."""
    def __init__(self, websocket: WebSocket):
        self.scope = websocket.scope
        self.state = websocket.state
        self.headers = websocket.headers
        self.query_params = websocket.query_params
        self.url = websocket.url
        self.client = websocket.client


class WebSocketApiView(BaseViewSet):
    """Declarative WebSocket ViewSet supporting action permissions, schemas & scope broadcasts."""

    auto_broadcast: bool = False
    broadcast_self: bool = True
    broadcast_scope: BroadcastScope = BroadcastScope.GLOBAL
    broadcast_on_actions: List[str] = ["create", "update", "destroy", "bulk_create", "bulk_update", "bulk_destroy"]

    # Optional dynamic attributes for targeted broadcasts
    broadcast_target_role: Optional[str] = None
    broadcast_target_group_field: Optional[str] = None
    broadcast_dynamic_attr: Optional[str] = None

    manager: WebSocketManager = global_ws_manager

    @classmethod
    async def handle_connection(cls, websocket: WebSocket):
        """Entry point for handling isolated WebSocket endpoint routes."""
        self = cls()
        token = websocket.query_params.get("token")

        is_allowed = await self.authenticate_websocket(websocket, token)
        if not is_allowed:
            # Accept handshake first to prevent HTTP 403 response before policy violation closure
            await websocket.accept()
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Unauthorized or invalid token"
            )
            return

        await self.manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_json()
                action = data.get("action")
                payload = data.get("payload", {})
                params = data.get("params", {})

                if not action:
                    await self.manager.send_personal_message(
                        {"status": "error", "message": "Missing 'action' field in WS frame"},
                        websocket
                    )
                    continue

                try:
                    # Action-level permission check
                    await self.dispatch_permission_check(websocket, action)

                    # Execute action logic
                    response = await self.dispatch_ws_action(websocket, action, payload, params)

                    if isinstance(response, BaseModel):
                        response = response.model_dump(mode="json")

                    # Broadcast or respond back to sender
                    if self.auto_broadcast and action in self.broadcast_on_actions:
                        sender_to_skip = None if self.broadcast_self else websocket
                        conn_user = getattr(getattr(websocket, "state", None), "user", None)
                        user_id = getattr(conn_user, "id", None) if conn_user else None
                        
                        target_group_val = None
                        if self.broadcast_target_group_field and conn_user:
                            target_group_val = getattr(conn_user, self.broadcast_target_group_field, None)

                        dynamic_val = None
                        if self.broadcast_dynamic_attr and conn_user:
                            dynamic_val = getattr(conn_user, self.broadcast_dynamic_attr, None)

                        await self.manager.broadcast(
                            {"action": action, "data": response, "status": "success"},
                            sender=sender_to_skip,
                            scope=self.broadcast_scope,
                            target_user_id=user_id,
                            target_role=self.broadcast_target_role,
                            target_group_id=target_group_val,
                            dynamic_attr_name=self.broadcast_dynamic_attr,
                            dynamic_attr_value=dynamic_val,
                        )
                    else:
                        await self.manager.send_personal_message(
                            {"action": action, "data": response, "status": "success"},
                            websocket
                        )

                except ValidationError as ve:
                    await self.manager.send_personal_message(
                        {"action": action, "status": "error", "errors": ve.errors()},
                        websocket
                    )
                except Exception as e:
                    await self.manager.send_personal_message(
                        {"action": action, "status": "error", "message": str(e)},
                        websocket
                    )

        except WebSocketDisconnect:
            self.manager.disconnect(websocket)
        except Exception:
            self.manager.disconnect(websocket)

    async def dispatch_permission_check(self, websocket: WebSocket, action: str):
        """Evaluates view permissions dynamically for WebSocket actions matching HTTP layer logic."""
        perms = self.get_permissions(action)
        if not perms:
            return

        user = getattr(getattr(websocket, "state", None), "user", None)
        dummy_req = DummyRequest(websocket)

        for perm_cls in perms:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls

            if hasattr(perm, "has_permission"):
                sig = inspect.signature(perm.has_permission)
                params = list(sig.parameters.keys())

                if "user" in params and "request" not in params:
                    res = perm.has_permission(user)
                elif len(params) >= 2:
                    res = perm.has_permission(dummy_req, self)
                elif len(params) == 1:
                    res = perm.has_permission(dummy_req)
                else:
                    res = perm.has_permission(user)

                if inspect.iscoroutine(res) or inspect.isawaitable(res):
                    is_allowed = await res
                else:
                    is_allowed = res
            else:
                is_allowed = True

            if not is_allowed:
                raise PermissionError(f"Permission denied for action '{action}'")

    async def dispatch_ws_action(
        self,
        websocket: WebSocket,
        action: str,
        payload: Union[Dict[str, Any], List[Dict[str, Any]]],
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        handler = getattr(self, f"action_{action}", None) or getattr(self, action, None)
        if callable(handler):
            return await handler(payload, params=params)
        raise NotImplementedError(f"Action '{action}' is not supported on this WebSocket view.")

    async def authenticate_websocket(self, websocket: WebSocket, token: Optional[str]) -> bool:
        """Validates token and runs ws_connect connection permissions."""
        if not token:
            # If no permissions required on connection, permit unauthenticated connection
            if not self.get_permissions("ws_connect"):
                return True
            return False

        user = await self.get_user_from_token(token)
        if not user and self.get_permissions("ws_connect"):
            return False

        websocket.state.user = user
        perms = self.get_permissions("ws_connect")
        dummy_req = DummyRequest(websocket)

        for perm_cls in perms:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls
            if hasattr(perm, "has_permission"):
                sig = inspect.signature(perm.has_permission)
                params = list(sig.parameters.keys())

                if "user" in params and "request" not in params:
                    res = perm.has_permission(user)
                elif len(params) >= 2:
                    res = perm.has_permission(dummy_req, self)
                elif len(params) == 1:
                    res = perm.has_permission(dummy_req)
                else:
                    res = perm.has_permission(user)

                if inspect.iscoroutine(res) or inspect.isawaitable(res):
                    is_allowed = await res
                else:
                    is_allowed = res

                if not is_allowed:
                    return False

        return True

    async def get_user_from_token(self, token: str) -> Optional[Any]:
        """Resolves active user instance using standard HTTP authentication security logic."""
        try:
            from fastapi.security import HTTPAuthorizationCredentials
            from apps.auth.permissions import get_current_user

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            return await get_current_user(creds)
        except Exception:
            return None


class WebSocketModelViewSet(
    WebSocketApiView,
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
):
    """Network-Agnostic WebSocket ModelViewSet with Paginated Lists & Bulk Actions."""
    print("websocketmodelviewset class initiated")
    def _serialize(self, instance: Any, schema: Optional[Type[BaseModel]]) -> Any:
        if not instance:
            return instance
        if isinstance(instance, BaseModel):
            return instance.model_dump(mode="json")
        if isinstance(instance, dict):
            return instance
        if schema:
            return schema.model_validate(instance, from_attributes=True).model_dump(mode="json")
        return instance

    def _validate_input(self, payload: Any, schema: Optional[Type[BaseModel]]) -> Any:
        if not schema:
            return payload

        if isinstance(payload, list):
            return [
                schema.model_validate(item).model_dump() if isinstance(item, dict) else item
                for item in payload
            ]
        elif isinstance(payload, dict):
            return schema.model_validate(payload).model_dump()
        return payload

    async def dispatch_ws_action(
        self, 
        websocket: WebSocket, 
        action: str, 
        payload: Union[Dict[str, Any], List[Dict[str, Any]]],
        params: Optional[Dict[str, Any]] = None
    ):
        schema = self.get_schema(action)
        params = params or {}
        dummy_req = DummyRequest(websocket)

        # 1. LIST ACTION
        if action == "list":
            search = params.get("search")
            ordering = params.get("ordering")
            page = int(params.get("page", 1))
            page_size = int(params.get("page_size", getattr(self, "page_size", 10)))

            extra_filters = {
                k: v for k, v in params.items() 
                if k not in ["search", "ordering", "page", "page_size"]
            }

            res = await self.list_action(
                request=dummy_req,
                search=search, 
                ordering=ordering, 
                page=page, 
                page_size=page_size, 
                **extra_filters
            )

            if schema and isinstance(res, dict) and "results" in res:
                res["results"] = [self._serialize(item, schema) for item in res["results"]]
            return res

        # 2. CREATE / BULK CREATE
        elif action == "create":
            validated_payload = self._validate_input(payload, schema)
            if isinstance(validated_payload, list):
                if hasattr(self, "bulk_create_action"):
                    instances = await self.bulk_create_action(validated_payload, request=dummy_req)
                else:
                    instances = [await self.create_action(p, request=dummy_req) for p in validated_payload]
                return [self._serialize(i, schema) for i in instances]

            instance = await self.create_action(validated_payload, request=dummy_req)
            return self._serialize(instance, schema)

        elif action == "bulk_create":
            payload_list = payload if isinstance(payload, list) else [payload]
            validated_payloads = self._validate_input(payload_list, schema)
            if hasattr(self, "bulk_create_action"):
                instances = await self.bulk_create_action(validated_payloads, request=dummy_req)
            else:
                instances = [await self.create_action(p, request=dummy_req) for p in validated_payloads]
            return [self._serialize(i, schema) for i in instances]

        # 3. RETRIEVE
        elif action == "retrieve":
            lookup_field = getattr(self, "lookup_field", "id")
            lookup_data = payload if isinstance(payload, dict) else {lookup_field: payload}
            instance = await self.retrieve_action(lookup_data, request=dummy_req)
            return self._serialize(instance, schema)

        # 4. UPDATE / BULK UPDATE
        elif action == "update":
            lookup_field = getattr(self, "lookup_field", "id")
            if isinstance(payload, list):
                if hasattr(self, "bulk_update_action"):
                    instances = await self.bulk_update_action(payload, request=dummy_req)
                    return [self._serialize(i, schema) for i in instances]

            lookup_data = payload.get("lookup", {lookup_field: payload.get(lookup_field)}) if isinstance(payload, dict) else {lookup_field: payload}
            update_data = payload.get("data", payload) if isinstance(payload, dict) else {}
            validated_update = self._validate_input(update_data, schema)
            
            instance = await self.update_action(lookup_data, validated_update, request=dummy_req)
            return self._serialize(instance, schema)

        elif action == "bulk_update":
            payload_list = payload if isinstance(payload, list) else [payload]
            if hasattr(self, "bulk_update_action"):
                instances = await self.bulk_update_action(payload_list, request=dummy_req)
                return [self._serialize(i, schema) for i in instances]

        # 5. DESTROY / BULK DESTROY
        elif action == "destroy":
            if isinstance(payload, dict) and "keys" in payload:
                bulk_schema = BulkDeleteSchema(keys=payload["keys"])
                return await self.bulk_destroy_action(bulk_schema, request=dummy_req)

            lookup_field = getattr(self, "lookup_field", "id")
            lookup_data = payload if isinstance(payload, dict) else {lookup_field: payload}
            success = await self.destroy_action(lookup_data, request=dummy_req)
            return {"detail": "Deleted successfully", "success": success}

        elif action == "bulk_destroy":
            keys = payload.get("keys", payload) if isinstance(payload, dict) else payload
            bulk_schema = BulkDeleteSchema(keys=keys)
            return await self.bulk_destroy_action(bulk_schema, request=dummy_req)

        # Fallback to custom method on class
        return await super().dispatch_ws_action(websocket, action, payload, params)


class WebSocketMultiplexer:
    """
    Multiplexer enabling multiple ViewSets (e.g. products, orders, notifications) 
    to share a single persistent WebSocket connection.
    """

    def __init__(self, manager: Optional[WebSocketManager] = None):
        self.viewset_map: Dict[str, Type[WebSocketApiView]] = {}
        self.manager: WebSocketManager = manager or global_ws_manager

    def register(self, name: str, viewset_cls: Type[WebSocketApiView]):
        """Registers a viewset under a unique moniker/basename."""
        self.viewset_map[name] = viewset_cls

    async def handle_gateway_connection(self, websocket: WebSocket):
        """Single connection entrypoint for frame routing across registered apps."""
        token = websocket.query_params.get("token")

        if not self.viewset_map:
            await websocket.accept()
            await websocket.close(code=status.WS_1011_UNEXPECTED_CONDITION, reason="No viewsets registered")
            return

        # Authenticate against first viewset's auth configuration
        first_viewset_cls = next(iter(self.viewset_map.values()))
        print("WS GATEWAY REACHED")
        auth_instance = first_viewset_cls()
        print("WS auth granted")
        is_allowed = await auth_instance.authenticate_websocket(websocket, token)
        if not is_allowed:
            # ACCEPT FIRST so HTTP 403 response isn't generated
            await websocket.accept()
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Unauthorized or invalid token"
            )
            return

        await self.manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_json()
                target_viewset_key = data.get("viewset")
                action = data.get("action")
                payload = data.get("payload", {})
                params = data.get("params", {})

                if not target_viewset_key or target_viewset_key not in self.viewset_map:
                    await self.manager.send_personal_message(
                        {
                            "status": "error", 
                            "message": f"Invalid or missing 'viewset' target. Available: {list(self.viewset_map.keys())}"
                        },
                        websocket
                    )
                    continue

                if not action:
                    await self.manager.send_personal_message(
                        {"status": "error", "message": "Missing 'action' field in payload"},
                        websocket
                    )
                    continue

                # Instantiate targeted viewset class dynamically per request
                viewset_cls = self.viewset_map[target_viewset_key]
                viewset_instance = viewset_cls()

                try:
                    # Action permission check
                    await viewset_instance.dispatch_permission_check(websocket, action)

                    # Execute payload action
                    response = await viewset_instance.dispatch_ws_action(
                        websocket=websocket,
                        action=action,
                        payload=payload,
                        params=params
                    )

                    if isinstance(response, BaseModel):
                        response = response.model_dump(mode="json")

                    # Handle targeted auto-broadcasting
                    if viewset_instance.auto_broadcast and action in viewset_instance.broadcast_on_actions:
                        sender_to_skip = None if viewset_instance.broadcast_self else websocket
                        conn_user = getattr(getattr(websocket, "state", None), "user", None)
                        user_id = getattr(conn_user, "id", None) if conn_user else None

                        target_group_val = None
                        if viewset_instance.broadcast_target_group_field and conn_user:
                            target_group_val = getattr(conn_user, viewset_instance.broadcast_target_group_field, None)

                        dynamic_val = None
                        if viewset_instance.broadcast_dynamic_attr and conn_user:
                            dynamic_val = getattr(conn_user, viewset_instance.broadcast_dynamic_attr, None)

                        await self.manager.broadcast(
                            {
                                "viewset": target_viewset_key,
                                "action": action, 
                                "data": response, 
                                "status": "success"
                            },
                            sender=sender_to_skip,
                            scope=viewset_instance.broadcast_scope,
                            target_user_id=user_id,
                            target_role=viewset_instance.broadcast_target_role,
                            target_group_id=target_group_val,
                            dynamic_attr_name=viewset_instance.broadcast_dynamic_attr,
                            dynamic_attr_value=dynamic_val,
                        )
                    else:
                        await self.manager.send_personal_message(
                            {
                                "viewset": target_viewset_key,
                                "action": action, 
                                "data": response, 
                                "status": "success"
                            },
                            websocket
                        )

                except ValidationError as ve:
                    await self.manager.send_personal_message(
                        {
                            "viewset": target_viewset_key,
                            "action": action, 
                            "status": "error", 
                            "errors": ve.errors()
                        },
                        websocket
                    )
                except Exception as e:
                    await self.manager.send_personal_message(
                        {
                            "viewset": target_viewset_key,
                            "action": action, 
                            "status": "error", 
                            "message": str(e)
                        },
                        websocket
                    )

        except WebSocketDisconnect:
            self.manager.disconnect(websocket)
        except Exception:
            self.manager.disconnect(websocket)