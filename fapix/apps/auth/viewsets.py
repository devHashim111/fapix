# In your viewsets/views.py

from fapix.viewsets.http import ModelViewSet
from .models import User
from .schemas import (
   
    UserRead,
    PasswordChangeSchema,
)
from .permissions import (
    IsAuthenticated,
    IsSuperUser,
)


class UserViewSet(ModelViewSet):
    model = User
    lookup_fields = ["id"]  # or any other unique identifier for your User model
    action_schemas = {
        "list": UserRead,        # Exposes hashed_password and all details
        
        "retrieve": UserRead,
        "update": PasswordChangeSchema,
    }

    action_permissions = {
        "list": [IsSuperUser],                  # No authentication check required
                     
        "retrieve": [IsAuthenticated],
        "update": [IsAuthenticated],
        "destroy": [IsSuperUser],
    }