import inspect
import logging
import time
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

# ------------------------------------------------------------------
# UVICORN-STYLE FORMATTED LOGGING
# ------------------------------------------------------------------

class UvicornStyleFormatter(logging.Formatter):
    """Custom logging formatter mimicking Uvicorn's clean, colorized output style."""

    LEVEL_COLORS = {
        logging.DEBUG: "\x1b[36m",    # Cyan
        logging.INFO: "\x1b[32m",     # Green
        logging.WARNING: "\x1b[33m",  # Yellow
        logging.ERROR: "\x1b[31m",    # Red
        logging.CRITICAL: "\x1b[35m", # Magenta
    }
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        levelname = f"{color}{record.levelname:<8}{self.RESET}"
        prefix = f"{self.BOLD}INFO{self.RESET}:     " if record.levelno == logging.INFO else f"{levelname}: "
        return f"{prefix}{record.getMessage()}"


logger = logging.getLogger("fapix.websocket")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(UvicornStyleFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class BroadcastScope(str, Enum):
    GLOBAL = "global"               # All connected sockets
    AUTHENTICATED = "authenticated" # Authenticated sockets only
    USER = "user"                   # Sockets matching target user ID
    ROLE = "role"                   # Sockets matching target user role (e.g. 'admin', 'superuser')
    GROUP = "group"                 # Sockets matching target group/team ID
    DYNAMIC = "dynamic"             # Target matching a specific attribute key-value pair on user state


class WebSocketManager:
    """Standalone/Reusable Manager with targeted Broadcast Scopes and activity logging."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        # Always accept handshake if not already accepted
        if websocket.client_state.name == "CONNECTING":
            await websocket.accept()
          
        self.active_connections.add(websocket)
        client_host = getattr(websocket.client, "host", "127.0.0.1")
        client_port = getattr(websocket.client, "port", 0)
        logger.info(f"WebSocket connection established with \x1b[36m{client_host}:{client_port}\x1b[0m")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.discard(websocket)
            client_host = getattr(websocket.client, "host", "127.0.0.1")
            client_port = getattr(websocket.client, "port", 0)
            logger.info(f"WebSocket connection closed for \x1b[36m{client_host}:{client_port}\x1b[0m")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send personal WS frame: {e}")
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
        delivered_count = 0

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
                delivered_count += 1
            except Exception:
                dead_connections.add(connection)

        for dead in dead_connections:
            self.disconnect(dead)

        action = message.get("action", "unknown")
        logger.info(f"Broadcast [\x1b[33m{action}\x1b[0m] via scope '\x1b[35m{scope.value}\x1b[0m' delivered to {delivered_count} clients")


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

    broadcast_target_role: Optional[str] = None
    broadcast_target_group_field: Optional[str] = None
    broadcast_dynamic_attr: Optional[str] = None

    manager: WebSocketManager = global_ws_manager

    @classmethod
    async def handle_connection(cls, websocket: WebSocket):
        """Entry point for handling isolated WebSocket endpoint routes."""
        self = cls()
        token = websocket.query_params.get("token")
        client_addr = f"{getattr(websocket.client, 'host', '127.0.0.1')}:{getattr(websocket.client, 'port', 0)}"

        # Accept handshake immediately to upgrade protocol and avoid HTTP 403 response
        await websocket.accept()

        is_allowed = await self.authenticate_websocket(websocket, token)
        if not is_allowed:
            reason = "Credentials not provided" if not token else "Invalid or expired token"
            logger.warning(f"WebSocket connection rejected for \x1b[36m{client_addr}\x1b[0m - {reason}")
            await websocket.send_json({
                "status": "error",
                "message": reason,
                "code": 4001
            })
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason=reason
            )
            return

        conn_user = getattr(websocket.state, "user", None)
        user_identity = getattr(conn_user, "username", None) or getattr(conn_user, "id", "authenticated")
        logger.info(f"WebSocket connection authenticated for user \x1b[32m'{user_identity}'\x1b[0m (\x1b[36m{client_addr}\x1b[0m)")

        await self.manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_json()
                action = data.get("action")
                payload = data.get("payload", {})
                params = data.get("params", {})
                start_time = time.perf_counter()

                if not action:
                    logger.warning(f"WS Frame Error from \x1b[36m{client_addr}\x1b[0m: Missing 'action' field")
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

                    process_time = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        f"WS Action '\x1b[32m{action}\x1b[0m' executed successfully in \x1b[33m{process_time:.2f}ms\x1b[0m"
                    )

                    # Broadcast or respond back to sender
                    if self.auto_broadcast and action in self.broadcast_on_actions:
                        sender_to_skip = None if self.broadcast_self else websocket
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
                    logger.warning(f"WS Action '\x1b[31m{action}\x1b[0m' validation failed: {ve.error_count()} errors")
                    await self.manager.send_personal_message(
                        {"action": action, "status": "error", "errors": ve.errors()},
                        websocket
                    )
                except PermissionError as pe:
                    logger.warning(f"WS Action '\x1b[31m{action}\x1b[0m' permission denied: {pe}")
                    await self.manager.send_personal_message(
                        {"action": action, "status": "error", "message": str(pe)},
                        websocket
                    )
                except Exception as e:
                    logger.error(f"WS Action '\x1b[31m{action}\x1b[0m' failed with exception: {e}")
                    await self.manager.send_personal_message(
                        {"action": action, "status": "error", "message": str(e)},
                        websocket
                    )

        except WebSocketDisconnect:
            logger.info(f"WebSocket client \x1b[36m{client_addr}\x1b[0m disconnected")
            self.manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"Unexpected WS disconnect error for \x1b[36m{client_addr}\x1b[0m: {e}")
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
        perms = self.get_permissions("ws_connect")

        if not token:
            return len(perms) == 0

        user = await self.get_user_from_token(token)
        if not user and len(perms) > 0:
            return False

        websocket.state.user = user
        if not perms:
            return True

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
            logger.info(f"CRUD [\x1b[36mLIST\x1b[0m] Fetched {len(res.get('results', []))} records (Page {page})")
            return res

        # 2. CREATE / BULK CREATE
        elif action == "create":
            validated_payload = self._validate_input(payload, schema)
            if isinstance(validated_payload, list):
                if hasattr(self, "bulk_create_action"):
                    instances = await self.bulk_create_action(validated_payload, request=dummy_req)
                else:
                    instances = [await self.create_action(p, request=dummy_req) for p in validated_payload]
                serialized = [self._serialize(i, schema) for i in instances]
                logger.info(f"CRUD [\x1b[32mCREATE\x1b[0m] Bulk created {len(serialized)} records")
                return serialized

            instance = await self.create_action(validated_payload, request=dummy_req)
            serialized = self._serialize(instance, schema)
            record_id = serialized.get("id") or serialized.get("pk") or ""
            logger.info(f"CRUD [\x1b[32mCREATE\x1b[0m] Created record ID: \x1b[36m{record_id}\x1b[0m")
            return serialized

        elif action == "bulk_create":
            payload_list = payload if isinstance(payload, list) else [payload]
            validated_payloads = self._validate_input(payload_list, schema)
            if hasattr(self, "bulk_create_action"):
                instances = await self.bulk_create_action(validated_payloads, request=dummy_req)
            else:
                instances = [await self.create_action(p, request=dummy_req) for p in validated_payloads]
            serialized = [self._serialize(i, schema) for i in instances]
            logger.info(f"CRUD [\x1b[32mBULK_CREATE\x1b[0m] Created {len(serialized)} records")
            return serialized

        # 3. RETRIEVE
        elif action == "retrieve":
            lookup_field = getattr(self, "lookup_field", "id")
            lookup_data = payload if isinstance(payload, dict) else {lookup_field: payload}
            instance = await self.retrieve_action(lookup_data, request=dummy_req)
            serialized = self._serialize(instance, schema)
            logger.info(f"CRUD [\x1b[36mRETRIEVE\x1b[0m] Fetched record ID: \x1b[36m{lookup_data.get(lookup_field)}\x1b[0m")
            return serialized

        # 4. UPDATE / BULK UPDATE
        elif action == "update":
            lookup_field = getattr(self, "lookup_field", "id")
            if isinstance(payload, list):
                if hasattr(self, "bulk_update_action"):
                    instances = await self.bulk_update_action(payload, request=dummy_req)
                    serialized = [self._serialize(i, schema) for i in instances]
                    logger.info(f"CRUD [\x1b[33mUPDATE\x1b[0m] Bulk updated {len(serialized)} records")
                    return serialized

            lookup_data = payload.get("lookup", {lookup_field: payload.get(lookup_field)}) if isinstance(payload, dict) else {lookup_field: payload}
            update_data = payload.get("data", payload) if isinstance(payload, dict) else {}
            validated_update = self._validate_input(update_data, schema)
            
            instance = await self.update_action(lookup_data, validated_update, request=dummy_req)
            serialized = self._serialize(instance, schema)
            logger.info(f"CRUD [\x1b[33mUPDATE\x1b[0m] Updated record ID: \x1b[36m{lookup_data.get(lookup_field)}\x1b[0m")
            return serialized

        elif action == "bulk_update":
            payload_list = payload if isinstance(payload, list) else [payload]
            if hasattr(self, "bulk_update_action"):
                instances = await self.bulk_update_action(payload_list, request=dummy_req)
                serialized = [self._serialize(i, schema) for i in instances]
                logger.info(f"CRUD [\x1b[33mBULK_UPDATE\x1b[0m] Updated {len(serialized)} records")
                return serialized

        # 5. DESTROY / BULK DESTROY
        elif action == "destroy":
            if isinstance(payload, dict) and "keys" in payload:
                bulk_schema = BulkDeleteSchema(keys=payload["keys"])
                res = await self.bulk_destroy_action(bulk_schema, request=dummy_req)
                logger.info(f"CRUD [\x1b[31mDESTROY\x1b[0m] Bulk deleted keys: {payload['keys']}")
                return res

            lookup_field = getattr(self, "lookup_field", "id")
            lookup_data = payload if isinstance(payload, dict) else {lookup_field: payload}
            success = await self.destroy_action(lookup_data, request=dummy_req)
            logger.info(f"CRUD [\x1b[31mDESTROY\x1b[0m] Deleted record ID: \x1b[36m{lookup_data.get(lookup_field)}\x1b[0m")
            return {"detail": "Deleted successfully", "success": success}

        elif action == "bulk_destroy":
            keys = payload.get("keys", payload) if isinstance(payload, dict) else payload
            bulk_schema = BulkDeleteSchema(keys=keys)
            res = await self.bulk_destroy_action(bulk_schema, request=dummy_req)
            logger.info(f"CRUD [\x1b[31mBULK_DESTROY\x1b[0m] Deleted keys: {keys}")
            return res

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
        client_addr = f"{getattr(websocket.client, 'host', '127.0.0.1')}:{getattr(websocket.client, 'port', 0)}"

        if not self.viewset_map:
            logger.error("Multiplexer connection rejected: No viewsets registered")
            await websocket.accept()
            await websocket.close(code=status.WS_1011_UNEXPECTED_CONDITION, reason="No viewsets registered")
            return

        # Accept handshake immediately to avoid HTTP 403 response
        await websocket.accept()

        first_viewset_cls = next(iter(self.viewset_map.values()))
        auth_instance = first_viewset_cls()
        is_allowed = await auth_instance.authenticate_websocket(websocket, token)
        if not is_allowed:
            reason = "Credentials not provided" if not token else "Invalid or expired token"
            logger.warning(f"Multiplexer WS connection rejected for \x1b[36m{client_addr}\x1b[0m - {reason}")
            await websocket.send_json({
                "status": "error",
                "message": reason,
                "code": 4001
            })
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason=reason
            )
            return

        conn_user = getattr(websocket.state, "user", None)
        user_identity = getattr(conn_user, "username", None) or getattr(conn_user, "id", "authenticated")
        logger.info(f"Multiplexer WS connection authenticated for user \x1b[32m'{user_identity}'\x1b[0m (\x1b[36m{client_addr}\x1b[0m)")

        await self.manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_json()
                target_viewset_key = data.get("viewset")
                action = data.get("action")
                payload = data.get("payload", {})
                params = data.get("params", {})
                start_time = time.perf_counter()

                if not target_viewset_key or target_viewset_key not in self.viewset_map:
                    logger.warning(f"Multiplexer Frame Error from \x1b[36m{client_addr}\x1b[0m: Invalid or missing viewset '{target_viewset_key}'")
                    await self.manager.send_personal_message(
                        {
                            "status": "error", 
                            "message": f"Invalid or missing 'viewset' target. Available: {list(self.viewset_map.keys())}"
                        },
                        websocket
                    )
                    continue

                if not action:
                    logger.warning(f"Multiplexer Frame Error from \x1b[36m{client_addr}\x1b[0m: Missing 'action' field")
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

                    process_time = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        f"Multiplexer [\x1b[36m{target_viewset_key}\x1b[0m] Action '\x1b[32m{action}\x1b[0m' executed in \x1b[33m{process_time:.2f}ms\x1b[0m"
                    )

                    # Handle targeted auto-broadcasting
                    if viewset_instance.auto_broadcast and action in viewset_instance.broadcast_on_actions:
                        sender_to_skip = None if viewset_instance.broadcast_self else websocket
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
                    logger.warning(f"Multiplexer [\x1b[36m{target_viewset_key}\x1b[0m] Action '\x1b[31m{action}\x1b[0m' validation failed")
                    await self.manager.send_personal_message(
                        {
                            "viewset": target_viewset_key,
                            "action": action, 
                            "status": "error", 
                            "errors": ve.errors()
                        },
                        websocket
                    )
                except PermissionError as pe:
                    logger.warning(f"Multiplexer [\x1b[36m{target_viewset_key}\x1b[0m] Action '\x1b[31m{action}\x1b[0m' permission denied: {pe}")
                    await self.manager.send_personal_message(
                        {
                            "viewset": target_viewset_key,
                            "action": action, 
                            "status": "error", 
                            "message": str(pe)
                        },
                        websocket
                    )
                except Exception as e:
                    logger.error(f"Multiplexer [\x1b[36m{target_viewset_key}\x1b[0m] Action '\x1b[31m{action}\x1b[0m' failed: {e}")
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
            logger.info(f"Multiplexer client \x1b[36m{client_addr}\x1b[0m disconnected")
            self.manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"Unexpected Multiplexer disconnect error for \x1b[36m{client_addr}\x1b[0m: {e}")
            self.manager.disconnect(websocket)