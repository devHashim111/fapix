import asyncio
import importlib
import os
import sys
from getpass import getpass
from pathlib import Path

import typer
from rich import print


# =========================================================
# PROJECT DETECTION
# =========================================================

def get_project_root() -> Path:
    """
    Detect the current Fapix/FastAPI project.

    A valid project must contain:

        main.py
        apps/
        db_config.py

    The command can also be executed from a subdirectory
    inside the project.
    """

    current = Path.cwd().resolve()

    while current != current.parent:

        main_file = current / "main.py"
        apps_dir = current / "apps"
        db_config = current / "db_config.py"

        if main_file.exists() and apps_dir.exists():

            return current

        current = current.parent

    print(
        "[red]❌ No Fapix project found.[/red]\n"
        "[yellow]Run this command inside a Fapix project.[/yellow]"
    )

    raise typer.Exit(code=1)


def prepare_project_imports(project_root: Path):
    """
    Add the project root to Python's import path.

    This allows:

        from db_config import TORTOISE_ORM
        from apps.auth.models import User

    even when the command is executed from another
    directory inside the project.
    """

    project_path = str(project_root)

    if project_path not in sys.path:
        sys.path.insert(0, project_path)


# =========================================================
# DATABASE / MIGRATIONS
# =========================================================

def ensure_database_ready(project_root: Path):
    """
    Ensure the project has database configuration and
    migrations are ready.
    """

    db_config_file = project_root / "db_config.py"

    if not db_config_file.exists():

        print(
            "[red]❌ db_config.py not found.[/red]\n"
            "[yellow]Run 'fapix startdb' first.[/yellow]"
        )

        raise typer.Exit(code=1)

    print("[cyan]🔄 Checking database and migrations...[/cyan]")

    original_directory = Path.cwd()

    try:

        os.chdir(project_root)

        result = os.system("fapix makemigrations")

        if result != 0:

            print(
                "[red]❌ Failed to prepare migrations.[/red]"
            )

            raise typer.Exit(code=1)

        result = os.system("fapix migrate")

        if result != 0:

            print(
                "[red]❌ Failed to migrate database.[/red]"
            )

            raise typer.Exit(code=1)

    finally:

        os.chdir(original_directory)


# =========================================================
# AUTH APP / USER MODEL
# =========================================================

def get_user_model(project_root: Path):
    """
    Load the User model from:

        apps/auth/models.py
    """

    auth_models = project_root / "apps" / "auth" / "models.py"

    if not auth_models.exists():

        print(
            "[red]❌ Auth app or User model not found.[/red]\n"
            "[yellow]Run:[/yellow] fapix startapp auth"
        )

        raise typer.Exit(code=1)

    try:

        prepare_project_imports(project_root)

        module = importlib.import_module(
            "apps.auth.models"
        )

        return module.User

    except Exception as e:

        print(
            f"[red]❌ Failed to load User model: {e}[/red]"
        )

        raise typer.Exit(code=1)


def get_tortoise_config(project_root: Path):
    """
    Load TORTOISE_ORM from the project's db_config.py.
    """

    try:

        prepare_project_imports(project_root)

        # Remove cached module if necessary.
        if "db_config" in sys.modules:
            del sys.modules["db_config"]

        module = importlib.import_module("db_config")

        return module.TORTOISE_ORM

    except Exception as e:

        print(
            f"[red]❌ Failed to load database configuration: {e}[/red]"
        )

        raise typer.Exit(code=1)


# =========================================================
# CREATE USER
# =========================================================

async def create_user_in_db(
    project_root: Path,
    username: str,
    email: str,
    password: str,
    is_superuser: bool = False,
):
    """
    Create a user in the Tortoise ORM database.
    """

    User = get_user_model(project_root)

    existing_user = await User.filter(
        email=email
    ).first()

    if existing_user:
        print(
            f"[red]❌ User with email '{email}' already exists.[/red]"
        )
        raise typer.Exit(code=1)

    existing_username = await User.filter(
        username=username
    ).first()

    if existing_username:
        print(
            f"[red]❌ Username '{username}' already exists.[/red]"
        )
        raise typer.Exit(code=1)
    
    # -------------------------------------------------
    # Password hashing
    # -------------------------------------------------

    from apps.auth.views import hash_password

    user = await User.create(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
        role="superuser" if is_superuser else "user",
    )

    return user

    # -------------------------------------------------
    # Password hashing
    # -------------------------------------------------

    user.set_password(password)

    await user.save()

    return user


async def run_create_user(
    project_root: Path,
    username: str,
    email: str,
    password: str,
    is_superuser: bool,
):
    """
    Initialize Tortoise, create the user,
    then close database connections.
    """

    from tortoise import Tortoise

    config = get_tortoise_config(project_root)

    await Tortoise.init(
        config=config
    )

    try:

        user = await create_user_in_db(
            project_root=project_root,
            username=username,
            email=email,
            password=password,
            is_superuser=is_superuser,
        )

        return user

    finally:

        await Tortoise.close_connections()


# =========================================================
# INPUT HELPERS
# =========================================================

def get_user_input(
    username: str | None,
    email: str | None,
    password: str | None,
):
    """
    Ask for missing user information.
    """

    if not username:

        username = typer.prompt(
            "Username"
        )

    if not email:

        email = typer.prompt(
            "Email"
        )

    if not password:

        password = getpass(
            "Password: "
        )

        password_confirm = getpass(
            "Password (again): "
        )

        if password != password_confirm:

            print(
                "[red]❌ Passwords do not match.[/red]"
            )

            raise typer.Exit(code=1)

    return username, email, password


