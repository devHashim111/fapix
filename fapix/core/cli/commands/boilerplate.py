# =========================================================
# DJANGO-LIKE VIEWS
# =========================================================

# ROUTER_TEMPLATE = '''from fastapi import APIRouter

# from .urls import urlpatterns


# router = APIRouter()


# for route in urlpatterns:

#     router.add_api_route(

#         route["path"],

#         route["view"],

#         methods=[
#             route.get(
#                 "method",
#                 "GET",
#             )
#         ],

#         name=route.get(
#             "name"
#         ),

#         response_model=route.get(
#             "response_model"
#         ),

#         response_class=route.get(
#             "response_class"
#         ),

#     )
# '''


# =========================================================
# URLS
# =========================================================
URLS_TEMPLATE = '''from . import views
from fastapi import APIRouter
from fapix.core.router import register_urlpatterns

router = APIRouter(prefix="/{app_name}", tags=["{app_name}"])

urlpatterns = [
    {{
        "path": "/",
        "view": views.home,
        "method": "GET",
        "name": "home",
    }},
]

register_urlpatterns(router, urlpatterns)
'''


def urls_template(app_name: str) -> str:
    return URLS_TEMPLATE.format(app_name=app_name)

# =========================================================
# VIEWS
# =========================================================

VIEWS_TEMPLATE = '''from fastapi import Request


async def home(
    request: Request,
):

    return {
        "message": "Hello from the Fapix!"
    }
'''


# =========================================================
# MODELS
# =========================================================

MODELS_TEMPLATE = '''from tortoise import fields
from tortoise.models import Model


# Add your Tortoise models here.
#
# Example:
#
# class Product(Model):
#
#     id = fields.IntField(
#         pk=True
#     )
#
#     name = fields.CharField(
#         max_length=255
#     )
#
#     class Meta:
#         table = "products"
'''


# =========================================================
# SCHEMAS
# =========================================================

SCHEMAS_TEMPLATE = '''from pydantic import BaseModel


# Add your Pydantic schemas here.
#
# Example:
#
# class ProductSchema(BaseModel):
#
#     name: str
#
#     price: float
'''


# =========================================================
# CONFIG
# =========================================================

CONFIG_TEMPLATE = '''# App-specific configuration
'''


# =========================================================
# INIT
# =========================================================

INIT_TEMPLATE = '''# Fapix application
'''