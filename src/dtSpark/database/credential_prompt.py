"""
Database credential prompting utility.

Provides interactive prompts for missing database credentials.


"""

import logging
import getpass
from typing import Optional
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

from .backends import DatabaseCredentials


def prompt_for_credentials(db_type: str, existing_credentials: Optional[DatabaseCredentials] = None) -> DatabaseCredentials:
    """
    Interactively prompt user for missing database credentials.

    Args:
        db_type: Database type (sqlite, mysql, mariadb, postgresql, mssql)
        existing_credentials: Existing credentials (will only prompt for missing fields)

    Returns:
        Complete DatabaseCredentials object
    """
    console = Console()
    db_type_lower = db_type.lower()

    # Start with existing credentials or create new
    if existing_credentials:
        creds = existing_credentials
    else:
        creds = DatabaseCredentials()

    # SQLite only needs path
    if db_type_lower == 'sqlite':
        if not creds.path:
            creds.path = Prompt.ask(
                "Enter SQLite database file path",
                default="./running/conversations.db"
            )
        return creds

    # Display information panel
    console.print()
    console.print(Panel(
        f"[bold cyan]Database Connection Setup[/bold cyan]\n\n"
        f"Database type: [yellow]{db_type}[/yellow]\n\n"
        f"Please provide connection credentials for your database server.",
        border_style="cyan",
        padding=(1, 2)
    ))
    console.print()

    # Prompt for remote database credentials
    if not creds.host:
        creds.host = Prompt.ask(
            "Database host",
            default="localhost"
        )

    if not creds.port:
        default_ports = {
            'mysql': 3306,
            'mariadb': 3306,
            'postgresql': 5432,
            'mssql': 1433,
            'sqlserver': 1433
        }
        default_port = default_ports.get(db_type_lower, 3306)

        port_input = Prompt.ask(
            "Database port",
            default=str(default_port)
        )
        creds.port = int(port_input)

    if not creds.database:
        creds.database = Prompt.ask(
            "Database name",
            default="dtawsbedrockcli"
        )

    if not creds.username:
        creds.username = Prompt.ask("Database username")

    if not creds.password:
        # Use getpass for secure password input
        console.print("[cyan]Database password:[/cyan] ", end="")
        creds.password = getpass.getpass("")

    # SSL option
    use_ssl = Confirm.ask("Use SSL/TLS connection?", default=False)
    creds.ssl = use_ssl

    # MSSQL-specific: driver selection
    if db_type_lower in ('mssql', 'sqlserver', 'mssqlserver'):
        if not creds.driver:
            drivers = [
                "ODBC Driver 17 for SQL Server",
                "ODBC Driver 18 for SQL Server",
                "SQL Server Native Client 11.0",
                "Custom"
            ]

            console.print()
            console.print("[bold cyan]Select ODBC driver:[/bold cyan]")
            for i, driver in enumerate(drivers, 1):
                console.print(f"  [{i}] {driver}")

            choice = Prompt.ask(
                "Driver selection",
                choices=[str(i) for i in range(1, len(drivers) + 1)],
                default="1"
            )

            choice_idx = int(choice) - 1
            if choice_idx == len(drivers) - 1:  # Custom
                creds.driver = Prompt.ask("Enter custom ODBC driver name")
            else:
                creds.driver = drivers[choice_idx]

    console.print()
    logging.info(f"Database credentials collected for {db_type}")

    return creds


def test_credentials(db_type: str, credentials: DatabaseCredentials) -> tuple[bool, Optional[str]]:
    """
    Test database credentials by attempting connection.

    Args:
        db_type: Database type
        credentials: Database credentials

    Returns:
        Tuple of (success, error_message)
    """
    from .backends import create_backend

    console = Console()

    try:
        console.print()
        console.print("[cyan]Testing database connection...[/cyan]")

        backend = create_backend(db_type, credentials)
        success = backend.test_connection()
        backend.close()

        if success:
            console.print("[green]✓ Database connection successful![/green]")
            return True, None
        else:
            error_msg = "Connection test query failed"
            console.print(f"[red]✗ {error_msg}[/red]")
            return False, error_msg

    except ImportError as e:
        error_msg = str(e)
        console.print(f"[red]✗ {error_msg}[/red]")
        return False, error_msg

    except Exception as e:
        error_msg = f"Connection failed: {str(e)}"
        console.print(f"[red]✗ {error_msg}[/red]")
        logging.error(f"Database connection test failed: {e}", exc_info=True)
        return False, error_msg


def prompt_and_validate_credentials(db_type: str,
                                    existing_credentials: Optional[DatabaseCredentials] = None,
                                    max_retries: int = 3) -> Optional[DatabaseCredentials]:
    """
    Prompt for credentials and validate them, with retry support.

    Args:
        db_type: Database type
        existing_credentials: Existing credentials (will only prompt for missing fields)
        max_retries: Maximum number of retry attempts

    Returns:
        Valid DatabaseCredentials or None if max retries exceeded
    """
    console = Console()
    creds = existing_credentials

    for attempt in range(max_retries):
        # Prompt for credentials
        creds = prompt_for_credentials(db_type, creds)

        # Test credentials
        success, error_msg = test_credentials(db_type, creds)

        if success:
            return creds

        # Failed - offer retry
        if attempt < max_retries - 1:
            console.print()
            retry = Confirm.ask(
                f"[yellow]Connection failed. Retry with different credentials? ({max_retries - attempt - 1} attempts remaining)[/yellow]",
                default=True
            )

            if not retry:
                return None
        else:
            console.print()
            console.print(f"[red]Maximum connection attempts ({max_retries}) exceeded.[/red]")
            return None

    return None
