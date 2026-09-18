# Declarative WebSocket ViewSets

```

`fapix.viewsets.websocket` brings RESTful structure to real-time WebSockets via `WebSocketApiView` (for custom non-DB actions) and `WebSocketModelViewSet` (for ORM-backed models).

---

## 1. Interactive Testing with Built-In Tester

Fapix provides an interactive WebSocket tester directly in your browser:

```text
http://localhost:8000/tester

```

You can test connection handshakes, JWT query parameter authentication, action routing, and inspect inbound/outbound real-time JSON frames.

---

## 2. Routing in `urls.py`

```python
from fastapi import APIRouter, WebSocket
from .views import RealtimeChatWebSocketView, ProductWebSocketViewSet

router = APIRouter()

# Non-DB Custom Action Endpoint
@router.websocket("/ws/chat/realtime/")
async def realtime_chat_websocket_endpoint(websocket: WebSocket):
    await RealtimeChatWebSocketView.handle_connection(websocket)

# DB-backed Model ViewSet Endpoint
@router.websocket("/ws/products/")
async def products_websocket_endpoint(websocket: WebSocket):
    await ProductWebSocketViewSet.handle_connection(websocket)

```

---

## 3. Implementation Example

```python
from fapix.viewsets.websocket import WebSocketApiView, WebSocketModelViewSet, BroadcastScope
from apps.auth.permissions import IsAuthenticated
from .models import Product
from .schemas import InboundChatMessageSchema, ProductSchema


# Non-DB Custom View
class RealtimeChatWebSocketView(WebSocketApiView):
    action_schemas = {"send_message": InboundChatMessageSchema}
    permission_classes = []
    action_permissions = {"send_message": [IsAuthenticated]}
    auto_broadcast = False
    broadcast_scope = BroadcastScope.GLOBAL

    async def action_send_message(self, payload: dict, params: dict = None):
        outbound_data = {
            "room_id": payload.get("room_id"),
            "text": payload.get("text", ""),
        }
        await self.manager.broadcast(
            message={"action": "new_message", "status": "success", "data": outbound_data},
            scope=self.broadcast_scope,
        )
        return outbound_data


# DB-backed Model ViewSet
class ProductWebSocketViewSet(WebSocketModelViewSet):
    model = Product
    schema = ProductSchema
    auto_broadcast = True
    broadcast_self = True
    broadcast_scope = BroadcastScope.GLOBAL

```

---

## 4. Method Overrides & Custom Hooks

```python
class CustomWebSocketView(WebSocketApiView):
    async def authenticate_websocket(self, websocket: WebSocket):
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="Unauthorized")
            return None
        user = await verify_jwt_token(token)
        websocket.state.user = user
        return user

    async def on_connect(self, websocket: WebSocket):
        print(f"Client connected: {websocket.client}")

    async def on_disconnect(self, websocket: WebSocket, close_code: int):
        print(f"Client disconnected with code {close_code}")

```
