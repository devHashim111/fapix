import shutil
from pathlib import Path

import typer

from . import boilerplate

app = typer.Typer()


def snake_case(name: str) -> str:
    return name.lower().replace(" ", "_")


def get_builtin_apps_path() -> Path:
    current_file = Path(__file__).resolve()
    return current_file.parents[3] / "apps"


def find_project_root() -> Path | None:
    current = Path.cwd().resolve()

    while True:
        if (current / "main.py").is_file() and (current / "apps").is_dir():
            return current
        if current == current.parent:
            return None
        current = current.parent


def require_project_root() -> Path:
    project_root = find_project_root()

    if project_root is None:
        typer.secho("No Fapix project found.", fg=typer.colors.RED, bold=True)
        typer.secho("Run this command inside a Fapix project.", fg=typer.colors.YELLOW)
        typer.echo("Create one with: fapix startproject <project-name>")
        raise typer.Exit(code=1)

    return project_root


def add_router_to_main(main_router: Path, app_name: str):
    if not main_router.exists():
        typer.secho(f"router.py not found at {main_router}", fg=typer.colors.YELLOW)
        return

    content = main_router.read_text(encoding="utf-8")

    import_line = f"from apps.{app_name}.urls import router as {app_name}_router"
    include_line = f"router.include_router({app_name}_router)"

    changed = False

    if import_line not in content:
        lines = content.splitlines()
        last_import_index = -1

        for index, line in enumerate(lines):
            if line.strip().startswith(("import ", "from ")):
                last_import_index = index

        insert_at = last_import_index + 1 if last_import_index >= 0 else 0
        lines.insert(insert_at, import_line)
        content = "\n".join(lines)
        changed = True

    if include_line not in content:
        lines = content.splitlines()
        app_creation_index = -1

        for index, line in enumerate(lines):
            if "FastAPI(" in line:
                app_creation_index = index

        if app_creation_index >= 0:
            lines.insert(app_creation_index + 1, "")
            lines.insert(app_creation_index + 2, include_line)
            content = "\n".join(lines)
        else:
            content += f"\n\n{include_line}\n"

        changed = True

    if changed:
        main_router.write_text(content.rstrip() + "\n", encoding="utf-8")
        typer.secho(f"Router '{app_name}' registered", fg=typer.colors.GREEN)
    else:
        typer.secho(f"Router '{app_name}' already registered", fg=typer.colors.BLUE)


def print_auth_message():
    typer.echo()
    typer.secho("Auth app installed.", fg=typer.colors.CYAN, bold=True)
    typer.echo("Create users with:")
    typer.secho("    fapix createuser", fg=typer.colors.GREEN)
    typer.secho("    fapix createsuperuser", fg=typer.colors.GREEN)
    typer.echo("The auth router has been registered in router.py.")


def create_normal_app(app_path: Path, app_name: str):
    typer.echo(f"Creating app '{app_name}'...")

    app_path.mkdir(parents=True, exist_ok=True)

    files = {
        "__init__.py": boilerplate.INIT_TEMPLATE,
        "models.py": boilerplate.MODELS_TEMPLATE,
        "schemas.py": boilerplate.SCHEMAS_TEMPLATE,
        "views.py": boilerplate.VIEWS_TEMPLATE,
        "config.py": boilerplate.CONFIG_TEMPLATE,
    }

    for filename, content in files.items():
        (app_path / filename).write_text(content, encoding="utf-8")

    (app_path / "urls.py").write_text(
        boilerplate.urls_template(app_name),
        encoding="utf-8",
    )

    typer.secho(f"App '{app_name}' created", fg=typer.colors.GREEN)


def install_builtin_app(builtin_app_path: Path, app_path: Path, app_name: str):
    typer.echo(f"Installing built-in app '{app_name}'...")

    app_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(builtin_app_path, app_path)

    # typer.secho(f"Built-in app '{app_name}' installed", fg=typer.colors.GREEN)


@app.command()
def startapp_cmd(
    names: list[str] = typer.Argument(..., help="One or more app names"),
    path: str = typer.Option("apps", "--path", "-p", help="Directory where apps should be created"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Prompt for input interactively"),
):
    """Create one or more new apps."""

    project_root = require_project_root()

    if interactive:
        names = typer.prompt("Enter app names separated by spaces").split()
        path = typer.prompt("Enter base path", default=path)

    if not names:
        typer.secho("At least one app name is required.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    main_router = project_root / "router.py"
    builtin_apps_path = get_builtin_apps_path()
    apps_root = (project_root / path).resolve()

    if apps_root != project_root and project_root not in apps_root.parents:
        typer.secho("App path cannot be outside the Fapix project.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    created_apps = []

    for name in names:
        app_name = snake_case(name)
        app_path = apps_root / app_name
        builtin_app_path = builtin_apps_path / app_name

        try:
            if app_path.exists():
                typer.secho(f"App '{app_name}' already exists at {app_path}", fg=typer.colors.YELLOW)
                continue

            if builtin_app_path.exists():
                install_builtin_app(builtin_app_path, app_path, app_name)
            else:
                create_normal_app(app_path, app_name)

            add_router_to_main(main_router, app_name)
            created_apps.append(app_name)

        except Exception as e:
            if app_path.exists():
                shutil.rmtree(app_path, ignore_errors=True)
            typer.secho(f"Error creating '{app_name}': {e}", fg=typer.colors.RED)

    if created_apps:
        typer.echo()
        typer.secho("Created apps:", fg=typer.colors.GREEN, bold=True)
        for app_name in created_apps:
            typer.echo(f"  {app_name}")
    else:
        typer.secho("No new apps were created.", fg=typer.colors.YELLOW)

    if "auth" in created_apps:
        print_auth_message()