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
# DISCOVER & SYNC APPS
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
    if not config_path.exists():
        return

    content = config_path.read_text(encoding="utf-8")
    expected_models = ["aerich.models"] + [f"apps.{app}.models" for app in apps]

    models_pattern = re.compile(
        r'("models"\s*:\s*\[)([^\]]*?)(\])', re.MULTILINE | re.DOTALL
    )

    match = models_pattern.search(content)
    if not match:
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


def validate_apps(requested: List[str], available: List[str]) -> None:
    invalid = [name for name in requested if name not in available]
    if invalid:
        print(f"[bold red]❌ Unknown app(s):[/bold red] {', '.join(invalid)}")
        print(f"[dim]Available apps: {', '.join(available)}[/dim]")
        raise typer.Exit(code=1)


# ==========================================================
# AERICH INITIALIZATION & MIGRATION EXECUTOR
# ==========================================================


def ensure_aerich_initialized(project_root: Path) -> None:
    """Ensure Aerich config and migrations directory exist before upgrading."""
    pyproject = project_root / "pyproject.toml"

    # 1. Initialize Aerich config if missing
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


def run_aerich_upgrade(project_root: Path) -> None:
    """
    Executes 'aerich upgrade' and handles Aerich error scenarios with auto-recovery.
    """
    print("[cyan] Applying database migrations...[/cyan]")

    result = subprocess.run(
        ["aerich", "upgrade"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("[green]✓ Database upgraded to latest schema.[/green]")
        return

    combined_output = f"{result.stdout}\n{result.stderr}".lower()

    # ------------------------------------------------------
    # FALLBACK 1: Database or migrations uninitialized
    # ------------------------------------------------------
    if "init-db" in combined_output or "no such table" in combined_output:
        print("[yellow]⚠️ Database uninitialized. Attempting 'aerich init-db'...[/yellow]")
        init_db_res = subprocess.run(
            ["aerich", "init-db"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        if init_db_res.returncode == 0:
            print("[green]✓ Initial database schema applied successfully.[/green]")
            return
        elif "already initialized" in init_db_res.stderr.lower():
            # If init-db fails because it's initialized, retry upgrade
            retry_upgrade = subprocess.run(
                ["aerich", "upgrade"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if retry_upgrade.returncode == 0:
                print("[green]✓ Database upgraded to latest schema.[/green]")
                return

        print(f"[bold red]❌ Failed to initialize database schema:[/bold red]\n[dim]{init_db_res.stderr or init_db_res.stdout}[/dim]")
        raise typer.Exit(code=1)

    # ------------------------------------------------------
    # FALLBACK 2: Pending migration files not generated yet
    # ------------------------------------------------------
    if "migrate" in combined_output or "no migration" in combined_output:
        print("[yellow]⚠️ Missing migration files detected. Generating migrations...[/yellow]")
        migrate_res = subprocess.run(
            ["aerich", "migrate"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        if migrate_res.returncode == 0:
            print("[green]✓ Migration files auto-generated. Retrying upgrade...[/green]")
            retry_upgrade = subprocess.run(
                ["aerich", "upgrade"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if retry_upgrade.returncode == 0:
                print("[green]✓ Database upgraded to latest schema.[/green]")
                return

    # ------------------------------------------------------
    # NO CHANGES / ALREADY UP TO DATE
    # ------------------------------------------------------
    if "no upgrade items" in combined_output or "already at latest" in combined_output:
        print("[yellow]ℹ️ Database is already up to date.[/yellow]")
        return

    # Unhandled error display
    print(f"[bold red]❌ Migration failed:[/bold red]\n[dim]{result.stderr or result.stdout}[/dim]")
    raise typer.Exit(code=1)


# ==========================================================
# COMMAND
# ==========================================================


@app.command()
def migrate_cmd(
    apps: Optional[List[str]] = typer.Argument(
        None,
        help="Optional app names. If omitted, all discovered apps are migrated.",
    ),
):
    """Apply pending database migrations for Fapix apps."""
    project_root = require_project_root()
    available_apps = discover_apps(project_root)

    if not available_apps:
        print("[yellow]⚠️ No apps containing 'models.py' were found.[/yellow]")
        raise typer.Exit(code=0)

    selected_apps = apps or available_apps
    validate_apps(selected_apps, available_apps)

    # 1. Sync discovered apps to db_config.py
    sync_db_config_models(project_root, selected_apps)

    # 2. Compact CLI status overview
    apps_str = ", ".join(f"[bold]{a}[/bold]" for a in selected_apps)
    print(f"[cyan] Fapix migrate[/cyan] [dim]({apps_str})[/dim]")

    # 3. Ensure Aerich project setup
    ensure_aerich_initialized(project_root)

    # 4. Run upgrade with intelligent fallbacks
    run_aerich_upgrade(project_root)

    print("[bold green] Done![/bold green]")


if __name__ == "__main__":
    app()