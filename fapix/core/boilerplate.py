DJANGO_LIKE_VIEWS = '''from fastapi import APIRouter, Request
from . import views
from .urls import urlpatterns

router = APIRouter()

for route in urlpatterns:
    router.add_api_route(
        route["path"],
        route["view"],
        methods=[route["method"]],
        name=route["name"]
    )
'''

URLS_TEMPLATE = '''from . import views

urlpatterns = [
    {
        "path": "/home/",
        "view": views.home,
        "name": "home",
        "method": "GET"
    },
]
'''

VIEWS_TEMPLATE = '''from fastapi import Request

async def home(request: Request):
    return {"message": "Hello from the app!"}
'''

CONFIG_TEMPLATE = '''# App-specific config
'''

INIT_TEMPLATE = '''# Init file for app
'''

