import importlib.util
from pathlib import Path
import re
import subprocess
from typing import List, Optional
from rich import print
import typer

app = typer.Typer()


# ==========================================================
# PROJECT DETECTION
# ==========================================================


def find_project_root() -> Optional[Path]:
    """Find the Fapix project root containing main.py, apps/, and db_config.py."""
    current = Path.cwd().resolve()
    while True:
        if (
            (current / "main.py").is_file()
            and (current / "apps").is_dir()
            and (current / "db_config.py").is_file()
        ):
            return current
        if current == current.parent:
            break
        current = current.parent
    return None


def require_project_root() -> Path:
    project_root = find_project_root()
    if project_root is None:
        print("[bold red]❌ Error:[/bold red] Not inside a valid Fapix project.")
        print("[dim]Ensure main.py, db_config.py, and apps/ exist.[/dim]")
        raise typer.Exit(code=1)
    return project_root


# ==========================================================
# DISCOVER & REGISTER APPS
# ==========================================================


def discover_apps(project_root: Path) -> List[str]:
    """Discover installed apps with valid models.py file."""
    apps_dir = project_root / "apps"
    if not apps_dir.exists():
        return []

    apps = []
    for app_dir in sorted(apps_dir.iterdir()):
        if app_dir.is_dir() and not app_dir.name.startswith(("_", ".")):
            if (app_dir / "models.py").is_file():
                apps.append(app_dir.name)
    return apps


def sync_db_config_models(project_root: Path, apps: List[str]) -> None:
    """Dynamically register discovered apps' models in db_config.py TORTOISE_ORM."""
    config_path = project_root / "db_config.py"
    content = config_path.read_text(encoding="utf-8")

    expected_models = ["aerich.models"] + [f"apps.{app}.models" for app in apps]

    models_pattern = re.compile(
        r'("models"\s*:\s*\[)([^\]]*?)(\])', re.MULTILINE | re.DOTALL
    )

    match = models_pattern.search(content)
    if not match:
        print(
            "[yellow]⚠️ Could not locate 'models' array in db_config.py. Skipping auto-registration.[/yellow]"
        )
        return

    existing_raw = match.group(2)
    existing_models = re.findall(r'["\']([^"\']+)["\']', existing_raw)

    updated_models = list(dict.fromkeys(existing_models + expected_models))

    if set(existing_models) == set(updated_models):
        return

    formatted_models_str = "\n" + ",\n".join(
        f'                "{m}"' for m in updated_models
    ) + ",\n            "
    
    new_content = models_pattern.sub(
        rf"\1{formatted_models_str}\3", content, count=1
    )
    config_path.write_text(new_content, encoding="utf-8")
    print("[dim]🔧 Synchronized app models in db_config.py[/dim]")


def validate_requested_apps(
    requested_apps: List[str], available_apps: List[str]
) -> None:
    invalid_apps = [name for name in requested_apps if name not in available_apps]
    if invalid_apps:
        print(
            f"[bold red]❌ Unknown app(s):[/bold red] {', '.join(invalid_apps)}"
        )
        print(
            f"[dim]Available apps: {', '.join(available_apps)}[/dim]"
        )
        raise typer.Exit(code=1)


# ==========================================================
# AERICH INITIALIZATION & MIGRATIONS
# ==========================================================


def ensure_aerich_initialized(project_root: Path) -> None:
    """Initialize Aerich config and run init-db if no initial migrations exist."""
    pyproject = project_root / "pyproject.toml"
    migrations_models_dir = project_root / "migrations" / "models"

    # 1. Ensure aerich config exists in pyproject.toml
    if not pyproject.exists() or "tool.aerich" not in pyproject.read_text(encoding="utf-8"):
        print("[cyan] Initializing Aerich config...[/cyan]")
        result = subprocess.run(
            ["aerich", "init", "-t", "db_config.TORTOISE_ORM"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[bold red]❌ Failed to initialize Aerich:[/bold red]\n[dim]{result.stderr}[/dim]")
            raise typer.Exit(code=1)

    # 2. Check if initial migration file exists inside migrations/models/
    has_initial_migration = False
    if migrations_models_dir.exists():
        has_initial_migration = any(
            f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
            for f in migrations_models_dir.iterdir()
        )

    # 3. If no initial migration exists, force aerich init-db
    if not has_initial_migration:
        print("[cyan] Initializing database schema (aerich init-db)...[/cyan]")
        result = subprocess.run(
            ["aerich", "init-db"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Ignore "already initialized" errors if aerich raises it
            if "already initialized" not in result.stderr.lower() and "already exists" not in result.stderr.lower():
                print(f"[bold red]❌ Aerich init-db failed:[/bold red]\n[dim]{result.stderr or result.stdout}[/dim]")
                raise typer.Exit(code=1)
        
        print("[green]✓ Initial migration created.[/green]")


def run_aerich_migrate(project_root: Path) -> None:
    """Execute aerich migrate and catch uninitialized DB edge cases."""
    result = subprocess.run(
        ["aerich", "migrate"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    # Error recovery if aerich claims init-db is missing
    if result.returncode != 0 and "aerich init-db" in result.stderr:
        print("[yellow]⚠️ Database uninitialized. Running 'aerich init-db'...[/yellow]")
        init_result = subprocess.run(
            ["aerich", "init-db"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if init_result.returncode == 0:
            print("[green]✓ Initial database schema initialized successfully.[/green]")
            return
        else:
            print(f"[bold red]❌ Failed to initialize database:[/bold red]\n[dim]{init_result.stderr}[/dim]")
            raise typer.Exit(code=1)

    if result.returncode != 0:
        combined_output = f"{result.stdout}\n{result.stderr}"
        if "No changes detected" in combined_output:
            print("[yellow]ℹ️ No schema changes detected.[/yellow]")
            return
        print(f"[bold red]❌ Migration generation failed:[/bold red]\n[dim]{result.stderr or result.stdout}[/dim]")
        raise typer.Exit(code=1)

    print("[green]✓ Migration files generated.[/green]")


# ==========================================================
# COMMAND
# ==========================================================


@app.command()
def makemigrations_cmd(
    apps: Optional[List[str]] = typer.Argument(
        None,
        help="Optional app names. If omitted, all discovered apps are migrated.",
    ),
):
    """Generate database migration files for Fapix apps."""
    project_root = require_project_root()
    available_apps = discover_apps(project_root)

    if not available_apps:
        print("[yellow]⚠️ No apps containing 'models.py' were found.[/yellow]")
        raise typer.Exit(code=0)

    requested_apps = apps or available_apps
    validate_requested_apps(requested_apps, available_apps)

    # 1. Sync model files to db_config.py
    sync_db_config_models(project_root, requested_apps)

    # 2. Output overview
    apps_str = ", ".join(f"[bold]{a}[/bold]" for a in requested_apps)
    print(f"[cyan] Fapix makemigrations[/cyan] [dim]({apps_str})[/dim]")

    # 3. Ensure Aerich initialization
    ensure_aerich_initialized(project_root)

    # 4. Generate migrations (with auto-fallback recovery)
    run_aerich_migrate(project_root)

    print("[bold green] Done![/bold green]")


if __name__ == "__main__":
    app()