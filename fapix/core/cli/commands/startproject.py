from pathlib import Path

import typer


def startproject_cmd(
    project_name: str = typer.Argument(..., help="Project name"),
):
    """Create a new Fapix project structure."""

    root = Path(project_name)

    if root.exists():
        typer.secho(f"Project folder '{project_name}' already exists.", fg=typer.colors.RED)
        raise typer.Exit(1)

    root.mkdir(parents=True)

    apps_dir = root / "apps"
    apps_dir.mkdir()
    (apps_dir / "__init__.py").write_text("# Fapix applications\n", encoding="utf-8")

    _write_main(root)
    _write_router(root)
    # _write_gitignore(root)
    # _write_pyproject(root, project_name)

    _print_success(project_name)


def _write_main(root: Path) -> None:
    content = '''from fastapi import FastAPI

from router import router

app = FastAPI()
app.include_router(router)
'''
    (root / "main.py").write_text(content, encoding="utf-8")


def _write_router(root: Path) -> None:
    content = '''from importlib import import_module
from pathlib import Path

from fastapi import APIRouter

from fapix.core.homepage import router as _fapix_homepage_router

router = APIRouter()
router.include_router(_fapix_homepage_router)






'''
    (root / "router.py").write_text(content, encoding="utf-8")


def _write_gitignore(root: Path) -> None:
    content = '''__pycache__/
*.pyc
.venv/
.env
db.sqlite3
migrations/*
!migrations/__init__.py
'''
    (root / ".gitignore").write_text(content, encoding="utf-8")


def _write_pyproject(root: Path, project_name: str) -> None:
    content = f'''[project]
name = "{project_name}"
version = "0.1.0"
'''
    (root / "pyproject.toml").write_text(content, encoding="utf-8")


def _print_success(project_name: str) -> None:
    typer.echo()
    typer.secho(f"Project '{project_name}' created.", fg=typer.colors.GREEN, bold=True)
   
    typer.echo("Next steps:")
    typer.echo("    fapix startdb        configure the database")
    typer.echo("    fapix startapp <name>")
    typer.echo("    fapix runserver")


# def _discover_app_routers():
#     apps_dir = Path(__file__).resolve().parent / "apps"
#     routers = []

#     if not apps_dir.exists():
#         return routers

#     for app_dir in sorted(apps_dir.iterdir()):
#         if not app_dir.is_dir() or app_dir.name.startswith("_"):
#             continue

#         try:
#             module = import_module(f"apps.{app_dir.name}.urls")
#         except Exception as exc:
#             print(f"Failed to load router for '{app_dir.name}': {exc}")
#             continue

#         app_router = getattr(module, "router", None)

#         if app_router is not None:
#             routers.append(app_router)

# for _app_router in _discover_app_routers():
#     router.include_router(_app_router)