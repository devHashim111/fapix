from enum import Enum

from typing import Any, Dict, List, Optional, Type, Union, Callable, Set
from fastapi import WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

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
    USER = "user"                   # Sockets matching the same authenticated user ID


class WebSocketManager:
    """Standalone/Reusable Manager with targeted Broadcast Scopes."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

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
        target_user_id: Optional[Any] = None
    ):
        dead_connections: Set[WebSocket] = set()

        # Iterate over a snapshot copy to prevent concurrent modification issues
        for connection in list(self.active_connections):
            if sender and connection == sender:
                continue

            conn_user = getattr(connection.state, "user", None)

            # Check broadcast scopes safely
            if scope == BroadcastScope.AUTHENTICATED and not conn_user:
                continue
            
            if scope == BroadcastScope.USER:
                if not conn_user:
                    continue
                conn_user_id = getattr(conn_user, "id", None) or getattr(conn_user, "pk", None)
                if str(conn_user_id) != str(target_user_id):
                    continue

            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        # Cleanup unreachable sockets after loop iteration finishes
        for dead in dead_connections:
            self.disconnect(dead)


class WebSocketApiView(BaseViewSet):
    """Declarative WebSocket ViewSet with configuration flags & broadcast scope handling."""
    
    # Declarative Configuration Flags
    auto_broadcast: bool = False
    broadcast_self: bool = True
    broadcast_scope: BroadcastScope = BroadcastScope.GLOBAL
    broadcast_on_actions: List[str] = ["create", "update", "destroy", "bulk_create", "bulk_update", "bulk_destroy"]
    
    manager: WebSocketManager = WebSocketManager()

    @classmethod
    async def handle_connection(cls, websocket: WebSocket):
        self = cls()
        token = websocket.query_params.get("token")

        if self.permission_classes:
            is_allowed = await self.authenticate_websocket(websocket, token)
            if not is_allowed:
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
                params = data.get("params", {})  # For searching, sorting, filtering & pagination

                if not action:
                    await self.manager.send_personal_message(
                        {"status": "error", "message": "Missing 'action' field in WS frame"},
                        websocket
                    )
                    continue

                try:
                    response = await self.dispatch_ws_action(websocket, action, payload, params)

                    # Broadcast logic based on configuration flags
                    if self.auto_broadcast and action in self.broadcast_on_actions:
                        sender_to_skip = None if self.broadcast_self else websocket
                        conn_user = getattr(getattr(websocket, "state", None), "user", None)
                        user_id = getattr(conn_user, "id", None) if conn_user else None
                        
                        await self.manager.broadcast(
                            {"action": action, "data": response, "status": "success"},
                            sender=sender_to_skip,
                            scope=self.broadcast_scope,
                            target_user_id=user_id
                        )
                    else:
                        await self.manager.send_personal_message(
                            {"action": action, "data": response, "status": "success"},
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
        if not token:
            return False
        user = await self.get_user_from_token(token)
        if not user:
            return False

        websocket.state.user = user
        perms = self.get_permissions("ws_connect")
        for perm_cls in perms:
            perm = perm_cls() if isinstance(perm_cls, type) else perm_cls
            if hasattr(perm, "has_permission") and not await perm.has_permission(user):
                return False

        return True

    async def get_user_from_token(self, token: str) -> Optional[Any]:
        """Resolves active user instance."""
        try:
            from apps.auth.views import decode_token
            from apps.auth.models import User
            
            payload = decode_token(token)
            if payload.get("type") != "access":
                return None
            
            user_id = payload.get("sub")
            if not user_id:
                return None
                
            return await User.filter(id=user_id, is_active=True).first()
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
        if not schema or not instance:
            return instance
        if isinstance(instance, dict):
            return instance
        return schema.model_validate(instance, from_attributes=True).model_dump()

    async def dispatch_ws_action(
        self, 
        websocket: WebSocket, 
        action: str, 
        payload: Union[Dict[str, Any], List[Dict[str, Any]]],
        params: Optional[Dict[str, Any]] = None
    ):
        schema = self.get_schema(action)
        params = params or {}

        # 1. LIST ACTION (Paginated envelope response)
        if action == "list":
            search = params.get("search")
            ordering = params.get("ordering")
            page = int(params.get("page", 1))
            page_size = int(params.get("page_size", self.page_size))
            
            # Remove pagination/control keys before passing remaining params as field filters
            extra_filters = {
                k: v for k, v in params.items() 
                if k not in ["search", "ordering", "page", "page_size"]
            }

            res = await self.list_action(
                search=search, 
                ordering=ordering, 
                page=page, 
                page_size=page_size, 
                **extra_filters
            )

            # Serialize paginated results
            if schema and isinstance(res, dict) and "results" in res:
                res["results"] = [self._serialize(item, schema) for item in res["results"]]
            return res

        # 2. CREATE / BULK CREATE
        elif action == "create":
            if isinstance(payload, list):
                instances = await self.bulk_create_action(payload)
                return [self._serialize(i, schema) for i in instances]
            
            instance = await self.create_action(payload)
            return self._serialize(instance, schema)

        elif action == "bulk_create":
            payload_list = payload if isinstance(payload, list) else [payload]
            instances = await self.bulk_create_action(payload_list)
            return [self._serialize(i, schema) for i in instances]

        # 3. RETRIEVE
        elif action == "retrieve":
            lookup_data = payload if isinstance(payload, dict) else {self.lookup_field: payload}
            instance = await self.retrieve_action(lookup_data)
            return self._serialize(instance, schema)

        # 4. UPDATE / BULK UPDATE
        elif action == "update":
            if isinstance(payload, list):
                instances = await self.bulk_update_action(payload)
                return [self._serialize(i, schema) for i in instances]

            lookup_data = payload.get("lookup", {self.lookup_field: payload.get(self.lookup_field)}) if isinstance(payload, dict) else {self.lookup_field: payload}
            update_data = payload.get("data", payload) if isinstance(payload, dict) else {}
            instance = await self.update_action(lookup_data, update_data)
            return self._serialize(instance, schema)

        elif action == "bulk_update":
            payload_list = payload if isinstance(payload, list) else [payload]
            instances = await self.bulk_update_action(payload_list)
            return [self._serialize(i, schema) for i in instances]

        # 5. DESTROY / BULK DESTROY
        elif action == "destroy":
            if isinstance(payload, dict) and "keys" in payload:
                bulk_schema = BulkDeleteSchema(keys=payload["keys"])
                return await self.bulk_destroy_action(bulk_schema)

            lookup_data = payload if isinstance(payload, dict) else {self.lookup_field: payload}
            success = await self.destroy_action(lookup_data)
            return {"success": success, "lookup": lookup_data}

        elif action == "bulk_destroy":
            keys = payload.get("keys", payload) if isinstance(payload, dict) else payload
            bulk_schema = BulkDeleteSchema(keys=keys if isinstance(keys, list) else [keys])
            return await self.bulk_destroy_action(bulk_schema)

        # Fallback to base dispatch
        return await super().dispatch_ws_action(websocket, action, payload, params)