```markdown
#  Fapix

**Fapix** is a high-productivity, **Django-inspired** web framework built on top of **FastAPI**, **Tortoise-ORM**, and **Typer**.

It brings the modular structure, built-in CLI automation, and seamless migration workflows of Django into the modern, asynchronous, and lightning-fast Python ecosystem.

---

##  Key Features

* **Django-Style App Architecture:** Modular project layout using `apps/` with automatic model discovery and router registration.
* **DRF-Style ViewSets & Routers:** Declarative `ModelViewSet` classes, dynamic `DefaultRouter`, fine-grained permissions, and custom `@action` decorators located in `fapix.views` and `fapix.decorators`.
* **Built-in Authentication:** Out-of-the-box user models, routes, and CLI user creation tools generated instantly via `fapix startapp auth`.
* **Smart Database Migrations:** Powered by `aerich`, featuring automated model detection, missing migration fallbacks, and single-command upgrades.
* **Built-in Interactive API Tester:** Integrated lightweight API tester (Postman alternative) and WebSocket tester hosted directly at `/tester`.
* **Built-in CLI Automation:** Manage projects, user authentication, migrations, and servers using the `fapix` command-line utility.

---

## 🛠️ Installation

### **Prerequisites**
* **Python:** `3.10+`
* **Database:** SQLite *(Default for development)* or PostgreSQL

---

### **Local Setup**

1. **Clone the repository:**
   ```bash
   git clone https://github.com/devHashim111/fapix
   cd fapix

```

2. **Create and activate a virtual environment:**
```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
py -m venv venv
venv\Scripts\activate

```


3. **Install dependencies in editable mode:**
```bash
pip install -e .

```


4. **Verify CLI installation:**
```bash
fapix --help

```



---

## 📖 Quickstart Guide

### 1️⃣ **Create a New Project**

Initialize a pre-configured project structure using the Fapix CLI:

```bash
fapix startproject myproject
cd myproject

```

#### **Generated Directory Structure**

```text
myproject/
├── main.py            # Application entrypoint & router initialization
├── db_config.py       # Tortoise-ORM configuration & model registry
├── pyproject.toml     # Project metadata & Aerich configuration
└── apps/              # Business logic modules
    └── auth/          # Default otpional auth application 

```

---

### 2️⃣ **Setup Built-in Authentication App**

Fapix provides a fully pre-built authentication module out of the box (including user models, password hashing, and authentication endpoints). Generate it with:

```bash
fapix startapp auth

```

Since the `auth` app comes with built-in models, run database migrations immediately to initialize the user tables:

```bash
fapix makemigrations
fapix migrate

```

---

### 3️⃣ **User & Superuser Management**

Manage users directly from your terminal using Fapix CLI commands:

#### **Create a Standard User:**

```bash
fapix createuser

```

#### **Create a Superuser (Admin):**

```bash
fapix createsuperuser

```

---

### 4️⃣ **Creating Custom Apps, ViewSets & Routers**

Fapix features **DRF-style `ModelViewSet` classes** in `fapix.views` along with permission handlers and `@action` decorators in `fapix.decorators`.

Generate a custom app (e.g., `product`):

```bash
fapix startapp product

```

#### **Defined Model (`apps/product/models.py`)**

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

#### **Defined ViewSet with DRF Parity (`apps/product/views.py`)**

```python
from fapix.views import ModelViewSet
from fapix.permissions import IsSuperUser, IsSuperUserOrRole
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
    permission_classes = []  # Public read access (list, retrieve)
    action_permissions = {
        "create": [IsSuperUserOrRole("admin")],
        "update": [IsSuperUser],
        "destroy": [IsSuperUser],
        "bulk_create": [IsSuperUser],
        "bulk_delete": [IsSuperUser],
    }

    # Filtering, Searching, & Ordering Configuration
    search_fields = ["name", "description"]
    filterset_fields = ["is_active", "stock"]
    ordering_fields = ["price", "id", "stock"]
    default_ordering = ["-price"]

```

#### **URL Registration & DefaultRouter (`apps/product/urls.py`)**

```python
from fastapi import APIRouter
from fapix.core.router import register_urlpatterns
from fapix.router import DefaultRouter
from . import views

router = APIRouter(prefix="/products", tags=["products"])

# 1. Initialize DefaultRouter and register ViewSets
product_router = DefaultRouter()

product_router.register("", views.ProductViewSet, basename="product")
product_router.register("items", views.ProductWebSocketViewSet, basename="product-ws")

# 2. Combine auto-generated router urlpatterns with explicit endpoints
urlpatterns = [
    # Custom / Manual views
]

# 3. Extend with automatically generated ViewSet patterns
urlpatterns.extend(product_router.generate_urlpatterns())

# 4. Register patterns onto router
register_urlpatterns(router, urlpatterns)

```

---

### 5️⃣ **Run Custom Migrations**

After defining or modifying Tortoise models in custom apps (like `product`), generate and apply migrations:

```bash
fapix makemigrations
fapix migrate

```

*To target a specific app:*

```bash
fapix makemigrations product

```

> 📌 **Self-Healing Engine:** If database tables or migration directories are uninitialized, `fapix migrate` automatically initializes database configurations and syncs missing files before applying schema upgrades.

---

### 6️⃣ **Run the Development Server**

Start the application server using default settings or custom parameters:

#### **Default Execution (Port 8000):**

```bash
fapix runserver

```

#### **Custom Port & Log Level:**

```bash
fapix runserver 9000 --log-level info

```

---

### 7️⃣ **Interactive API & WebSocket Tester**

Fapix ships with a built-in GUI client (a lightweight alternative to Postman) and an integrated WebSocket tester to exercise generated endpoints.

Access the tools in your browser:

* 🧪 **Interactive Tester (Postman-style UI & WebSockets):** `http://localhost:8000/tester`
* 🌐 **Swagger UI:** `http://localhost:8000/docs`
* 🌐 **ReDoc:** `http://localhost:8000/redoc`

*(Note: Replace `8000` with your custom port if configured, e.g., `http://localhost:9000/tester`).*

---

## 📄 License

Distributed under the **MIT License**.

```

```