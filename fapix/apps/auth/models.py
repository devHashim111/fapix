import uuid
from enum import Enum
from tortoise import fields, models


class UserRole(str, Enum):
    USER = "user"
    SUPERUSER = "superuser"
    ADMIN = "admin"


class User(models.Model):
    """
    Default reusable user model.
    """

    id = fields.UUIDField(
        pk=True,
        default=uuid.uuid4,
    )

    email = fields.CharField(
        max_length=255,
        unique=True,
    )

    username = fields.CharField(
        max_length=150,
        unique=True,
        null=True,
    )

    hashed_password = fields.CharField(
        max_length=255,
    )

    is_active = fields.BooleanField(
        default=True,
    )

    is_verified = fields.BooleanField(
        default=False,
    )

    role = fields.CharField(
        max_length=50,
        default=UserRole.USER,
    )

    created_at = fields.DatetimeField(
        auto_now_add=True,
    )

    updated_at = fields.DatetimeField(
        auto_now=True,
    )

    class Meta:
        table = "auth_users"

    def __str__(self):
        return self.email