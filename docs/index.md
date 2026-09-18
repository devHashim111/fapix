# Fapix

**Fapix** is a high-productivity, **Django-inspired** web framework built on top of **FastAPI**, **Tortoise-ORM**, and **Typer**.

It brings the modular structure, built-in CLI automation, and seamless migration workflows of Django into the modern, asynchronous Python ecosystem.

---

## 🚀 Key Features

* **Django-Style App Architecture:** Modular project layout using `apps/` with automatic model discovery and router registration.
* **DRF-Style ViewSets & Routers:** Declarative `ModelViewSet` classes, dynamic `DefaultRouter`, fine-grained permissions, and custom `@action` decorators.
* **Declarative WebSockets:** Non-DB custom action views (`WebSocketApiView`) and ORM-backed real-time viewsets (`WebSocketModelViewSet`).
* **Built-in Authentication:** Out-of-the-box user models, routes, and CLI user management.
* **Smart Database Migrations:** Powered by `aerich`, featuring automated model detection and self-healing migration fallbacks.
* **Built-in Interactive API Tester:** Integrated lightweight API and WebSocket tester hosted directly at `/tester`.

---

## 📦 Installation

Install Fapix directly from PyPI:

```bash
pip install fapix

```

Or install locally in editable mode for core development:

```bash
git clone https://github.com/devHashim111/fapix
cd fapix
pip install -e .

```

---

## 📖 Quick Start

```bash
# 1. Start a new project & navigate into it
fapix startproject myproject
cd myproject

# 2. Initialize built-in auth app & run migrations
fapix startapp auth
fapix makemigrations
fapix migrate

# 3. Start local development server
fapix runserver

```

Access the interactive API & WebSocket tester at `http://localhost:8000/tester`.

---

## 📚 Documentation Index

Explore detailed documentation sections inside the [`docs/`] folder:

* 🛠️ **[CLI & Database Migrations]:** Project creation, user management commands, and migration workflows.
* 🌐 **[HTTP ViewSets & Routing]:** DRF-parity `ModelViewSet`, `DefaultRouter`, function views, and permission setup.
* ⚡ **[WebSocket ViewSets]:** `WebSocketApiView`, `WebSocketModelViewSet`, frame routing, custom handlers, and method overrides.
* 🔐 **[Authentication & Permissions]:** Built-in user models, CLI user creation, JWT authentication, and permission classes.

---

## 📄 License

Distributed under the **MIT License**.