# =========================================================
# CREATE NORMAL USER
# =========================================================

def createuser_cmd(
    username: str = typer.Argument(
        None,
        help="Username",
    ),
    email: str = typer.Argument(
        None,
        help="Email address",
    ),
    password: str = typer.Argument(
        None,
        help="Password",
    ),
):
    """
    Create a normal user.

    Examples:

        fapix createuser

        fapix createuser hadi hadi@gmail.com pass123
    """

    # -------------------------------------------------
    # Detect project
    # -------------------------------------------------

    project_root = get_project_root()

    prepare_project_imports(project_root)

    # -------------------------------------------------
    # Ensure DB and migrations
    # -------------------------------------------------

    ensure_database_ready(project_root)

    # -------------------------------------------------
    # Get user data
    # -------------------------------------------------

    username, email, password = get_user_input(
        username,
        email,
        password,
    )

    # -------------------------------------------------
    # Create user
    # -------------------------------------------------

    try:

        user = asyncio.run(
            run_create_user(
                project_root=project_root,
                username=username,
                email=email,
                password=password,
                is_superuser=False,
            )
        )

        print()

        print(
            "[green]"
            "╔══════════════════════════════════════╗\n"
            "║      User created successfully     ║\n"
            "╚══════════════════════════════════════╝"
            "[/green]"
        )

        print(
            f"[cyan]Username:[/cyan] {user.username}"
        )

        print(
            f"[cyan]Email:[/cyan] {user.email}"
        )

    except typer.Exit:

        raise

    except Exception as e:

        print(
            f"[red]❌ Error creating user: {e}[/red]"
        )

        raise typer.Exit(code=1)


# =========================================================
# CREATE SUPERUSER
# =========================================================

def createsuperuser_cmd(
    username: str = typer.Argument(
        None,
        help="Username",
    ),
    email: str = typer.Argument(
        None,
        help="Email address",
    ),
    password: str = typer.Argument(
        None,
        help="Password",
    ),
):
    """
    Create a superuser.

    Examples:

        fapix createsuperuser

        fapix createsuperuser admin admin@example.com pass123
    """

    # -------------------------------------------------
    # Detect project
    # -------------------------------------------------

    project_root = get_project_root()

    prepare_project_imports(project_root)

    # -------------------------------------------------
    # Ensure DB and migrations
    # -------------------------------------------------

    ensure_database_ready(project_root)

    # -------------------------------------------------
    # Get user data
    # -------------------------------------------------

    username, email, password = get_user_input(
        username,
        email,
        password,
    )

    # -------------------------------------------------
    # Create superuser
    # -------------------------------------------------

    try:

        user = asyncio.run(
            run_create_user(
                project_root=project_root,
                username=username,
                email=email,
                password=password,
                is_superuser=True,
            )
        )

        print()

        print(
            "[yellow]"
            "╔══════════════════════════════════════════╗\n"
            "║    Superuser created successfully      ║\n"
            "╚══════════════════════════════════════════╝"
            "[/yellow]"
        )

        print(
            f"[cyan]Username:[/cyan] {user.username}"
        )

        print(
            f"[cyan]Email:[/cyan] {user.email}"
        )

    except typer.Exit:

        raise

    except Exception as e:

        print(
            f"[red]❌ Error creating superuser: {e}[/red]"
        )

        raise typer.Exit(code=1)


# =========================================================
# DELETE USER
# =========================================================

async def run_delete_user(
    project_root: Path,
    identifier: str,
):
    """
    Delete a user by username or email.
    """

    from tortoise import Tortoise

    User = get_user_model(project_root)

    config = get_tortoise_config(project_root)

    await Tortoise.init(
        config=config
    )

    try:

        user = await User.filter(
            username=identifier
        ).first()

        if not user:

            user = await User.filter(
                email=identifier
            ).first()

        if not user:

            return False

        await user.delete()

        return True

    finally:

        await Tortoise.close_connections()


def deleteuser_cmd(
    identifier: str = typer.Argument(
        None,
        help="Username or email of the user",
    ),
):
    """
    Delete a user.

    Examples:

        fapix deleteuser hadi

        fapix deleteuser hadi@gmail.com
    """

    # -------------------------------------------------
    # Detect project
    # -------------------------------------------------

    project_root = get_project_root()

    prepare_project_imports(project_root)

    # -------------------------------------------------
    # Ensure database is ready
    # -------------------------------------------------

    ensure_database_ready(project_root)

    # -------------------------------------------------
    # Get identifier
    # -------------------------------------------------

    if not identifier:

        identifier = typer.prompt(
            "Username or email"
        )

    # -------------------------------------------------
    # Confirmation
    # -------------------------------------------------

    confirm = typer.confirm(
        f"Are you sure you want to delete '{identifier}'?"
    )

    if not confirm:

        print(
            "[yellow]⚠️ User deletion cancelled.[/yellow]"
        )

        raise typer.Exit()

    # -------------------------------------------------
    # Delete
    # -------------------------------------------------

    try:

        deleted = asyncio.run(
            run_delete_user(
                project_root=project_root,
                identifier=identifier,
            )
        )

        if not deleted:

            print(
                f"[red]❌ User '{identifier}' not found.[/red]"
            )

            raise typer.Exit(code=1)

        print(
            f"[green]✅ User '{identifier}' deleted successfully.[/green]"
        )

    except typer.Exit:

        raise

    except Exception as e:

        print(
            f"[red]❌ Error deleting user: {e}[/red]"
        )

        raise typer.Exit(code=1)