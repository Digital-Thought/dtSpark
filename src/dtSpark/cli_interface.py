"""
CLI interface module for user interaction using Rich terminal UI.

This module provides functionality for:
- Displaying menus and prompts with beautiful formatting
- Handling user input
- Progress tracking for initialisation
- Application splash screens
"""

from typing import List, Dict, Optional
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
import time
import re


# Common style and message string constants (SonarCloud S1192)
_STYLE_BOLD_CYAN = "bold cyan"
_STYLE_BOLD_YELLOW = "bold yellow"
_STYLE_BOLD_MAGENTA = "bold magenta"
_MSG_INVALID_SELECTION = "Invalid selection"
_MSG_CANCEL_OPTION = "  [0] Cancel"
_MSG_ENTER_CHOICE = "Enter choice"
_MSG_INVALID_CHOICE = "Invalid choice"
_MSG_INVALID_INPUT = "Invalid input"


def extract_friendly_model_name(model_id: str) -> str:
    """
    Extract a human-friendly model name from a full model ID or ARN.

    Examples:
        - 'arn:aws:bedrock:...:inference-profile/au.anthropic.claude-sonnet-4-5-20250929-v1:0'
          → 'Claude Sonnet 4.5'
        - 'anthropic.claude-3-5-sonnet-20241022-v2:0' → 'Claude 3.5 Sonnet'
        - 'meta.llama3-1-70b-instruct-v1:0' → 'Llama 3.1 70B Instruct'

    Args:
        model_id: Full model ID, ARN, or inference profile

    Returns:
        Human-readable model name
    """
    if not model_id:
        return "Unknown"

    # Extract the core model identifier from ARN or full path
    model_lower = model_id.lower()

    # Handle inference profile ARNs
    if 'inference-profile/' in model_lower:
        # Extract after inference-profile/
        match = re.search(r'inference-profile/([^:]+)', model_id, re.IGNORECASE)
        if match:
            model_lower = match.group(1).lower()

    # Claude model patterns
    claude_patterns = [
        (r'claude-opus-4\.5|claude-opus-4-5', 'Claude Opus 4.5'),
        (r'claude-sonnet-4\.5|claude-sonnet-4-5', 'Claude Sonnet 4.5'),
        (r'claude-opus-4(?!\.)', 'Claude Opus 4'),
        (r'claude-sonnet-4(?!\.)', 'Claude Sonnet 4'),
        (r'claude-3-5-sonnet', 'Claude 3.5 Sonnet'),
        (r'claude-3-5-haiku', 'Claude 3.5 Haiku'),
        (r'claude-3-opus', 'Claude 3 Opus'),
        (r'claude-3-sonnet', 'Claude 3 Sonnet'),
        (r'claude-3-haiku', 'Claude 3 Haiku'),
        (r'claude-2\.1', 'Claude 2.1'),
        (r'claude-2', 'Claude 2'),
        (r'claude-instant', 'Claude Instant'),
    ]

    for pattern, name in claude_patterns:
        if re.search(pattern, model_lower):
            return name

    # Llama patterns
    llama_patterns = [
        (r'llama3-1-(\d+)b', lambda m: f"Llama 3.1 {m.group(1)}B"),
        (r'llama3\.2', 'Llama 3.2'),
        (r'llama3', 'Llama 3'),
        (r'llama2-(\d+)b', lambda m: f"Llama 2 {m.group(1)}B"),
    ]

    for pattern, name in llama_patterns:
        match = re.search(pattern, model_lower)
        if match:
            if callable(name):
                return name(match)
            return name

    # Mistral patterns
    if 'mistral-large' in model_lower:
        return 'Mistral Large'
    if 'mistral-small' in model_lower:
        return 'Mistral Small'
    if 'mistral' in model_lower:
        return 'Mistral'

    # Amazon Titan patterns
    if 'titan-text-express' in model_lower:
        return 'Amazon Titan Text Express'
    if 'titan-text-lite' in model_lower:
        return 'Amazon Titan Text Lite'
    if 'titan' in model_lower:
        return 'Amazon Titan'

    # Cohere patterns
    if 'cohere.command-r-plus' in model_lower:
        return 'Cohere Command R+'
    if 'cohere.command-r' in model_lower:
        return 'Cohere Command R'
    if 'cohere' in model_lower:
        return 'Cohere'

    # If no pattern matched, try to clean up the model ID
    # Remove common prefixes and suffixes
    cleaned = model_id
    for prefix in ['arn:aws:bedrock:', 'anthropic.', 'meta.', 'amazon.', 'cohere.', 'mistral.', 'au.', 'us.', 'eu.']:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]

    # Remove version suffixes like -v1:0, -20241022-v2:0
    cleaned = re.sub(r'-\d{8}-v\d+:\d+$', '', cleaned)
    cleaned = re.sub(r'-v\d+:\d+$', '', cleaned)
    cleaned = re.sub(r':\d+$', '', cleaned)

    # Title case and limit length
    if len(cleaned) > 50:
        cleaned = cleaned[:47] + '...'

    return cleaned


