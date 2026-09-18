# Authentication & User Management

```

Fapix includes a pre-built authentication module with user models, password hashing, and token handling out of the box.

---

## 1. Setup Auth Module

Initialize the auth app and run migrations:

```bash
fapix startapp auth
fapix makemigrations
fapix migrate

```

---

## 2. CLI User Management Commands

### Standard User Creation

```bash
fapix createuser

```

### Superuser (Admin) Creation

```bash
fapix createsuperuser

```

---

## 3. Permissions Reference

Import permission classes from `apps.auth.permissions`:

| Class | Description |
| --- | --- |
| `IsAuthenticated` | Requires a valid authenticated user session or token. |
| `IsSuperUser` | Restricts access exclusively to users with `is_superuser=True`. |
| `IsSuperUserOrRole(*roles)` | Allows access to superusers or users assigned specific role strings. |

```python
from apps.auth.permissions import IsAuthenticated, IsSuperUser, IsSuperUserOrRole

# Usage in ViewSets
permission_classes = [IsAuthenticated]
action_permissions = {
    "create": [IsSuperUserOrRole("admin", "vendor")],
    "destroy": [IsSuperUser],
}

```
