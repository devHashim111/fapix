# HTTP ViewSets & Routing

```

Fapix features **DRF-style `ModelViewSet` classes**, dynamic `DefaultRouter`, fine-grained permissions, and `@action` decorators.

---

## 1. Defining Models & ViewSets

### `apps/product/models.py`

```python
from tortoise import fields
from tortoise.models import Model


class Product(Model):
    id = fields.UUIDField(pk=True)
    name = fields.CharField(max_length=100)
    slug = fields.CharField(max_length=100, unique=True)
    description = fields.TextField(null=True)
    price = fields.DecimalField(max_digits=10, decimal_places=2)
    stock = fields.IntField(default=0)
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "products"

```

### `apps/product/views.py`

```python
from fapix.views import ModelViewSet
from apps.auth.permissions import IsSuperUser, IsSuperUserOrRole
from .models import Product
from .schemas import (
    ProductSchema,
    ProductCreateSchema,
    ProductUpdateSchema,
    ProductRetrieveSchema,
)


class ProductViewSet(ModelViewSet):
    model = Product
    schema = ProductSchema  # Default response schema

    # Dynamic action schemas
    action_schemas = {
        "create": ProductCreateSchema,
        "update": ProductUpdateSchema,
        "retrieve": ProductRetrieveSchema,
        "bulk_create": ProductCreateSchema,
    }
    lookup_fields = ["slug"]

    # Action-level permissions
    permission_classes = []  # Public read access
    action_permissions = {
        "create": [IsSuperUserOrRole("admin")],
        "update": [IsSuperUser],
        "destroy": [IsSuperUser],
        "bulk_create": [IsSuperUser],
        "bulk_delete": [IsSuperUser],
    }

    # Filtering, Searching, & Ordering
    search_fields = ["name", "description"]
    filterset_fields = ["is_active", "stock"]
    ordering_fields = ["price", "id", "stock"]
    default_ordering = ["-price"]

```

---

## 2. Function-Based Views & Decorators

```python
from fastapi import FastAPI, Depends
from fapix.decorators import permission_classes, api_view
from apps.auth.permissions import IsAuthenticated


# Decorator approach
@api_view
@permission_classes([IsAuthenticated])
async def home():
    return {"message": "Welcome Home"}


# Dependency Injection approach
async def profile(current_user=Depends(IsAuthenticated())):
    return {"user": current_user}

```

---

## 3. URL Registration & `DefaultRouter`

### `apps/product/urls.py`

```python
from fastapi import APIRouter
from fapix.core.router import register_urlpatterns
from fapix.router import DefaultRouter
from . import views

router = APIRouter(prefix="/products", tags=["products"])

# 1. Initialize DefaultRouter and register ViewSets
product_router = DefaultRouter()
product_router.register("", views.ProductViewSet, basename="product")

# 2. Define custom/manual endpoints
urlpatterns = []

# 3. Extend with generated ViewSet pattern definitions
urlpatterns.extend(product_router.generate_urlpatterns())

# 4. Attach pattern definitions onto router instance
register_urlpatterns(router, urlpatterns)

```