class StatusIndicator:
    """Context manager for displaying an animated status indicator with elapsed time."""

    def __init__(self, console: Console, message: str, cli_interface=None):
        """
        Initialise status indicator.

        Args:
            console: Rich console instance
            message: Status message to display
            cli_interface: Optional CLIInterface to register with for pause/resume control
        """
        self.console = console
        self.message = message
        self.start_time = None
        self.live = None
        self.cli_interface = cli_interface
        self._is_paused = False

    def __enter__(self):
        """Start the status indicator."""
        self.start_time = time.time()
        spinner = Spinner("dots", text=f"[cyan]{self.message}[/cyan]", style="cyan")
        self.live = Live(spinner, console=self.console, refresh_per_second=10)
        self.live.start()
        # Register with CLI interface for pause/resume control
        if self.cli_interface:
            self.cli_interface._active_status_indicator = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop the status indicator and show elapsed time."""
        if self.live:
            self.live.stop()

        # Unregister from CLI interface
        if self.cli_interface:
            self.cli_interface._active_status_indicator = None

        if self.start_time and not self._is_paused:
            elapsed = time.time() - self.start_time
            self.console.print(f"[dim]✓ Completed in {elapsed:.1f}s[/dim]")

        return False  # Don't suppress exceptions

    def pause(self):
        """
        Temporarily pause the status indicator to allow user interaction.
        Call resume() to continue the indicator.
        """
        if self.live and not self._is_paused:
            self.live.stop()
            self._is_paused = True

    def resume(self):
        """
        Resume the status indicator after a pause.
        """
        if self._is_paused and self.start_time:
            elapsed = time.time() - self.start_time
            spinner = Spinner("dots", text=f"[cyan]{self.message} ({elapsed:.0f}s)[/cyan]", style="cyan")
            self.live = Live(spinner, console=self.console, refresh_per_second=10)
            self.live.start()
            self._is_paused = False

    def update(self, message: str):
        """
        Update the status message.

        Args:
            message: New status message
        """
        if self.live and self.start_time and not self._is_paused:
            elapsed = time.time() - self.start_time
            spinner = Spinner("dots", text=f"[cyan]{message} ({elapsed:.0f}s)[/cyan]", style="cyan")
            self.live.update(spinner)


class CLIInterface:
    """Provides command-line interface functionality using Rich terminal UI."""

    def __init__(self):
        """Initialise the CLI interface."""
        self.console = Console()
        self.running = True
        self.model_changing_enabled = True  # Can be disabled if model is locked via config
        self.cost_tracking_enabled = False  # Can be enabled via config
        self.actions_enabled = False  # Can be enabled via autonomous_actions.enabled config
        self.new_conversations_allowed = True  # Can be disabled via predefined_conversations.allow_new_conversations
        self._active_status_indicator = None  # Track active status indicator for pause/resume

    def print_splash_screen(self, full_name: str, description: str, version: str):  # noqa: S1172
        """
        Print application splash screen with SPARK branding.

        Args:
            full_name: Application full name
            description: Application description
            version: Application version
        """
        import os
        from dtPyAppFramework.process import ProcessManager

        # Get log path
        log_path = ProcessManager().log_path

        # Build splash content line by line
        splash_content = Text()
        splash_content.append("\n")

        # Line 1: *  .  * and DIGITAL-THOUGHT
        splash_content.append("    *  .  *              ", style="bright_yellow")
        splash_content.append(" DIGITAL-THOUGHT\n", style="bold bright_magenta")

        # Line 2: . \|/ . and Secure Personal AI Research Kit
        splash_content.append("    . \\|/ .              ", style="yellow")
        splash_content.append(" Secure Personal AI Research Kit\n", style="cyan")

        # Line 3: S P A R K and Version
        splash_content.append("   *-- ", style="bright_yellow")
        splash_content.append("S P A R K", style="bold bright_cyan")
        splash_content.append(" --*     ", style="bright_yellow")
        splash_content.append(f" Version {version}\n", style="green")

        # Line 4: . /|\ .
        splash_content.append("    . /|\\ .              \n", style="yellow")

        # Line 5: *  .  * and Process ID
        splash_content.append("     *  .  *             ", style="bright_yellow")
        splash_content.append(f" Process ID: {os.getpid()}\n", style="cyan")

        # Line 6: blank space and Log Path
        splash_content.append("                          ", style="")
        splash_content.append(f"Log Path: {log_path}\n", style="dim")

        splash_content.append("")

        # Create panel
        splash_panel = Panel(
            splash_content,
            border_style="bright_cyan",
            box=box.HEAVY,
            padding=(0, 2)
        )

        self.console.print()
        self.console.print(splash_panel)
        self.console.print()

    def print_banner(self):
        """Print the application banner."""
        # This is now replaced by print_splash_screen
        pass

    def create_progress(self, description: str = "Initialising...") -> Progress:  # noqa: S1172
        """
        Create a progress bar for tracking operations.

        Args:
            description: Description of the operation

        Returns:
            Progress instance
        """
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console
        )

    def status_indicator(self, message: str):
        """
        Create a status indicator with spinner and elapsed time.
        Use as a context manager.

        The status indicator registers with the CLI interface so it can be
        paused/resumed when user input is needed (e.g., tool permission prompts).

        Args:
            message: Status message to display

        Returns:
            StatusIndicator context manager

        Example:
            with cli.status_indicator("Processing request..."):
                # Do work here
                pass
        """
        return StatusIndicator(self.console, message, cli_interface=self)

    def pause_status_indicator(self):
        """
        Pause the active status indicator to allow user interaction.
        Call resume_status_indicator() after the interaction is complete.
        """
        if self._active_status_indicator:
            self._active_status_indicator.pause()

    def resume_status_indicator(self):
        """
        Resume the active status indicator after user interaction.
        """
        if self._active_status_indicator:
            self._active_status_indicator.resume()

    def print_separator(self, char: str = "─", length: int = 70):
        """
        Print a separator line.

        Args:
            char: Character to use for the separator
            length: Length of the separator line
        """
        self.console.print(char * length, style="dim")

    def display_main_menu(self) -> str:
        """
        Display the main menu and get user's choice.

        Returns:
            User's menu choice: 'costs', 'new', 'list', or 'quit'
        """
        # Create menu content
        menu_content = Text()
        option_num = 1
        choice_map = {}

        # Conditionally show cost tracking option
        if self.cost_tracking_enabled:
            menu_content.append("  ", style="")
            menu_content.append(str(option_num), style="cyan")
            menu_content.append(". Re-gather AWS Bedrock Costs\n", style="")
            choice_map[str(option_num)] = 'costs'
            option_num += 1

        # Start New Conversation (only when new conversations are allowed)
        if self.new_conversations_allowed:
            menu_content.append("  ", style="")
            menu_content.append(str(option_num), style="cyan")
            menu_content.append(". Start New Conversation\n", style="")
            choice_map[str(option_num)] = 'new'
            option_num += 1

        # List and Select Conversation
        menu_content.append("  ", style="")
        menu_content.append(str(option_num), style="cyan")
        menu_content.append(". List and Select Conversation\n", style="")
        choice_map[str(option_num)] = 'list'
        option_num += 1

        # Manage Autonomous Actions (only when enabled)
        if self.actions_enabled:
            menu_content.append("  ", style="")
            menu_content.append(str(option_num), style="cyan")
            menu_content.append(". Manage Autonomous Actions\n", style="")
            choice_map[str(option_num)] = 'autonomous'
            option_num += 1

        # Quit
        menu_content.append("  ", style="")
        menu_content.append(str(option_num), style="cyan")
        menu_content.append(". Quit", style="")
        choice_map[str(option_num)] = 'quit'

        # Create panel with HEAVY borders
        menu_panel = Panel(
            menu_content,
            title="[bold bright_magenta]MAIN MENU[/bold bright_magenta]",
            border_style=_STYLE_BOLD_CYAN,
            box=box.HEAVY,
            padding=(0, 1)
        )

        self.console.print()
        self.console.print(menu_panel)
        self.console.print()

        # Get user input
        choice = self.get_input("Select an option")

        return choice_map.get(choice, 'invalid')

    def print_budget_warning(self, message: str, level: str = "75"):
        """
        Print a budget warning with appropriate colour based on level.

        Args:
            message: Warning message to display
            level: Warning level ('75', '85', '95')
        """
        if level == "75":
            # Yellow/amber warning
            self.console.print(f"⚠️  [yellow]{message}[/yellow]")
        elif level == "85":
            # Orange warning
            self.console.print(f"⚠️  [bold yellow]{message}[/bold yellow]")
        elif level == "95":
            # Red warning
            self.console.print(f"🚨 [bold red]{message}[/bold red]")
        else:
            self.console.print(f"⚠️  {message}")

    def prompt_budget_override(self) -> tuple[bool, float]:
        """
        Prompt user for budget override when limit is reached.

        Returns:
            Tuple of (override_accepted, additional_percentage)
        """
        self.console.print("\n[bold red]❌ Budget Limit Reached[/bold red]")
        self.console.print("[yellow]Would you like to override the budget limit?[/yellow]")

        override = self.confirm("Allow budget override?")
        if not override:
            return False, 0.0

        # Get additional percentage
        while True:
            try:
                percentage_input = input("Enter additional percentage to allow (e.g., 10 for 10% more): ").strip()
                percentage = float(percentage_input)

                if percentage <= 0:
                    self.console.print("[red]Please enter a positive number[/red]")
                    continue

                if percentage > 500:  # Sanity check
                    self.console.print("[red]Maximum override is 500%[/red]")
                    continue

                return True, percentage

            except ValueError:
                self.console.print("[red]Please enter a valid number[/red]")
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Override cancelled[/yellow]")
                return False, 0.0

    def print_error(self, message: str):
        """
        Print an error message.

        Args:
            message: Error message to display
        """
        self.console.print(f"\n[bold red]✗[/bold red] [red]{message}[/red]\n")

    def print_success(self, message: str):
        """
        Print a success message.

        Args:
            message: Success message to display
        """
        self.console.print(f"\n[bold green]✓[/bold green] [green]{message}[/green]\n")

    def print_info(self, message: str):
        """
        Print an informational message.

        Args:
            message: Info message to display
        """
        self.console.print(f"\n[bold cyan]ℹ[/bold cyan] [cyan]{message}[/cyan]\n")

    def print_warning(self, message: str):
        """
        Print a warning message.

        Args:
            message: Warning message to display
        """
        self.console.print(f"\n[bold yellow]⚠[/bold yellow] [yellow]{message}[/yellow]\n")

    def get_input(self, prompt: str) -> str:
        """
        Get user input with a prompt.

        Args:
            prompt: Prompt to display

        Returns:
            User input string
        """
        return Prompt.ask(f"[bold cyan]{prompt}[/bold cyan]").strip()

    def get_multiline_input(self, prompt: str) -> str:
        """
        Get multiline user input (ends with double Enter).

        Args:
            prompt: Prompt to display

        Returns:
            Multiline user input string
        """
        self.console.print(f"\n[bold cyan]{prompt}[/bold cyan]")
        self.console.print("[dim](Press Enter twice to finish)[/dim]\n")

        lines = []
        empty_line_count = 0

        while True:
            line = input()
            if line == "":
                empty_line_count += 1
                if empty_line_count >= 2:
                    break
                lines.append(line)
            else:
                empty_line_count = 0
                lines.append(line)

        return '\n'.join(lines).strip()

    def display_menu(self, title: str, options: List[str]) -> int:
        """
        Display a menu and get user selection.

        Args:
            title: Menu title
            options: List of menu options

        Returns:
            Selected option index (0-based) or -1 for invalid selection
        """
        # Create table
        table = Table(show_header=False, box=box.ROUNDED, border_style="cyan")
        table.add_column("No.", style=_STYLE_BOLD_YELLOW, width=4)
        table.add_column("Option", style="white")

        for i, option in enumerate(options, 1):
            table.add_row(str(i), option)

        table.add_row(str(len(options) + 1), "[red]Exit[/red]")

        # Display in panel
        panel = Panel(
            table,
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan"
        )

        self.console.print()
        self.console.print(panel)

        try:
            choice = int(Prompt.ask("[bold]Select an option[/bold]"))
            if 1 <= choice <= len(options):
                return choice - 1
            elif choice == len(options) + 1:
                return -1
            else:
                self.print_error(_MSG_INVALID_SELECTION)
                return -1
        except ValueError:
            self.print_error("Please enter a valid number")
            return -1

    def prompt_tool_permission(self, tool_name: str, tool_description: str = None) -> Optional[str]:
        """
        Prompt user for permission to use a tool.

        Args:
            tool_name: Name of the tool
            tool_description: Optional description of the tool

        Returns:
            'allowed' if user grants permission for all future uses
            'denied' if user denies this and all future uses
            'once' if user grants permission for this time only
            None if user cancelled
        """
        # Pause any active status indicator to prevent visual interference
        self.pause_status_indicator()

        self.console.print()
        self.print_separator("─")
        self.console.print("\n[bold yellow]🔐 Tool Permission Request[/bold yellow]")
        self.console.print(f"\nThe assistant wants to use the tool: [bold cyan]{tool_name}[/bold cyan]")

        if tool_description:
            self.console.print(f"\n[dim]{tool_description}[/dim]")

        self.console.print("\n[bold]Please choose an option:[/bold]")
        self.console.print("  [bold green]1.[/bold green] Allow once - Run this time only")
        self.console.print("  [bold green]2.[/bold green] Allow always - Run this time and all future times")
        self.console.print("  [bold red]3.[/bold red] Deny - Don't run this time or in the future")
        self.console.print("  [bold yellow]4.[/bold yellow] Cancel")

        try:
            choice = Prompt.ask("\n[bold]Your choice[/bold]", choices=["1", "2", "3", "4"], default="1")

            if choice == "1":
                self.console.print("\n[bold green]✓[/bold green] Tool will run this time only")
                return 'once'
            elif choice == "2":
                self.console.print("\n[bold green]✓[/bold green] Tool permission granted for all future uses")
                return 'allowed'
            elif choice == "3":
                self.console.print("\n[bold red]✗[/bold red] Tool denied")
                return 'denied'
            else:  # "4" or invalid
                self.console.print("\n[yellow]Cancelled[/yellow]")
                return None

        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[yellow]Cancelled[/yellow]")
            return None
        finally:
            self.print_separator("─")
            # Resume status indicator after user interaction
            self.resume_status_indicator()

    def display_models(self, models: List[Dict]) -> Optional[str]:
        """
        Display available models and get user selection.

        Args:
            models: List of model dictionaries

        Returns:
            Selected model ID or None
        """
        if not models:
            self.print_error("No models available")
            return None

        # Create table
        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="cyan"
        )
        table.add_column("No.", style=_STYLE_BOLD_YELLOW, width=4)
        table.add_column("Model Name", style="cyan")
        table.add_column("Provider", style="green")
        table.add_column("Access Method", style="magenta")
        table.add_column("Streaming", style="blue", justify="center")

        for i, model in enumerate(models, 1):
            streaming = "✓" if model.get('response_streaming') else "✗"
            access_info = model.get('access_info', 'Unknown')
            table.add_row(
                str(i),
                model['name'],
                model['provider'],
                access_info,
                streaming
            )

        # Add quit option
        table.add_row(
            "Q",
            "[red]Quit[/red]",
            "",
            "",
            ""
        )

        # Display in panel
        panel = Panel(
            table,
            title="[bold magenta]📋 Available LLM Models[/bold magenta]",
            border_style="magenta"
        )

        self.console.print()
        self.console.print(panel)

        try:
            choice_str = Prompt.ask("\n[bold]Select a model (or Q to quit)[/bold]")

            # Check for quit
            if choice_str.upper() == 'Q':
                return 'QUIT'

            choice = int(choice_str)
            if 1 <= choice <= len(models):
                return models[choice - 1]['id']
            else:
                self.print_error(_MSG_INVALID_SELECTION)
                return None
        except ValueError:
            self.print_error("Please enter a valid number or Q to quit")
            return None

    def display_conversations(self, conversations: List[Dict]) -> Optional[int]:
        """
        Display existing conversations and get user selection.

        Args:
            conversations: List of conversation dictionaries

        Returns:
            Selected conversation ID or None
        """
        if not conversations:
            self.print_info("No existing conversations found")
            return None

        # Create table
        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="cyan"
        )
        table.add_column("No.", style=_STYLE_BOLD_YELLOW, width=4)
        table.add_column("Name", style="cyan")
        table.add_column("Model", style="green")
        table.add_column("Created", style="blue")
        table.add_column("Tokens", style="magenta", justify="right")

        for i, conv in enumerate(conversations, 1):
            created = datetime.fromisoformat(conv['created_at'])
            table.add_row(
                str(i),
                conv['name'],
                conv['model_id'][:40] + "..." if len(conv['model_id']) > 40 else conv['model_id'],
                created.strftime('%Y-%m-%d %H:%M'),
                str(conv['total_tokens'])
            )

        table.add_row(
            "[bold green]N[/bold green]",
            "[bold green]Start New Conversation[/bold green]",
            "-",
            "-",
            "-"
        )

        # Display in panel
        panel = Panel(
            table,
            title="[bold magenta]💬 Conversations[/bold magenta]",
            border_style="magenta"
        )

        self.console.print()
        self.console.print(panel)

        choice_str = Prompt.ask("\n[bold]Select an option[/bold]")

        # Check for "N" or "n" for new conversation
        if choice_str.lower() == 'n':
            return None

        # Try to parse as number
        try:
            choice = int(choice_str)
            if 1 <= choice <= len(conversations):
                return conversations[choice - 1]['id']
            else:
                self.print_error(_MSG_INVALID_SELECTION)
                return None
        except ValueError:
            self.print_error("Please enter a valid number or 'N' for new conversation")
            return None

    def display_message(self, role: str, content: str, timestamp: Optional[datetime] = None):
        """
        Display a chat message with markdown rendering for assistant responses.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            timestamp: Optional timestamp
        """
        role_config = {
            'user': {'emoji': '👤', 'style': 'bold cyan', 'border': 'cyan'},
            'assistant': {'emoji': '🤖', 'style': 'bold green', 'border': 'green'},
            'system': {'emoji': 'ℹ️', 'style': 'bold yellow', 'border': 'yellow'}
        }

        config = role_config.get(role.lower(), {'emoji': '💬', 'style': 'white', 'border': 'white'})

        # Format title
        title = f"[{config['style']}]{config['emoji']} {role.capitalize()}[/{config['style']}]"
        if timestamp:
            time_str = timestamp.strftime('%H:%M:%S')
            title += f" [dim]{time_str}[/dim]"

        # Render assistant messages as markdown for better formatting
        if role.lower() == 'assistant':
            rendered_content = Markdown(content)
        else:
            rendered_content = content

        # Create panel
        panel = Panel(
            rendered_content,
            title=title,
            title_align="left",
            border_style=config['border'],
            box=box.ROUNDED,
            padding=(1, 2)
        )

        self.console.print()
        self.console.print(panel)

    def display_conversation_history(self, messages: List[Dict]):
        """
        Display conversation history.

        Args:
            messages: List of message dictionaries
        """
        self.console.print()
        self.console.print(Panel(
            "[bold]Conversation History[/bold]",
            style=_STYLE_BOLD_MAGENTA,
            box=box.DOUBLE
        ))

        for msg in messages:
            timestamp = datetime.fromisoformat(msg['timestamp'])
            self.display_message(msg['role'], msg['content'], timestamp)

        self.console.print()
        self.print_separator("═")

    def display_conversation_info(self, conversation: Dict, token_count: int, max_tokens: int,
                                   attached_files: Optional[List[Dict]] = None,
                                   model_usage: Optional[List[Dict]] = None,
                                   detailed: bool = False,
                                   access_method: Optional[str] = None):
        """
        Display current conversation information.

        Args:
            conversation: Conversation dictionary
            token_count: Current token count
            max_tokens: Maximum token limit
            attached_files: Optional list of attached files
            model_usage: Optional list of per-model usage breakdowns
            detailed: If True, show full details including full instructions
            access_method: Optional access method description (e.g., 'AWS Bedrock', 'Ollama (http://...)')
        """
        token_percentage = (token_count / max_tokens) * 100

        # Create info table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style=_STYLE_BOLD_CYAN)
        table.add_column("Value", style="white")

        table.add_row("Conversation", conversation['name'])

        # Display friendly model name with full ID in detailed view
        model_id = conversation['model_id']
        friendly_name = extract_friendly_model_name(model_id)
        if detailed:
            # Show both friendly name and full model ID
            table.add_row("Current Model", f"{friendly_name}")
            table.add_row("Model ID", f"[dim]{model_id}[/dim]")
        else:
            table.add_row("Current Model", friendly_name)

        # Add access method if provided
        if access_method:
            table.add_row("Access Method", access_method)

        # Add instructions indicator
        if conversation.get('instructions'):
            table.add_row("Instructions", "[green]YES[/green]")
        else:
            table.add_row("Instructions", "[dim]NO[/dim]")

        table.add_row("Tokens", f"{token_count:,} / {max_tokens:,} ({token_percentage:.1f}%)")

        # Add API token usage
        tokens_sent = conversation.get('tokens_sent', 0)
        tokens_received = conversation.get('tokens_received', 0)
        total_api_tokens = tokens_sent + tokens_received
        table.add_row("Total API Usage", f"↑ {tokens_sent:,} sent | ↓ {tokens_received:,} received | Σ {total_api_tokens:,}")

        # Add attached files count
        if attached_files:
            total_file_tokens = sum(f.get('token_count', 0) for f in attached_files)
            table.add_row("Files", f"{len(attached_files)} attached ({total_file_tokens:,} tokens)")

        # Colour coding based on usage
        if token_percentage < 60:
            status = "[green]🟢 Good[/green]"
            bar_style = "green"
        elif token_percentage < 80:
            status = "[yellow]🟡 Moderate[/yellow]"
            bar_style = "yellow"
        else:
            status = "[red]🔴 High[/red]"
            bar_style = "red"

        # Visual token usage bar
        bar_length = 40
        filled_length = int(bar_length * token_count // max_tokens)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)

        table.add_row("Usage", f"[{bar_style}]{bar}[/{bar_style}] {status}")

        panel = Panel(
            table,
            title="[bold cyan]📊 Conversation Status[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        )

        self.console.print()
        self.console.print(panel)

        # Display full instructions if in detailed mode and instructions exist
        if detailed and conversation.get('instructions'):
            self.console.print()
            instructions_panel = Panel(
                conversation['instructions'],
                title="[bold cyan]📝 Conversation Instructions[/bold cyan]",
                border_style="cyan",
                box=box.ROUNDED
            )
            self.console.print(instructions_panel)

        # Display per-model usage breakdown if provided
        if model_usage and len(model_usage) > 0:
            self.console.print()
            self.display_model_usage_breakdown(model_usage)

    def display_model_usage_breakdown(self, model_usage: List[Dict]):
        """
        Display per-model token usage breakdown.

        Args:
            model_usage: List of model usage dictionaries
        """
        # Create model usage table
        usage_table = Table(title="Model Usage Breakdown", box=box.ROUNDED, show_header=True)
        usage_table.add_column("Model", style="cyan", no_wrap=True)
        usage_table.add_column("Input Tokens", justify="right", style="green")
        usage_table.add_column("Output Tokens", justify="right", style="yellow")
        usage_table.add_column("Total Tokens", justify="right", style="bold")

        for usage in model_usage:
            usage_table.add_row(
                usage['model_id'],
                f"{usage['input_tokens']:,}",
                f"{usage['output_tokens']:,}",
                f"{usage['total_tokens']:,}"
            )

        self.console.print(usage_table)

    def chat_prompt(self) -> Optional[str]:
        """
        Get user input for chat message.
        Supports multi-line input - press Enter twice to send.

        Returns:
            User message or None to exit
        """
        self.console.print()
        self.print_separator("─")

        # Display help text - conditionally include changemodel if enabled
        commands = "[bold]quit[/bold] | [bold]end[/bold] | [bold]history[/bold] | [bold]info[/bold] | " \
                   "[bold]export[/bold] | [bold]delete[/bold] | [bold]attach[/bold] | [bold]copy[/bold] | " \
                   "[bold]instructions[/bold] | [bold]deletefiles[/bold] | [bold]mcpaudit[/bold] | [bold]mcpservers[/bold]"

        if self.model_changing_enabled:
            commands += " | [bold]changemodel[/bold]"

        help_panel = Panel(
            f"[dim]Commands: {commands}\n"
            "Press [bold]Enter twice[/bold] to send your message[/dim]",
            border_style="dim",
            box=box.ROUNDED
        )
        self.console.print(help_panel)

        self.console.print("\n[bold cyan]💬 Your message:[/bold cyan]")

        lines = []
        empty_line_count = 0

        while True:
            try:
                line = input()
            except EOFError:
                # Handle Ctrl+D or EOF
                return None

            if line == "":
                empty_line_count += 1
                if empty_line_count >= 2:
                    # Double Enter pressed - send message
                    break
                lines.append(line)
            else:
                empty_line_count = 0
                lines.append(line)

        message = '\n'.join(lines).strip()

        # Check for commands
        if message.lower() in ['quit', 'exit', 'q']:
            return None
        elif message.lower() in ['end', 'endchat']:
            return 'END_CHAT'
        elif message.lower() in ['history', 'h']:
            return 'SHOW_HISTORY'
        elif message.lower() in ['info', 'i']:
            return 'SHOW_INFO'
        elif message.lower() in ['export', 'e']:
            return 'EXPORT_CONVERSATION'
        elif message.lower() in ['delete', 'd']:
            return 'DELETE_CONVERSATION'
        elif message.lower() in ['attach', 'a']:
            return 'ATTACH_FILES'
        elif message.lower() in ['mcpaudit', 'audit']:
            return 'MCP_AUDIT'
        elif message.lower() in ['mcpservers', 'servers', 's']:
            return 'MCP_SERVERS'
        elif message.lower() in ['changemodel', 'model', 'm']:
            return 'CHANGE_MODEL'
        elif message.lower() in ['instructions', 'inst']:
            return 'CHANGE_INSTRUCTIONS'
        elif message.lower() in ['deletefiles', 'df']:
            return 'DELETE_FILES'
        elif message.lower() in ['copy', 'c']:
            return 'COPY_LAST'

        return message

    def confirm(self, message: str) -> bool:
        """
        Ask for user confirmation.

        Args:
            message: Confirmation message

        Returns:
            True if confirmed, False otherwise
        """
        return Confirm.ask(f"[bold yellow]{message}[/bold yellow]")

    def wait_for_enter(self, message: str = "Press Enter to continue"):
        """
        Wait for user to press Enter.

        Args:
            message: Message to display
        """
        Prompt.ask(f"\n[dim]{message}[/dim]", default="")

    def print_farewell(self, version: str = None):
        """
        Print farewell message when exiting with SPARK branding.

        Args:
            version: Application version to display (optional)
        """
        # Get version from launch module if not provided
        if version is None:
            try:
                from dtSpark import launch
                version = launch.version()
            except ImportError:
                version = "X.X"

        # Get log path
        from dtPyAppFramework.process import ProcessManager
        log_path = ProcessManager().log_path

        # Build farewell content line by line
        farewell_content = Text()
        farewell_content.append("\n")

        # Line 1: *  .  * and DIGITAL-THOUGHT
        farewell_content.append("    *  .  *              ", style="bright_yellow")
        farewell_content.append(" DIGITAL-THOUGHT\n", style="bold bright_magenta")

        # Line 2: . \|/ . and Secure Personal AI Research Kit
        farewell_content.append("    . \\|/ .              ", style="yellow")
        farewell_content.append(" Secure Personal AI Research Kit\n", style="cyan")

        # Line 3: S P A R K and Version
        farewell_content.append("   *-- ", style="bright_yellow")
        farewell_content.append("S P A R K", style="bold bright_cyan")
        farewell_content.append(" --*     ", style="bright_yellow")
        farewell_content.append(f" Version {version}\n", style="green")

        # Line 4: . /|\ .
        farewell_content.append("    . /|\\ .              \n", style="yellow")

        # Line 5: *  .  * and Thankyou and Goodbye!
        farewell_content.append("     *  .  *             ", style="bright_yellow")
        farewell_content.append(" Thankyou and Goodbye!\n", style="bright_green")

        # Line 6: blank space and Log Path
        farewell_content.append("                          ", style="")
        farewell_content.append(f"Log Path: {log_path}\n", style="dim")

        farewell_content.append("")

        # Create panel
        farewell_panel = Panel(
            farewell_content,
            border_style="bright_cyan",
            box=box.HEAVY,
            padding=(0, 2)
        )

        self.console.print()
        self.console.print(farewell_panel)
        self.console.print()

    def display_mcp_status(self, mcp_manager):
        """
        Display MCP server connection status and tools.

        Args:
            mcp_manager: MCPManager instance
        """
        # Count connected servers
        connected_count = sum(1 for client in mcp_manager.clients.values() if client.connected)

        if connected_count == 0:
            self.print_warning("No MCP servers connected")
            return

        # Create table for server details
        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="green"
        )
        table.add_column("Server", style="cyan")
        table.add_column("Status", style="green", justify="center")
        table.add_column("Transport", style="blue")
        table.add_column("Tools", style="yellow", justify="right")

        # Get tools by server
        tools_by_server = {}
        if hasattr(mcp_manager, '_tools_cache') and mcp_manager._tools_cache:
            for tool in mcp_manager._tools_cache:
                server_name = tool.get('server', 'unknown')
                if server_name not in tools_by_server:
                    tools_by_server[server_name] = []
                tools_by_server[server_name].append(tool['name'])

        # Add rows for each server
        for name, client in mcp_manager.clients.items():
            status = "✓ Connected" if client.connected else "✗ Disconnected"
            transport = client.config.transport.upper()
            tool_count = len(tools_by_server.get(name, []))

            table.add_row(
                name,
                status if client.connected else f"[red]{status}[/red]",
                transport,
                str(tool_count)
            )

        # Display in panel
        total_tools = sum(len(tools) for tools in tools_by_server.values())
        panel = Panel(
            table,
            title=f"[bold green]🔧 MCP Servers ({connected_count} connected, {total_tools} tools)[/bold green]",
            border_style="green"
        )

        self.console.print()
        self.console.print(panel)

        # List tools for each server
        if tools_by_server:
            self.console.print()
            for server_name, tool_names in tools_by_server.items():
                tools_text = ", ".join([f"[cyan]{name}[/cyan]" for name in tool_names])
                self.console.print(f"  [bold]{server_name}[/bold]: {tools_text}")
            self.console.print()

    def display_bedrock_costs(self, costs_data: Dict):
        """
        Display AWS Bedrock usage costs.

        Args:
            costs_data: Dictionary containing cost information from CostTracker
        """
        if not costs_data:
            self.print_warning("No AWS Bedrock cost information available")
            return

        currency = costs_data.get('currency', 'USD')

        # Create content for the panel
        content_parts = []

        # Current Month section
        if 'current_month' in costs_data:
            current_month = costs_data['current_month']
            total = current_month.get('total', 0.0)
            breakdown = current_month.get('breakdown', {})

            content_parts.append(f"[bold cyan]Current Month:[/bold cyan] [yellow]${total:.2f} {currency}[/yellow]")

            if breakdown:
                # Calculate percentages and sort by cost
                breakdown_with_pct = []
                for model, cost in breakdown.items():
                    percentage = (cost / total * 100) if total > 0 else 0
                    breakdown_with_pct.append((model, cost, percentage))

                breakdown_with_pct.sort(key=lambda x: x[1], reverse=True)

                for model, cost, percentage in breakdown_with_pct:
                    content_parts.append(f"    • [cyan]{model}[/cyan]: [yellow]${cost:.2f}[/yellow] [dim]({percentage:.1f}%)[/dim]")

        # Last Month section
        if 'last_month' in costs_data:
            last_month = costs_data['last_month']
            total = last_month.get('total', 0.0)
            breakdown = last_month.get('breakdown', {})

            if content_parts:
                content_parts.append("")  # Add spacing

            content_parts.append(f"[bold cyan]Last Month:[/bold cyan] [yellow]${total:.2f} {currency}[/yellow]")

            if breakdown:
                # Calculate percentages and sort by cost
                breakdown_with_pct = []
                for model, cost in breakdown.items():
                    percentage = (cost / total * 100) if total > 0 else 0
                    breakdown_with_pct.append((model, cost, percentage))

                breakdown_with_pct.sort(key=lambda x: x[1], reverse=True)

                for model, cost, percentage in breakdown_with_pct:
                    content_parts.append(f"    • [cyan]{model}[/cyan]: [yellow]${cost:.2f}[/yellow] [dim]({percentage:.1f}%)[/dim]")

        # Last 24 Hours section
        if 'last_24h' in costs_data:
            last_24h = costs_data['last_24h']
            total = last_24h.get('total', 0.0)
            breakdown = last_24h.get('breakdown', {})

            if content_parts:
                content_parts.append("")  # Add spacing

            content_parts.append(f"[bold cyan]Last 24 Hours:[/bold cyan] [yellow]${total:.4f} {currency}[/yellow]")

            if breakdown:
                # Calculate percentages and sort by cost
                breakdown_with_pct = []
                for model, cost in breakdown.items():
                    percentage = (cost / total * 100) if total > 0 else 0
                    breakdown_with_pct.append((model, cost, percentage))

                breakdown_with_pct.sort(key=lambda x: x[1], reverse=True)

                for model, cost, percentage in breakdown_with_pct:
                    content_parts.append(f"    • [cyan]{model}[/cyan]: [yellow]${cost:.4f}[/yellow] [dim]({percentage:.1f}%)[/dim]")

        # Create panel
        content_text = "\n".join(content_parts)
        panel = Panel(
            content_text,
            title="[bold green]💰 AWS Bedrock Usage Costs[/bold green]",
            border_style="green"
        )

        self.console.print()
        self.console.print(panel)

    def display_anthropic_costs(self, costs_data: Dict):
        """
        Display Anthropic Direct API usage costs and budget status.

        Args:
            costs_data: Dictionary containing cost information from AnthropicService
        """
        if not costs_data:
            self.print_warning("No Anthropic cost information available")
            return

        # Create content for the panel
        content_parts = []

        # Current month spending
        current_month_spent = costs_data.get('current_month_spent', 0.0)
        total_spent = costs_data.get('total_spent', 0.0)
        budget_limit = costs_data.get('budget_limit', 0.0)
        budget_remaining = costs_data.get('budget_remaining', 0.0)
        budget_percentage = costs_data.get('budget_percentage', 0.0)
        budget_exceeded = costs_data.get('budget_exceeded', False)
        approaching_limit = costs_data.get('approaching_limit', False)
        current_month = costs_data.get('current_month', '')

        # Current month section
        content_parts.append(f"[bold cyan]Current Month ({current_month}):[/bold cyan]")
        content_parts.append(f"    • Spent: [yellow]${current_month_spent:.4f} USD[/yellow]")

        # Budget section
        if budget_limit > 0:
            content_parts.append("")
            content_parts.append("[bold cyan]Budget Status:[/bold cyan]")
            content_parts.append(f"    • Budget Limit: [yellow]${budget_limit:.2f} USD[/yellow]")

            if budget_exceeded:
                content_parts.append(f"    • Remaining: [red]${budget_remaining:.2f} USD (EXCEEDED)[/red]")
                content_parts.append(f"    • Usage: [red]{budget_percentage:.1f}%[/red] [red]⚠️ OVER BUDGET[/red]")
            elif approaching_limit:
                content_parts.append(f"    • Remaining: [yellow]${budget_remaining:.2f} USD[/yellow]")
                content_parts.append(f"    • Usage: [yellow]{budget_percentage:.1f}%[/yellow] [yellow]⚠️ APPROACHING LIMIT[/yellow]")
            else:
                content_parts.append(f"    • Remaining: [green]${budget_remaining:.2f} USD[/green]")
                content_parts.append(f"    • Usage: [green]{budget_percentage:.1f}%[/green]")

        # Total lifetime spending
        content_parts.append("")
        content_parts.append(f"[bold cyan]Total Lifetime Spending:[/bold cyan] [yellow]${total_spent:.4f} USD[/yellow]")

        # Usage count
        usage_count = costs_data.get('usage_count', 0)
        if usage_count > 0:
            content_parts.append(f"[bold cyan]API Calls:[/bold cyan] {usage_count} requests")

        # Create panel with appropriate colour based on budget status
        if budget_exceeded:
            border_colour = "red"
            title = "[bold red]💰 Anthropic API Costs - BUDGET EXCEEDED[/bold red]"
        elif approaching_limit:
            border_colour = "yellow"
            title = "[bold yellow]💰 Anthropic API Costs - APPROACHING LIMIT[/bold yellow]"
        else:
            border_colour = "green"
            title = "[bold green]💰 Anthropic API Costs[/bold green]"

        content_text = "\n".join(content_parts)
        panel = Panel(
            content_text,
            title=title,
            border_style=border_colour
        )

        self.console.print()
        self.console.print(panel)

    def display_aws_account_info(self, account_info: Dict):
        """
        Display AWS account and authentication information.

        Args:
            account_info: Dictionary containing AWS account information
        """
        if not account_info:
            self.print_warning("No AWS account information available")
            return

        # Create content for the panel
        content_parts = []

        # Identity/ARN
        if 'user_arn' in account_info:
            content_parts.append(f"[bold cyan]Authenticated as:[/bold cyan] [green]{account_info['user_arn']}[/green]")

        # Account ID
        if 'account_id' in account_info:
            content_parts.append(f"[bold cyan]Account:[/bold cyan] [yellow]{account_info['account_id']}[/yellow]")

        # Region
        if 'region' in account_info:
            content_parts.append(f"[bold cyan]Region:[/bold cyan] [yellow]{account_info['region']}[/yellow]")

        # Authentication Method
        if 'auth_method' in account_info and account_info['auth_method']:
            auth_method_display = "API Keys" if account_info['auth_method'] == 'api_keys' else "SSO Profile"
            content_parts.append(f"[bold cyan]Authentication:[/bold cyan] [magenta]{auth_method_display}[/magenta]")

        # Create panel
        content_text = "\n".join(content_parts)
        panel = Panel(
            content_text,
            title="[bold green]☁️  AWS Account Information[/bold green]",
            border_style="green"
        )

        self.console.print()
        self.console.print(panel)

    def display_application_info(self, user_guid: str):
        """
        Display application and user information.

        Args:
            user_guid: User's unique identifier
        """
        # Create content for the panel
        content_parts = []

        # User GUID
        content_parts.append(f"[bold cyan]User GUID:[/bold cyan] [blue]{user_guid}[/blue]")
        content_parts.append("")
        content_parts.append("[dim]This unique identifier is used for database isolation[/dim]")
        content_parts.append("[dim]and multi-user support when using shared databases.[/dim]")

        # Create panel
        content_text = "\n".join(content_parts)
        panel = Panel(
            content_text,
            title="[bold green]📋  Application Information[/bold green]",
            border_style="green"
        )

        self.console.print()
        self.console.print(panel)

    def display_tool_call(self, tool_name: str, tool_input: Dict):
        """
        Display a tool call during chat.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input parameters for the tool
        """
        # Format input nicely
        input_str = ", ".join([f"{k}={v}" for k, v in tool_input.items()])

        self.console.print(
            f"\n[dim]🔧 Calling tool:[/dim] [bold cyan]{tool_name}[/bold cyan]"
            f"[dim]({input_str})[/dim]"
        )

    def display_tool_result(self, tool_name: str, result: str, is_error: bool = False):  # noqa: S1172
        """
        Display a tool result during chat.

        Args:
            tool_name: Name of the tool that was called
            result: Result from the tool
            is_error: Whether the result is an error
        """
        if is_error:
            self.console.print(
                f"[dim]  ✗ Tool failed:[/dim] [red]{result}[/red]"
            )
        else:
            # Truncate long results
            display_result = result if len(result) <= 100 else result[:100] + "..."
            self.console.print(
                f"[dim]  ✓ Result:[/dim] [green]{display_result}[/green]"
            )

    def get_file_attachments(self, supported_extensions: str) -> List[Dict]:
        """
        Prompt user to attach files or directories to the conversation.

        Args:
            supported_extensions: Comma-separated list of supported file extensions

        Returns:
            List of dictionaries with 'path' and 'tags' keys
        """
        file_attachments = []

        # Ask if user wants to attach files
        attach_files = self.confirm("Would you like to attach files to this conversation?")

        if not attach_files:
            return file_attachments

        # Display supported file types
        self.console.print()
        info_panel = Panel(
            f"[cyan]Supported file types:[/cyan]\n{supported_extensions}\n\n"
            f"[yellow]You can provide file paths or directory paths.[/yellow]",
            title="[bold cyan]📎 File Attachments[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        )
        self.console.print(info_panel)
        self.console.print()

        # Get file/directory paths from user
        self.print_info("Enter file or directory paths one at a time (press Enter with empty path to finish)")

        while True:
            input_path = self.get_input("File/Directory path (or press Enter to finish)").strip()

            if not input_path:
                # User pressed Enter with empty input
                break

            # Check if path exists
            from pathlib import Path
            from dtSpark.files.manager import FileManager

            path = Path(input_path)

            if not path.exists():
                self.print_error(f"Path not found: {input_path}")
                continue

            # Handle directories
            if path.is_dir():
                self.print_info(f"Directory detected: {path.name}")

                # Ask if recursive
                recursive = self.confirm("  Include files from subdirectories?")

                # Scan directory
                try:
                    found_files = FileManager.scan_directory(str(path.absolute()), recursive=recursive)

                    if not found_files:
                        self.print_warning("  No supported files found in directory")
                        continue

                    self.print_success(f"  Found {len(found_files)} supported file(s)")

                    # Ask for tags for this batch
                    assign_tags = self.confirm("  Would you like to assign tags to these files?")
                    tags = None
                    if assign_tags:
                        tags_input = self.get_input("  Enter tags (comma-separated)").strip()
                        if tags_input:
                            tags = tags_input
                            self.print_success(f"  Tagged {len(found_files)} file(s) with: {tags}")

                    # Add all found files with the same tags
                    for file_path in found_files:
                        file_attachments.append({
                            'path': file_path,
                            'tags': tags
                        })

                except Exception as e:
                    self.print_error(f"  Error scanning directory: {e}")
                    continue

            # Handle individual files
            elif path.is_file():
                # Check if file is supported
                if not FileManager.is_supported(str(path)):
                    self.print_error(f"Unsupported file type: {path.suffix}")
                    continue

                # Ask for tags for this file
                assign_tags = self.confirm(f"  Assign tags to '{path.name}'?")
                tags = None
                if assign_tags:
                    tags_input = self.get_input("  Enter tags (comma-separated)").strip()
                    if tags_input:
                        tags = tags_input

                file_attachments.append({
                    'path': str(path.absolute()),
                    'tags': tags
                })

                tags_str = f" with tags: {tags}" if tags else ""
                self.print_success(f"Added: {path.name}{tags_str}")

            else:
                self.print_error(f"Invalid path type: {input_path}")

        if file_attachments:
            self.console.print()

            # Count files by tags
            tagged_count = sum(1 for f in file_attachments if f['tags'])
            untagged_count = len(file_attachments) - tagged_count

            self.print_success(f"Total files to attach: {len(file_attachments)}")
            if tagged_count > 0:
                self.print_info(f"  - {tagged_count} file(s) with tags")
            if untagged_count > 0:
                self.print_info(f"  - {untagged_count} file(s) without tags")
            self.console.print()

        return file_attachments

    def display_attached_files(self, files: List[Dict]):
        """
        Display attached files for a conversation.

        Args:
            files: List of file dictionaries from database
        """
        if not files:
            return

        # Create table for attached files
        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="blue"
        )
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Filename", style="cyan")
        table.add_column("Type", style="green", justify="center")
        table.add_column("Size", style="yellow", justify="right")
        table.add_column("Tokens", style="magenta", justify="right")
        table.add_column("Tags", style="bright_blue")

        for file_info in files:
            # Format file size
            size_bytes = file_info.get('file_size', 0)
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            # Format tags
            tags = file_info.get('tags', None)
            if tags:
                # Split tags and format them nicely
                tag_list = [t.strip() for t in tags.split(',') if t.strip()]
                tags_str = ', '.join([f"[bold]{tag}[/bold]" for tag in tag_list])
            else:
                tags_str = "[dim]-[/dim]"

            table.add_row(
                str(file_info['id']),
                file_info['filename'],
                file_info['file_type'],
                size_str,
                f"{file_info.get('token_count', 0):,}",
                tags_str
            )

        # Display in panel
        panel = Panel(
            table,
            title=f"[bold blue]📎 Attached Files ({len(files)})[/bold blue]",
            border_style="blue"
        )

        self.console.print()
        self.console.print(panel)

    def display_mcp_transactions(self, transactions: List[Dict], title: str = "MCP Tool Transactions"):
        """
        Display MCP transaction history for security monitoring.

        Args:
            transactions: List of transaction dictionaries
            title: Title for the display panel
        """
        if not transactions:
            self.print_info("No MCP transactions found")
            return

        # Create table for transactions
        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="yellow"
        )
        table.add_column("ID", style="dim", width=6)
        table.add_column("Timestamp", style="cyan", width=19)
        table.add_column("Tool", style="green")
        table.add_column("Server", style="blue")
        table.add_column("Status", style="white", justify="center", width=8)
        table.add_column("Time(ms)", style="magenta", justify="right", width=10)

        for txn in transactions:
            timestamp = datetime.fromisoformat(txn['transaction_timestamp'])
            status = "[red]ERROR[/red]" if txn['is_error'] else "[green]OK[/green]"
            exec_time = str(txn['execution_time_ms']) if txn['execution_time_ms'] else "-"

            table.add_row(
                str(txn['id']),
                timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                txn['tool_name'],
                txn['tool_server'],
                status,
                exec_time
            )

        # Display in panel
        panel = Panel(
            table,
            title=f"[bold yellow]🔐 {title} ({len(transactions)})[/bold yellow]",
            border_style="yellow"
        )

        self.console.print()
        self.console.print(panel)

    def display_mcp_transaction_details(self, transaction: Dict):
        """
        Display detailed information about a specific MCP transaction.

        Args:
            transaction: Transaction dictionary
        """
        import json

        # Create details table
        details_table = Table(show_header=False, box=None, padding=(0, 2))
        details_table.add_column("Label", style=_STYLE_BOLD_YELLOW)
        details_table.add_column("Value", style="white")

        timestamp = datetime.fromisoformat(transaction['transaction_timestamp'])
        status = "ERROR" if transaction['is_error'] else "SUCCESS"
        status_style = "red" if transaction['is_error'] else "green"

        details_table.add_row("Transaction ID", str(transaction['id']))
        details_table.add_row("Timestamp", timestamp.strftime('%Y-%m-%d %H:%M:%S'))
        details_table.add_row("Conversation ID", str(transaction['conversation_id']))
        details_table.add_row("Tool Name", transaction['tool_name'])
        details_table.add_row("Tool Server", transaction['tool_server'])
        details_table.add_row("Status", f"[{status_style}]{status}[/{status_style}]")
        if transaction['execution_time_ms']:
            details_table.add_row("Execution Time", f"{transaction['execution_time_ms']} ms")

        self.console.print()
        self.console.print(Panel(
            details_table,
            title="[bold yellow]🔐 Transaction Details[/bold yellow]",
            border_style="yellow"
        ))

        # User prompt
        self.console.print()
        self.console.print(Panel(
            transaction['user_prompt'],
            title="[bold cyan]User Prompt[/bold cyan]",
            border_style="cyan"
        ))

        # Tool input
        self.console.print()
        try:
            input_formatted = json.dumps(json.loads(transaction['tool_input']), indent=2)
        except ValueError:
            input_formatted = transaction['tool_input']

        self.console.print(Panel(
            input_formatted,
            title="[bold blue]Tool Input[/bold blue]",
            border_style="blue"
        ))

        # Tool response
        self.console.print()
        response_style = "red" if transaction['is_error'] else "green"
        response_text = transaction['tool_response']
        if len(response_text) > 500:
            response_text = response_text[:500] + "\n\n[... truncated for display ...]"

        self.console.print(Panel(
            response_text,
            title=f"[bold {response_style}]Tool Response[/bold {response_style}]",
            border_style=response_style
        ))

    def display_mcp_stats(self, stats: Dict):
        """
        Display MCP transaction statistics for security monitoring.

        Args:
            stats: Statistics dictionary
        """
        # Create stats table
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Metric", style=_STYLE_BOLD_YELLOW)
        stats_table.add_column("Value", style="white")

        stats_table.add_row("Total Transactions", f"{stats['total_transactions']:,}")
        stats_table.add_row("Errors", f"{stats['error_count']:,}")
        stats_table.add_row("Error Rate", f"{stats['error_rate']:.2f}%")

        self.console.print()
        self.console.print(Panel(
            stats_table,
            title="[bold yellow]📊 MCP Transaction Statistics[/bold yellow]",
            border_style="yellow"
        ))

        # Top tools
        if stats['top_tools']:
            self.console.print()
            tools_table = Table(
                show_header=True,
                header_style=_STYLE_BOLD_MAGENTA,
                box=box.ROUNDED,
                border_style="green"
            )
            tools_table.add_column("Tool", style="cyan")
            tools_table.add_column("Usage Count", style="green", justify="right")

            for tool in stats['top_tools']:
                tools_table.add_row(tool['tool'], str(tool['count']))

            self.console.print(Panel(
                tools_table,
                title="[bold green]🔧 Most Used Tools[/bold green]",
                border_style="green"
            ))

        # Top conversations
        if stats['top_conversations']:
            self.console.print()
            conv_table = Table(
                show_header=True,
                header_style=_STYLE_BOLD_MAGENTA,
                box=box.ROUNDED,
                border_style="cyan"
            )
            conv_table.add_column("Conversation", style="cyan")
            conv_table.add_column("Tool Calls", style="green", justify="right")

            for conv in stats['top_conversations']:
                conv_table.add_row(conv['conversation'], str(conv['count']))

            self.console.print(Panel(
                conv_table,
                title="[bold cyan]💬 Conversations with Most Tool Usage[/bold cyan]",
                border_style="cyan"
            ))

    def display_mcp_server_states(self, server_states: List[Dict]) -> None:
        """
        Display MCP server enabled/disabled states.

        Args:
            server_states: List of dicts with 'server_name' and 'enabled' keys
        """
        if not server_states:
            self.console.print("[yellow]No MCP servers available[/yellow]")
            return

        self.console.print()
        self.console.print("[bold cyan]═══ MCP Server States ═══[/bold cyan]")
        self.console.print()

        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="cyan"
        )
        table.add_column("Server Name", style="cyan")
        table.add_column("Status", justify="center")

        for state in server_states:
            status = "[green]✓ Enabled[/green]" if state['enabled'] else "[red]✗ Disabled[/red]"
            table.add_row(state['server_name'], status)

        self.console.print(table)

    def display_prompt_violation(self, inspection_result) -> None:
        """
        Display prompt security violation with details.

        Args:
            inspection_result: InspectionResult from prompt inspector
        """
        from rich.panel import Panel

        self.console.print()

        # Build violation message
        title = "[bold red]🛡️  Security Violation Detected[/bold red]"

        content_parts = []

        # Severity
        severity_colors = {
            'low': 'yellow',
            'medium': 'orange1',
            'high': 'red',
            'critical': 'bold red'
        }
        severity_color = severity_colors.get(inspection_result.severity, 'red')
        content_parts.append(f"[bold]Severity:[/bold] [{severity_color}]{inspection_result.severity.upper()}[/{severity_color}]")

        # Violation types
        if inspection_result.violation_types:
            violations_text = ', '.join(inspection_result.violation_types)
            content_parts.append(f"[bold]Violations:[/bold] {violations_text}")

        # Explanation
        content_parts.append(f"\n[bold]Details:[/bold]\n{inspection_result.explanation}")

        # Detected patterns (sample)
        if inspection_result.detected_patterns:
            sample = inspection_result.detected_patterns[:2]
            patterns_text = ', '.join(f'"{p}"' for p in sample)
            if len(inspection_result.detected_patterns) > 2:
                patterns_text += f" (+{len(inspection_result.detected_patterns) - 2} more)"
            content_parts.append(f"\n[bold]Detected Patterns:[/bold] {patterns_text}")

        # Detection method
        content_parts.append(f"\n[dim]Detection method: {inspection_result.inspection_method}[/dim]")

        # Create panel
        panel = Panel(
            "\n".join(content_parts),
            title=title,
            border_style="red",
            padding=(1, 2)
        )

        self.console.print(panel)
        self.console.print()
        self.console.print("[bold red]❌ This prompt has been blocked for security reasons.[/bold red]")
        self.console.print()

    def confirm_risky_prompt(self, inspection_result) -> bool:
        """
        Ask user to confirm they want to send a risky prompt.

        Args:
            inspection_result: InspectionResult from prompt inspector

        Returns:
            True if user confirms, False otherwise
        """
        from rich.panel import Panel

        self.console.print()

        # Build warning message
        title = "[bold yellow]⚠️  Security Warning[/bold yellow]"

        content_parts = []

        # Severity
        severity_colors = {
            'low': 'yellow',
            'medium': 'orange1',
            'high': 'red',
            'critical': 'bold red'
        }
        severity_color = severity_colors.get(inspection_result.severity, 'yellow')
        content_parts.append(f"[bold]Severity:[/bold] [{severity_color}]{inspection_result.severity.upper()}[/{severity_color}]")

        # Violation types
        if inspection_result.violation_types:
            violations_text = ', '.join(inspection_result.violation_types)
            content_parts.append(f"[bold]Potential Issues:[/bold] {violations_text}")

        # Explanation
        content_parts.append(f"\n[bold]Details:[/bold]\n{inspection_result.explanation}")

        # Detected patterns (sample)
        if inspection_result.detected_patterns:
            sample = inspection_result.detected_patterns[:2]
            patterns_text = ', '.join(f'"{p}"' for p in sample)
            if len(inspection_result.detected_patterns) > 2:
                patterns_text += f" (+{len(inspection_result.detected_patterns) - 2} more)"
            content_parts.append(f"\n[bold]Detected Patterns:[/bold] {patterns_text}")

        # Sanitised version available?
        if inspection_result.sanitised_prompt:
            content_parts.append("\n[green]ℹ A sanitised version of your prompt is available.[/green]")

        # Detection method
        content_parts.append(f"\n[dim]Detection method: {inspection_result.inspection_method}[/dim]")

        # Create panel
        panel = Panel(
            "\n".join(content_parts),
            title=title,
            border_style="yellow",
            padding=(1, 2)
        )

        self.console.print(panel)
        self.console.print()

        # Prompt for confirmation
        response = Prompt.ask(
            "[bold yellow]Do you want to proceed with this prompt?[/bold yellow]",
            choices=["y", "n"],
            default="n"
        )

        return response.lower() == 'y'

    def select_mcp_server(self, server_states: List[Dict], action: str = "toggle") -> Optional[str]:
        """
        Let user select an MCP server from a list.

        Args:
            server_states: List of dicts with 'server_name' and 'enabled' keys
            action: Action description (e.g., "toggle", "enable", "disable")

        Returns:
            Selected server name or None if cancelled
        """
        if not server_states:
            return None

        self.console.print(f"\n[bold cyan]Select a server to {action}:[/bold cyan]")
        for i, state in enumerate(server_states, 1):
            status = "[green]enabled[/green]" if state['enabled'] else "[red]disabled[/red]"
            self.console.print(f"  [{i}] {state['server_name']} ({status})")
        self.console.print(_MSG_CANCEL_OPTION)

        choice = self.get_input(_MSG_ENTER_CHOICE)
        try:
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(server_states):
                return server_states[idx - 1]['server_name']
            else:
                self.print_error(_MSG_INVALID_CHOICE)
                return None
        except ValueError:
            self.print_error(_MSG_INVALID_INPUT)
            return None

    # =========================================================================
    # Autonomous Actions Interface
    # =========================================================================

    def display_autonomous_actions_menu(self, failed_action_count: int = 0) -> str:
        """
        Display the autonomous actions submenu.

        Args:
            failed_action_count: Number of failed/disabled actions to show as indicator

        Returns:
            User's menu choice
        """
        menu_content = Text()

        # Show warning if there are failed actions
        if failed_action_count > 0:
            menu_content.append(f"  ⚠️  {failed_action_count} action(s) disabled due to failures\n\n", style="yellow")

        options = [
            ('1', 'List Actions', 'list'),
            ('2', 'Create New Action', 'create'),
            ('3', 'View Action Runs', 'runs'),
            ('4', 'Run Now (Manual)', 'run_now'),
            ('5', 'Enable/Disable Action', 'toggle'),
            ('6', 'Delete Action', 'delete'),
            ('7', 'Export Run Results', 'export'),
            ('8', 'Back to Main Menu', 'back')
        ]

        choice_map = {}
        for num, label, action in options:
            menu_content.append("  ", style="")
            menu_content.append(num, style="cyan")
            menu_content.append(f". {label}\n", style="")
            choice_map[num] = action

        menu_panel = Panel(
            menu_content,
            title="[bold bright_magenta]AUTONOMOUS ACTIONS[/bold bright_magenta]",
            border_style=_STYLE_BOLD_CYAN,
            box=box.HEAVY,
            padding=(0, 1)
        )

        self.console.print()
        self.console.print(menu_panel)
        self.console.print()

        choice = self.get_input("Select an option")
        return choice_map.get(choice, 'invalid')

    def select_action_creation_method(self) -> Optional[str]:
        """
        Prompt user to select action creation method.

        Returns:
            'manual', 'prompt_driven', or None if cancelled
        """
        self.console.print("\n[bold cyan]Create Autonomous Action[/bold cyan]")
        self.console.print("─" * 40)
        self.console.print("Choose creation method:")
        self.console.print("  [cyan]1.[/cyan] Manual Wizard (step-by-step)")
        self.console.print("  [cyan]2.[/cyan] Prompt-Driven (conversational with AI)")
        self.console.print("  [cyan]3.[/cyan] Cancel")

        choice = self.get_input("Select")
        if choice == "1":
            return "manual"
        elif choice == "2":
            return "prompt_driven"
        return None

    def display_actions_list(self, actions: List[Dict]):
        """
        Display a table of autonomous actions.

        Args:
            actions: List of action dictionaries
        """
        if not actions:
            self.print_info("No autonomous actions defined")
            return

        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="cyan"
        )
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Schedule", style="green")
        table.add_column("Context", style="yellow")
        table.add_column("Status", justify="center")
        table.add_column("Last Run", style="dim")
        table.add_column("Failures", justify="right")

        for action in actions:
            # Format schedule
            if action['schedule_type'] == 'one_off':
                config = action.get('schedule_config', {})
                run_date = config.get('run_date', 'N/A')
                if isinstance(run_date, str) and len(run_date) > 16:
                    run_date = run_date[:16]
                schedule = f"One-off: {run_date}"
            else:
                config = action.get('schedule_config', {})
                cron = config.get('cron_expression', 'N/A')
                schedule = f"Cron: {cron}"

            # Format status
            if action['is_enabled']:
                status = "[green]Enabled[/green]"
            else:
                status = "[red]Disabled[/red]"

            # Format last run
            last_run = action.get('last_run_at', 'Never')
            if last_run and last_run != 'Never':
                if isinstance(last_run, str) and len(last_run) > 16:
                    last_run = last_run[:16]

            # Failure count with warning colour
            failures = action.get('failure_count', 0)
            max_failures = action.get('max_failures', 3)
            if failures >= max_failures:
                failures_str = f"[red]{failures}/{max_failures}[/red]"
            elif failures > 0:
                failures_str = f"[yellow]{failures}/{max_failures}[/yellow]"
            else:
                failures_str = f"{failures}/{max_failures}"

            table.add_row(
                str(action['id']),
                action['name'][:30],
                schedule[:30],
                action.get('context_mode', 'fresh'),
                status,
                str(last_run) if last_run else 'Never',
                failures_str
            )

        panel = Panel(
            table,
            title="[bold cyan]Autonomous Actions[/bold cyan]",
            border_style="cyan"
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    def display_action_runs(self, runs: List[Dict], action_name: str = None):
        """
        Display a table of action runs.

        Args:
            runs: List of run dictionaries
            action_name: Optional action name for title
        """
        if not runs:
            self.print_info("No action runs found")
            return

        table = Table(
            show_header=True,
            header_style=_STYLE_BOLD_MAGENTA,
            box=box.ROUNDED,
            border_style="cyan"
        )
        table.add_column("Run ID", style="dim", justify="right")
        if not action_name:
            table.add_column("Action", style="cyan")
        table.add_column("Started", style="green")
        table.add_column("Status", justify="center")
        table.add_column("Duration", style="dim", justify="right")
        table.add_column("Tokens", style="yellow", justify="right")

        for run in runs:
            # Format status
            status = run.get('status', 'unknown')
            if status == 'completed':
                status_str = "[green]✓ Completed[/green]"
            elif status == 'failed':
                status_str = "[red]✗ Failed[/red]"
            elif status == 'running':
                status_str = "[yellow]⟳ Running[/yellow]"
            else:
                status_str = status

            # Calculate duration
            started = run.get('started_at')
            completed = run.get('completed_at')
            if started and completed:
                try:
                    if isinstance(started, str):
                        started = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    if isinstance(completed, str):
                        completed = datetime.fromisoformat(completed.replace('Z', '+00:00'))
                    duration = (completed - started).total_seconds()
                    duration_str = f"{duration:.1f}s"
                except (ValueError, TypeError):
                    duration_str = "N/A"
            else:
                duration_str = "N/A"

            # Format tokens
            input_tokens = run.get('input_tokens', 0)
            output_tokens = run.get('output_tokens', 0)
            tokens_str = f"{input_tokens:,}/{output_tokens:,}"

            # Format started time
            started_str = str(started)[:19] if started else 'N/A'

            row = [str(run['id'])]
            if not action_name:
                row.append(run.get('action_name', 'Unknown')[:20])
            row.extend([started_str, status_str, duration_str, tokens_str])

            table.add_row(*row)

        title = f"[bold cyan]Runs for '{action_name}'[/bold cyan]" if action_name else "[bold cyan]Recent Action Runs[/bold cyan]"
        panel = Panel(table, title=title, border_style="cyan")
        self.console.print()
        self.console.print(panel)
        self.console.print()

    def display_run_details(self, run: Dict):
        """
        Display detailed information about a single run.

        Args:
            run: Run dictionary
        """
        content_parts = []

        content_parts.append(f"[bold]Run ID:[/bold] {run['id']}")
        content_parts.append(f"[bold]Action:[/bold] {run.get('action_name', 'Unknown')}")
        content_parts.append(f"[bold]Status:[/bold] {run['status']}")
        content_parts.append(f"[bold]Started:[/bold] {run.get('started_at', 'N/A')}")
        content_parts.append(f"[bold]Completed:[/bold] {run.get('completed_at', 'N/A')}")
        content_parts.append(f"[bold]Input Tokens:[/bold] {run.get('input_tokens', 0):,}")
        content_parts.append(f"[bold]Output Tokens:[/bold] {run.get('output_tokens', 0):,}")

        if run.get('error_message'):
            content_parts.append(f"\n[bold red]Error:[/bold red] {run['error_message']}")

        if run.get('result_text'):
            content_parts.append("\n[bold]Result:[/bold]")
            # Truncate long results
            result = run['result_text']
            if len(result) > 1000:
                result = result[:1000] + "\n... (truncated)"
            content_parts.append(result)

        panel = Panel(
            "\n".join(content_parts),
            title="[bold cyan]Run Details[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    def select_action(self, actions: List[Dict], prompt: str = "Select an action") -> Optional[int]:
        """
        Let user select an action from a list.

        Args:
            actions: List of action dictionaries
            prompt: Prompt to display

        Returns:
            Selected action ID or None if cancelled
        """
        if not actions:
            self.print_warning("No actions available")
            return None

        self.console.print(f"\n[bold cyan]{prompt}:[/bold cyan]")
        for i, action in enumerate(actions, 1):
            status = "[green]enabled[/green]" if action['is_enabled'] else "[red]disabled[/red]"
            self.console.print(f"  [{i}] {action['name']} ({status})")
        self.console.print(_MSG_CANCEL_OPTION)

        choice = self.get_input(_MSG_ENTER_CHOICE)
        try:
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(actions):
                return actions[idx - 1]['id']
            else:
                self.print_error(_MSG_INVALID_CHOICE)
                return None
        except ValueError:
            self.print_error(_MSG_INVALID_INPUT)
            return None

    def select_run(self, runs: List[Dict], prompt: str = "Select a run") -> Optional[int]:
        """
        Let user select a run from a list.

        Args:
            runs: List of run dictionaries
            prompt: Prompt to display

        Returns:
            Selected run ID or None if cancelled
        """
        if not runs:
            self.print_warning("No runs available")
            return None

        self.console.print(f"\n[bold cyan]{prompt}:[/bold cyan]")
        for i, run in enumerate(runs, 1):
            status = run.get('status', 'unknown')
            started = str(run.get('started_at', ''))[:16]
            self.console.print(f"  [{i}] Run {run['id']} - {status} ({started})")
        self.console.print(_MSG_CANCEL_OPTION)

        choice = self.get_input(_MSG_ENTER_CHOICE)
        try:
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(runs):
                return runs[idx - 1]['id']
            else:
                self.print_error(_MSG_INVALID_CHOICE)
                return None
        except ValueError:
            self.print_error(_MSG_INVALID_INPUT)
            return None

    def select_export_format(self) -> Optional[str]:
        """
        Let user select an export format.

        Returns:
            'text', 'html', 'markdown', or None if cancelled
        """
        self.console.print("\n[bold cyan]Select export format:[/bold cyan]")
        self.console.print("  [1] Plain Text")
        self.console.print("  [2] HTML")
        self.console.print("  [3] Markdown")
        self.console.print(_MSG_CANCEL_OPTION)

        choice = self.get_input(_MSG_ENTER_CHOICE)
        format_map = {'1': 'text', '2': 'html', '3': 'markdown'}
        return format_map.get(choice)

    def create_action_wizard(self, available_models: List[Dict],
                             available_tools: List[Dict]) -> Optional[Dict]:
        """
        Interactive wizard for creating a new autonomous action.

        Args:
            available_models: List of available model dictionaries
            available_tools: List of available tool dictionaries

        Returns:
            Action configuration dictionary or None if cancelled
        """
        self.console.print("\n[bold cyan]═══ Create New Autonomous Action ═══[/bold cyan]\n")

        # Step 1: Name
        name = self.get_input("Action name (unique identifier)")
        if not name:
            self.print_error("Name is required")
            return None

        # Step 2: Description
        description = self.get_input("Description (what this action does)")
        if not description:
            description = name

        # Step 3: Action prompt
        self.console.print("\n[bold]Enter the action prompt:[/bold]")
        self.console.print("[dim]This is what the AI will execute each time the action runs.[/dim]")
        action_prompt = self.get_multiline_input("Action prompt")
        if not action_prompt:
            self.print_error("Action prompt is required")
            return None

        # Step 4: Model selection
        self.console.print("\n[bold cyan]Select a model:[/bold cyan]")
        if not available_models:
            self.print_error("No models available")
            return None

        for i, model in enumerate(available_models, 1):
            friendly_name = extract_friendly_model_name(model.get('id', ''))
            self.console.print(f"  [{i}] {friendly_name}")

        model_choice = self.get_input(_MSG_ENTER_CHOICE)
        try:
            model_idx = int(model_choice) - 1
            if model_idx < 0 or model_idx >= len(available_models):
                self.print_error("Invalid model selection")
                return None
            model_id = available_models[model_idx]['id']
        except ValueError:
            self.print_error(_MSG_INVALID_INPUT)
            return None

        # Step 5: Schedule type
        self.console.print("\n[bold cyan]Schedule type:[/bold cyan]")
        self.console.print("  [1] One-off (run once at specific time)")
        self.console.print("  [2] Recurring (run on schedule)")

        schedule_choice = self.get_input(_MSG_ENTER_CHOICE)
        if schedule_choice == '1':
            schedule_type = 'one_off'
            self.console.print("\n[dim]Enter date/time in format: YYYY-MM-DD HH:MM[/dim]")
            run_date_str = self.get_input("Run date/time")
            try:
                run_date = datetime.strptime(run_date_str, "%Y-%m-%d %H:%M")
                schedule_config = {'run_date': run_date.isoformat()}
            except ValueError:
                self.print_error("Invalid date format")
                return None
        elif schedule_choice == '2':
            schedule_type = 'recurring'
            self.console.print("\n[dim]Enter cron expression (minute hour day month day_of_week)[/dim]")
            self.console.print("[dim]Examples: '0 9 * * *' (daily at 9am), '0 0 * * 0' (weekly on Sunday)[/dim]")
            cron_expr = self.get_input("Cron expression")
            if not cron_expr:
                self.print_error("Cron expression is required")
                return None
            schedule_config = {'cron_expression': cron_expr}
        else:
            self.print_error("Invalid schedule type")
            return None

        # Step 6: Context mode
        self.console.print("\n[bold cyan]Context mode:[/bold cyan]")
        self.console.print("  [1] Fresh - Start with clean context each run")
        self.console.print("  [2] Cumulative - Carry context from previous runs")

        context_choice = self.get_input(_MSG_ENTER_CHOICE)
        context_mode = 'cumulative' if context_choice == '2' else 'fresh'

        # Step 7: Max failures
        max_failures_str = self.get_input("Max failures before auto-disable (default: 3)")
        try:
            max_failures = int(max_failures_str) if max_failures_str else 3
        except ValueError:
            max_failures = 3

        # Step 8: Max tokens
        self.console.print("\n[bold cyan]Max tokens for LLM response:[/bold cyan]")
        self.console.print("  Use higher values for tasks that generate large content (e.g., reports)")
        self.console.print("  Recommended: 4096 (simple tasks), 8192 (default), 16384 (large reports)")
        max_tokens_str = self.get_input("Max tokens (default: 8192)")
        try:
            max_tokens = int(max_tokens_str) if max_tokens_str else 8192
            # Enforce reasonable limits
            max_tokens = max(1024, min(max_tokens, 32000))
        except ValueError:
            max_tokens = 8192

        # Step 9: Tool selection
        selected_tools = []
        if available_tools:
            self.console.print("\n[bold cyan]Select tools to allow (enter numbers separated by commas, or 'none'):[/bold cyan]")
            for i, tool in enumerate(available_tools, 1):
                server = tool.get('server', 'unknown')
                self.console.print(f"  [{i}] {tool['name']} ({server})")

            tools_input = self.get_input("Tool numbers (e.g., 1,3,5) or 'none'")
            if tools_input.lower() != 'none' and tools_input:
                try:
                    indices = [int(x.strip()) - 1 for x in tools_input.split(',')]
                    for idx in indices:
                        if 0 <= idx < len(available_tools):
                            tool = available_tools[idx]
                            selected_tools.append({
                                'tool_name': tool['name'],
                                'server_name': tool.get('server'),
                                'permission_state': 'allowed'
                            })
                except ValueError:
                    self.print_warning("Invalid tool selection, proceeding without tools")

        # Confirm
        self.console.print("\n[bold cyan]═══ Action Summary ═══[/bold cyan]")
        self.console.print(f"  Name: {name}")
        self.console.print(f"  Description: {description}")
        self.console.print(f"  Model: {extract_friendly_model_name(model_id)}")
        self.console.print(f"  Schedule: {schedule_type} - {schedule_config}")
        self.console.print(f"  Context Mode: {context_mode}")
        self.console.print(f"  Max Failures: {max_failures}")
        self.console.print(f"  Max Tokens: {max_tokens}")
        self.console.print(f"  Tools: {len(selected_tools)}")
        self.console.print()

        if not self.confirm("Create this action?"):
            return None

        return {
            'name': name,
            'description': description,
            'action_prompt': action_prompt,
            'model_id': model_id,
            'schedule_type': schedule_type,
            'schedule_config': schedule_config,
            'context_mode': context_mode,
            'max_failures': max_failures,
            'max_tokens': max_tokens,
            'tool_permissions': selected_tools
        }

    def display_creation_conversation_message(
        self,
        role: str,
        content: str,
        is_final: bool = False
    ) -> None:
        """
        Display a message in the action creation conversation.

        Args:
            role: Message role ('user' or 'assistant')
            content: Message content text
            is_final: Whether this is the final message in the conversation
        """
        if role == "user":
            self.console.print(f"\n[bold purple]You:[/bold purple] {content}")
        else:
            self.console.print(f"\n[bold green]Assistant:[/bold green]")
            self.console.print(Markdown(content))

        if is_final:
            self.console.print("─" * 40)

    def display_creation_tool_call(self, tool_name: str, result: dict) -> None:
        """
        Display a tool call result during action creation.

        Args:
            tool_name: Name of the tool that was called
            result: Result dictionary from the tool
        """
        self.console.print(f"\n[dim]↳ Called {tool_name}[/dim]")

        if tool_name == 'list_available_tools':
            count = result.get('count', 0)
            self.console.print(f"[dim]  Found {count} available tools[/dim]")

        elif tool_name == 'validate_schedule':
            if result.get('valid'):
                human_readable = result.get('human_readable', 'Valid')
                self.console.print(f"[dim]  Schedule: {human_readable}[/dim]")
            else:
                error = result.get('error', 'Invalid')
                self.console.print(f"[yellow]  Validation failed: {error}[/yellow]")

        elif tool_name == 'create_autonomous_action':
            if result.get('success'):
                name = result.get('name', 'Action')
                self.console.print(f"[green]  ✓ Created action: {name}[/green]")
            else:
                error = result.get('error', 'Creation failed')
                self.console.print(f"[red]  ✗ Error: {error}[/red]")

    def display_creation_prompt_header(self) -> None:
        """Display the header for prompt-driven action creation."""
        header = Panel(
            "[bold]Describe the task you want to schedule.[/bold]\n"
            "The AI will help you configure the action by asking clarifying questions.\n"
            "[dim]Type 'cancel' at any time to abort.[/dim]",
            title="[bold cyan]Prompt-Driven Action Creation[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        )
        self.console.print()
        self.console.print(header)
        self.console.print()
