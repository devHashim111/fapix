from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@router.get("/", include_in_schema=False)
async def fapix_homepage():
    return HTMLResponse(
        content=(_TEMPLATES_DIR / "fapix.html").read_text(encoding="utf-8")
    )


@router.get("/tester", include_in_schema=False)
async def fapix_tester():
    return HTMLResponse(
        content=(_TEMPLATES_DIR / "tester.html").read_text(encoding="utf-8")
    )