import os
import socket
import sys
import logging
import time
import subprocess
from datetime import datetime
from typing import List, Optional

from argparse import ArgumentParser

from dtPyAppFramework.misc.packaging import load_module_package, ModulePackage
from dtPyAppFramework.application import AbstractApp
from dtPyAppFramework.settings import Settings
from dtPyAppFramework.paths import ApplicationPaths
from dtPyAppFramework.process import ProcessManager
from dtPyAppFramework.resources import ResourceManager

# Add the parent 'src' directory to sys.path to enable relative imports
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

dir_path = os.path.dirname(os.path.realpath(__file__))
# _metadata.yaml is in the parent directory (dtSpark/)
parent_dir = os.path.dirname(dir_path)
module_package: ModulePackage = load_module_package(os.path.join(parent_dir, '_metadata.yaml'))

# Force OpenTelemetry to use contextvars context
os.environ['OTEL_PYTHON_CONTEXT'] = 'contextvars_context'

def version():
    """Returns the version of the module."""
    return module_package.version

def description():
    """Returns the version of the module."""
    return module_package.description

def agent_type():
    return module_package.short_name

def full_name():
    return module_package.full_name

def agent_name():
    return socket.gethostname()

def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to system clipboard using platform-specific commands.

    Args:
        text: Text to copy to clipboard

    Returns:
        True if successful, False otherwise
    """
    try:
        if sys.platform == 'win32':
            # Windows: use clip.exe
            process = subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True)
            process.communicate(text.encode('utf-16le'))
            return process.returncode == 0
        elif sys.platform == 'darwin':
            # macOS: use pbcopy
            process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            process.communicate(text.encode('utf-8'))
            return process.returncode == 0
        else:
            # Linux: try xclip or xsel
            try:
                process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
                return process.returncode == 0
            except FileNotFoundError:
                try:
                    process = subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE)
                    process.communicate(text.encode('utf-8'))
                    return process.returncode == 0
                except FileNotFoundError:
                    return False
    except Exception as e:
        logging.error(f"Failed to copy to clipboard: {e}")
        return False

# Common string constants (SonarCloud S1192)
_SETTING_BEDROCK_COST_TRACKING = 'llm_providers.aws_bedrock.cost_tracking.enabled'
_SETTING_COST_TRACKING = 'aws.cost_tracking.enabled'
_SETTING_OLLAMA_ENABLED = 'llm_providers.ollama.enabled'
_DEFAULT_RUNNING_DIR = "./running"
_PROMPT_ACCESS_MODE = "Select access mode"
_MSG_NO_MODELS = "No models available"
_MSG_MANAGED_CONVERSATION = "This conversation is managed by configuration"
_MSG_DELETE_CANCELLED = "Delete operation cancelled"

class AWSBedrockCLI(AbstractApp):
    def __init__(self):
        super().__init__(short_name=agent_type(), full_name=full_name(), version=version(),
                         description='AWS Bedrock CLI for GenAI Chat',
                         console_app=True)
        self.settings: Settings = None
        self.authenticator = None
        self.bedrock_service = None
        self.database = None
        self.conversation_manager = None
        self.cli = None
        self.mcp_manager = None
        self.auth_failed = False
        self.action_scheduler = None
        self.execution_queue = None
        self.action_executor = None
        self.configured_model_id = None  # Model locked via config.yaml
        self.configured_provider = None  # Provider for mandatory model
        self.cost_tracker = None  # Cost tracker for Bedrock usage
        self.token_manager = None  # Token manager for usage limit enforcement

    def _get_nested_setting(self, key: str, default=None):
        """
        Get a nested setting value, trying both dot notation and dict navigation.

        The dtPyAppFramework Settings class may not fully support dot notation
        for deeply nested YAML keys. This method provides a fallback.

        Args:
            key: Dot-separated key (e.g., 'llm_providers.aws_bedrock.enabled')
            default: Default value if not found

        Returns:
            The setting value, or default if not found
        """
        # First try direct dot notation access
        value = self.settings.get(key, None)
        if value is not None:
            return value


        # Fallback: Navigate the dict manually
        parts = key.split('.')
        if len(parts) > 1:
            # Get the top-level key
            top_level = self.settings.get(parts[0], None)
            if isinstance(top_level, dict):
                # Navigate through remaining parts
                current = top_level
                for part in parts[1:]:
                    if isinstance(current, dict):
                        current = current.get(part, None)
                    else:
                        current = None
                        break
                if current is not None:
                    return current

        return default

    def _load_database_configuration(self):
        """
        Load database configuration and prompt for credentials if needed.

        Returns:
            Tuple of (db_type, credentials)
        """
        from dtSpark.database.backends import DatabaseCredentials
        from dtSpark.database.credential_prompt import prompt_and_validate_credentials

        # Get database type from configuration
        db_type = self.settings.get('database.type', 'sqlite')
        logging.info(f"Database type: {db_type}")

        # Load credentials from configuration
        if db_type.lower() == 'sqlite':
            db_path = self.settings.get('database.sqlite.path', './data/conversations.db')
            # Expand path relative to current working directory (app root)
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(db_path)

            credentials = DatabaseCredentials(path=db_path)
            logging.info(f"SQLite database path: {db_path}")

        else:
            # Remote database - load credentials from config
            db_config_key = f'database.{db_type.lower()}'

            credentials = DatabaseCredentials(
                host=self.settings.get(f'{db_config_key}.host'),
                port=self.settings.get(f'{db_config_key}.port'),
                database=self.settings.get(f'{db_config_key}.database'),
                username=self.settings.get(f'{db_config_key}.username'),
                password=self.settings.get(f'{db_config_key}.password'),
                ssl=self.settings.get(f'{db_config_key}.ssl', False),
                driver=self.settings.get(f'{db_config_key}.driver')  # For MSSQL
            )

            # Check if credentials need prompting (any null values)
            needs_prompt = not all([
                credentials.host,
                credentials.database,
                credentials.username,
                credentials.password
            ])

            if needs_prompt:
                logging.info("Database credentials incomplete - prompting user")
                credentials = prompt_and_validate_credentials(db_type, credentials, max_retries=3)

                if credentials is None:
                    raise RuntimeError(
                        f"Failed to establish database connection after multiple attempts. "
                        f"Please check your configuration in config.yaml and ensure the database server is accessible."
                    )

            logging.info(f"Database configured: {db_type} at {credentials.host}:{credentials.port}/{credentials.database}")

        return db_type, credentials

    def _build_model_context_limits(self) -> dict:
        """
        Build model_context_limits dictionary from Settings object.

        Settings uses dot notation, so we need to manually construct the
        nested dictionary structure that ContextLimitResolver expects.

        Returns:
            Dictionary with provider sections containing model limits
        """
        limits = {}

        # Define providers and their known models
        providers_and_models = {
            'anthropic': [
                'claude-opus-4', 'claude-sonnet-4', 'claude-opus-4.5', 'claude-sonnet-4.5',
                'claude-3-5-sonnet', 'claude-3-5-haiku', 'claude-3-opus', 'claude-3-sonnet',
                'claude-3-haiku', 'default'
            ],
            'aws_bedrock': [
                'amazon.titan-text-express', 'amazon.titan-text-lite',
                'meta.llama3-1', 'mistral.mistral-large', 'default'
            ],
            'ollama': [
                'llama3.2', 'mistral', 'codellama', 'default'
            ]
        }

        # Debug: Test if we can access any model_context_limits values
        test_key = 'model_context_limits.anthropic.claude-sonnet-4.context_window'
        test_value = self.settings.get(test_key, None)
        logging.info(f"Settings test: '{test_key}' = {test_value}")

        for provider, models in providers_and_models.items():
            provider_limits = {}

            for model in models:
                # Build the dot-notation keys for this model
                base_key = f'model_context_limits.{provider}.{model}'

                context_window = self.settings.get(f'{base_key}.context_window', None)
                max_output = self.settings.get(f'{base_key}.max_output', None)

                # Log attempts for debugging
                if model in ['claude-sonnet-4', 'default']:
                    logging.info(f"Settings lookup: '{base_key}.context_window' = {context_window}")

                if context_window is not None and max_output is not None:
                    provider_limits[model] = {
                        'context_window': int(context_window),
                        'max_output': int(max_output)
                    }
                    logging.debug(f"Loaded model limits: {provider}.{model} = {context_window}/{max_output}")

            if provider_limits:
                limits[provider] = provider_limits
                logging.info(f"Loaded {len(provider_limits)} model configurations for provider '{provider}'")

        # Try global default
        global_context = self.settings.get('model_context_limits.default.context_window', None)
        global_output = self.settings.get('model_context_limits.default.max_output', None)
        if global_context is not None and global_output is not None:
            limits['default'] = {
                'context_window': int(global_context),
                'max_output': int(global_output)
            }

        if not limits:
            logging.warning("No model_context_limits found in settings, using hardcoded defaults")

        return limits

    def _check_daemon_running(self) -> bool:
        """
        Check if a daemon process is currently running.

        Uses the PID file to determine if a daemon is active.
        This is used to decide whether the UI should start its own
        scheduler or defer to the daemon.

        Returns:
            True if daemon is running, False otherwise
        """
        try:
            from dtSpark.daemon.pid_file import PIDFile

            # Get PID file path from settings (same as daemon uses)
            pid_file_path = self.settings.get('daemon.pid_file', './daemon.pid')
            pid_file = PIDFile(pid_file_path)

            is_running = pid_file.is_running()

            if is_running:
                pid = pid_file.read_pid()
                logging.info(f"Daemon detected running with PID {pid}")
            else:
                logging.debug("No daemon running (PID file absent or process not found)")

            return is_running

        except ImportError:
            logging.debug("Daemon module not available - assuming no daemon running")
            return False
        except Exception as e:
            logging.warning(f"Error checking daemon status: {e} - assuming no daemon running")
            return False

    def initialise_singletons(self):
        """Initialise application components."""
        import asyncio
        from dtSpark.aws import AWSAuthenticator
        from dtSpark.aws import BedrockService
        from dtSpark.database import ConversationDatabase
        from dtSpark.conversation_manager import ConversationManager
        from dtSpark.cli_interface import CLIInterface
        from dtSpark.mcp_integration import MCPManager
        from dtSpark.aws import CostTracker
        from dtSpark.limits import TokenManager
        from dtSpark.llm import LLMManager, OllamaService, AnthropicService
        from dtSpark.safety import PromptInspector, ViolationLogger
        from dtSpark.safety.llm_service import InspectionLLMService

        logging.info('Initialising application components')

        # Initialise CLI interface
        self.cli = CLIInterface()

        # Display splash screen with metadata
        self.cli.print_splash_screen(
            full_name=full_name(),
            description=module_package.description,
            version=version()
        )

        # Create progress tracker
        progress = self.cli.create_progress()

        with progress:
            # Task 1: Load configuration
            task_config = progress.add_task("[cyan]Loading configuration...", total=100)
            # AWS Bedrock configuration - now under llm_providers.aws_bedrock
            # Uses _get_nested_setting helper which handles both dot notation and dict navigation
            # Also checks legacy 'aws.' paths for backwards compatibility
            aws_region = self._get_nested_setting('llm_providers.aws_bedrock.region', None)
            if aws_region is None:
                aws_region = self.settings.get('aws.region', 'us-east-1')

            aws_profile = self._get_nested_setting('llm_providers.aws_bedrock.sso_profile', None)
            if aws_profile is None:
                aws_profile = self.settings.get('aws.sso_profile', 'default')

            bedrock_request_timeout = self.settings.get('bedrock.request_timeout', 300)

            # AWS API key configuration (optional - takes precedence over SSO if provided)
            aws_access_key_id = self._get_nested_setting('llm_providers.aws_bedrock.access_key_id', None)
            if aws_access_key_id is None:
                aws_access_key_id = self.settings.get('aws.access_key_id', None)

            aws_secret_access_key = self._get_nested_setting('llm_providers.aws_bedrock.secret_access_key', None)
            if aws_secret_access_key is None:
                aws_secret_access_key = self.settings.get('aws.secret_access_key', None)

            aws_session_token = self._get_nested_setting('llm_providers.aws_bedrock.session_token', None)
            if aws_session_token is None:
                aws_session_token = self.settings.get('aws.session_token', None)

            # Configure CLI cost tracking display
            cost_tracking_enabled = self._get_nested_setting(_SETTING_BEDROCK_COST_TRACKING, None)
            if cost_tracking_enabled is None:
                cost_tracking_enabled = self.settings.get(_SETTING_COST_TRACKING, False)
            self.cli.cost_tracking_enabled = cost_tracking_enabled
            self.cli.actions_enabled = self._get_nested_setting('autonomous_actions.enabled', False)
            self.cli.new_conversations_allowed = self._get_nested_setting('predefined_conversations.allow_new_conversations', True)

            progress.update(task_config, advance=100)

            # Task 2: Initialise LLM Providers
            task_llm = progress.add_task("[cyan]Initialising LLM providers...", total=100)

            self.llm_manager = LLMManager()
            provider_count = 0

            # Check AWS Bedrock configuration using helper that handles both dot notation and dict navigation
            aws_enabled_raw = self._get_nested_setting('llm_providers.aws_bedrock.enabled', None)
            logging.info(f"AWS Bedrock enabled raw value: {aws_enabled_raw} (type: {type(aws_enabled_raw).__name__ if aws_enabled_raw is not None else 'NoneType'})")

            # Handle missing or various value types
            if aws_enabled_raw is None:
                # Setting not found via any method - check if other providers are enabled
                ollama_check = self._get_nested_setting(_SETTING_OLLAMA_ENABLED, False)
                anthropic_check = self._get_nested_setting('llm_providers.anthropic.enabled', False)
                if ollama_check or anthropic_check:
                    # Other providers configured, don't default to AWS
                    logging.info("AWS Bedrock not explicitly configured, other providers available - skipping AWS")
                    aws_enabled = False
                else:
                    # No providers configured - default to AWS for backwards compatibility
                    logging.warning("No LLM provider explicitly configured - defaulting to AWS Bedrock")
                    aws_enabled = True
            elif isinstance(aws_enabled_raw, str):
                # Handle string 'false'/'true' from YAML parsing
                aws_enabled = aws_enabled_raw.lower() not in ('false', 'no', '0', 'off', '')
            else:
                aws_enabled = bool(aws_enabled_raw)

            logging.info(f"AWS Bedrock final enabled state: {aws_enabled}")

            if aws_enabled:
                # Task 2a: AWS Authentication
                progress.update(task_llm, advance=10, description="[cyan]Authenticating with AWS...")

                # Suppress stdout/stderr during authentication
                import contextlib
                with contextlib.redirect_stdout(open(os.devnull, 'w')), \
                     contextlib.redirect_stderr(open(os.devnull, 'w')):
                    self.authenticator = AWSAuthenticator(
                        profile_name=aws_profile,
                        region=aws_region,
                        bedrock_request_timeout=bedrock_request_timeout,
                        access_key_id=aws_access_key_id,
                        secret_access_key=aws_secret_access_key,
                        session_token=aws_session_token
                    )
                    auth_result = self.authenticator.authenticate()

                if not auth_result:
                    progress.stop()
                    self.cli.print_warning("Failed to authenticate with AWS Bedrock")

                    # Check if Ollama is available as fallback
                    ollama_enabled = self._get_nested_setting(_SETTING_OLLAMA_ENABLED, False)
                    if not ollama_enabled:
                        self.cli.print_error("AWS authentication required (Ollama not configured)")
                        self.cli.print_info(f"Run: aws sso login --profile {aws_profile}")
                        self.auth_failed = True
                        return
                    else:
                        self.cli.print_info("Continuing with Ollama only...")
                        aws_enabled = False
                else:
                    # AWS auth succeeded, initialize Bedrock
                    progress.update(task_llm, advance=20, description="[cyan]Initialising AWS Bedrock...")
                    bedrock_client = self.authenticator.get_client('bedrock')
                    bedrock_runtime_client = self.authenticator.get_client('bedrock-runtime')
                    bedrock_service = BedrockService(bedrock_client, bedrock_runtime_client)
                    self.llm_manager.register_provider(bedrock_service)
                    provider_count += 1
                    logging.info("AWS Bedrock provider registered")
            else:
                # AWS disabled - skip AWS progress (10% auth + 20% init = 30%)
                progress.update(task_llm, advance=30)

            progress.update(task_llm, advance=20, description="[cyan]Checking Ollama...")

            # Check Ollama configuration
            ollama_enabled = self._get_nested_setting(_SETTING_OLLAMA_ENABLED, False)
            if ollama_enabled:
                try:
                    ollama_url = self._get_nested_setting(
                        'llm_providers.ollama.base_url',
                        'http://localhost:11434'
                    )
                    # Get SSL verification setting (default True, set to False for self-signed certs)
                    ollama_verify_ssl = self._get_nested_setting(
                        'llm_providers.ollama.verify_ssl',
                        True
                    )
                    ollama_service = OllamaService(
                        base_url=ollama_url,
                        verify_ssl=ollama_verify_ssl
                    )
                    self.llm_manager.register_provider(ollama_service)
                    provider_count += 1
                    logging.info("Ollama provider registered")
                except Exception as e:
                    logging.error(f"Failed to initialise Ollama: {e}")

            progress.update(task_llm, advance=20, description="[cyan]Checking Anthropic...")

            # Check Anthropic configuration
            anthropic_enabled = self._get_nested_setting('llm_providers.anthropic.enabled', False)
            if anthropic_enabled:
                try:
                    api_key = self._get_nested_setting('llm_providers.anthropic.api_key', '')

                    # Get default max_tokens from bedrock config
                    default_max_tokens = self.settings.get('bedrock.max_tokens', 8192)

                    # Get rate limit configuration
                    rate_limit_max_retries = self._get_nested_setting('llm_providers.anthropic.rate_limit_max_retries', 5)
                    rate_limit_base_delay = self._get_nested_setting('llm_providers.anthropic.rate_limit_base_delay', 2.0)

                    # Allow empty API key if environment variable is set
                    if not api_key:
                        api_key = os.environ.get('ANTHROPIC_API_KEY')

                    if api_key:
                        anthropic_service = AnthropicService(
                            api_key=api_key,
                            default_max_tokens=default_max_tokens,
                            rate_limit_max_retries=rate_limit_max_retries,
                            rate_limit_base_delay=rate_limit_base_delay
                        )
                        self.llm_manager.register_provider(anthropic_service)
                        provider_count += 1
                        logging.info("Anthropic Direct API provider registered")
                    else:
                        logging.warning("Anthropic enabled but no API key provided")
                except Exception as e:
                    logging.error(f"Failed to initialise Anthropic: {e}")

            progress.update(task_llm, advance=30)

            # Verify at least one provider is available
            if provider_count == 0:
                progress.stop()
                self.cli.print_error("No LLM providers available")
                self.cli.print_info("Configure AWS Bedrock or Ollama in config.yaml")
                raise RuntimeError("No LLM providers available")

            logging.info(f"Initialised {provider_count} LLM provider(s)")

            # Set bedrock_service for backward compatibility
            self.bedrock_service = self.llm_manager.get_active_service()

            # Task 3.5: Retrieve Bedrock cost information (silently, display later)
            # Only if cost tracking is enabled in configuration
            cost_tracking_enabled = self._get_nested_setting(_SETTING_BEDROCK_COST_TRACKING, None)
            if cost_tracking_enabled is None:
                cost_tracking_enabled = self.settings.get(_SETTING_COST_TRACKING, False)
            if cost_tracking_enabled and self.authenticator:
                task_costs = progress.add_task("[cyan]Retrieving usage costs...", total=100)
                self.bedrock_costs = None
                try:
                    cost_explorer_client = self.authenticator.get_client('ce')
                    self.cost_tracker = CostTracker(cost_explorer_client)
                    self.bedrock_costs = self.cost_tracker.get_bedrock_costs()
                    progress.update(task_costs, advance=100)
                except Exception as e:
                    logging.debug(f"Could not retrieve cost information: {e}")
                    progress.update(task_costs, advance=100)
                    # Continue silently - cost tracking is optional
            elif cost_tracking_enabled and not self.authenticator:
                logging.debug("Cost tracking enabled but AWS not configured - skipping")
            else:
                logging.debug("Cost tracking disabled in configuration")
                self.bedrock_costs = None
                self.cost_tracker = None

            # Task 3.8: Initialise or retrieve user GUID
            task_user = progress.add_task("[cyan]Initialising user identity...", total=100)
            import uuid

            # Get or create user GUID from secret manager
            user_guid = self.settings.secret_manager.get_secret('user_guid', None, 'User_Local_Store')
            if user_guid is None:
                # Generate new GUID for this user
                user_guid = str(uuid.uuid4())
                # Store in secret manager for future use
                self.settings.secret_manager.set_secret('user_guid', user_guid, 'User_Local_Store')
                logging.info(f"Generated new user GUID: {user_guid}")
            else:
                logging.info(f"Using existing user GUID: {user_guid}")

            self.user_guid = user_guid
            progress.update(task_user, advance=100)

            # Task 4: Initialise database
            task_db = progress.add_task("[cyan]Initialising conversation database...", total=100)

            # Get database configuration
            db_type, db_credentials = self._load_database_configuration()

            # Create database connection with appropriate backend
            self.database = ConversationDatabase(
                db_type=db_type,
                credentials=db_credentials,
                user_guid=self.user_guid
            )
            progress.update(task_db, advance=100)

            # Task 4.5: Initialise token management (if enabled)
            token_mgmt_enabled = self.settings.get('token_management.enabled', False)
            if token_mgmt_enabled:
                task_token = progress.add_task("[cyan]Initialising token management...", total=100)
                try:
                    # Create token manager
                    token_config = {
                        'enabled': True,
                        'max_input_tokens': self.settings.get('token_management.max_input_tokens', 100000),
                        'max_output_tokens': self.settings.get('token_management.max_output_tokens', 50000),
                        'period_hours': self.settings.get('token_management.period_hours', 24),
                        'allow_override': self.settings.get('token_management.allow_override', True)
                    }
                    self.token_manager = TokenManager(self.database, token_config)
                    progress.update(task_token, advance=100)

                    logging.info(
                        f"Token management enabled: {token_config['max_input_tokens']:,} input tokens, "
                        f"{token_config['max_output_tokens']:,} output tokens per {token_config['period_hours']}h"
                    )

                except Exception as e:
                    logging.error(f"Failed to initialise token management: {e}")
                    progress.update(task_token, advance=100)
                    self.token_manager = None
            else:
                self.token_manager = None

            # Task 5: MCP Initialisation (if enabled)
            mcp_enabled = self.settings.get('mcp_config.enabled', False)
            if mcp_enabled:
                task_mcp = progress.add_task("[cyan]Initialising MCP servers...", total=100)
                try:
                    # Create MCP manager from config
                    config_dict = {
                        'mcp_config': {
                            'servers': self.settings.get('mcp_config.servers', [])
                        }
                    }
                    self.mcp_manager = MCPManager.from_config(config_dict)
                    progress.update(task_mcp, advance=10)

                    # Calculate progress per server (70% of progress for connecting servers)
                    num_servers = len(self.mcp_manager.clients)
                    progress_per_server = 70.0 / num_servers if num_servers > 0 else 0

                    # Define progress callback to update as each server connects
                    def on_server_connected(server_name: str, success: bool):
                        status = "OK" if success else "FAIL"
                        progress.update(task_mcp, advance=progress_per_server,
                                      description=f"[cyan]Initialising MCP servers... [{status}] {server_name}")
                        progress.refresh()  # Force display refresh
                        time.sleep(0.1)  # Small delay to make progress visible

                    # Connect to all MCP servers with progress callback
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    results = loop.run_until_complete(self.mcp_manager.connect_all(on_server_connected))

                    # Reset description after all servers connected
                    progress.update(task_mcp, description="[cyan]Initialising MCP servers...")

                    connected_count = sum(1 for success in results.values() if success)
                    if connected_count > 0:
                        # Fetch and cache tools
                        try:
                            tools = loop.run_until_complete(
                                asyncio.wait_for(
                                    self.mcp_manager.list_all_tools(),
                                    timeout=15.0
                                )
                            )
                            progress.update(task_mcp, advance=20)

                            # Store the loop for reuse
                            self.mcp_manager._initialization_loop = loop

                        except asyncio.TimeoutError:
                            logging.error("Timeout during initial MCP tool fetch")
                            progress.update(task_mcp, advance=20)
                        except Exception as tool_err:
                            logging.error(f"Error during initial MCP tool fetch: {tool_err}")
                            progress.update(task_mcp, advance=20)
                    else:
                        progress.update(task_mcp, advance=90)

                except Exception as e:
                    logging.exception("MCP initialisation failed")
                    self.mcp_manager = None
                    progress.update(task_mcp, advance=100)

            # Task 6: Initialise conversation manager
            task_conv = progress.add_task("[cyan]Initialising conversation manager...", total=100)
            max_tokens = self.settings.get('bedrock.max_tokens', 4096)
            rollup_threshold = self.settings.get('conversation.rollup_threshold', 0.8)
            rollup_summary_ratio = self.settings.get('conversation.rollup_summary_ratio', 0.3)
            max_tool_result_tokens = self.settings.get('conversation.max_tool_result_tokens', 10000)
            max_tool_iterations = self.settings.get('conversation.max_tool_iterations', 25)
            max_tool_selections = self.settings.get('conversation.max_tool_selections', 30)
            emergency_rollup_threshold = self.settings.get('conversation.emergency_rollup_threshold', 0.95)

            # Load global instructions if configured
            global_instructions = None
            global_instructions_path = self.settings.get('conversation.global_instructions_path', None)
            if global_instructions_path:
                try:
                    logging.info(f"Loading global instructions from: {global_instructions_path}")
                    resource_manager = ResourceManager()
                    global_instructions = resource_manager.load_resource(global_instructions_path)
                    if global_instructions:
                        logging.info(f"Global instructions loaded successfully ({len(global_instructions)} characters)")
                    else:
                        logging.warning(f"Global instructions file is empty: {global_instructions_path}")
                except Exception as e:
                    logging.warning(f"Failed to load global instructions from {global_instructions_path}: {e}")
                    logging.warning("Continuing without global instructions")

            # Initialise prompt inspector for Cyber Security
            prompt_inspector = None
            prompt_inspection_config = self.settings.get('prompt_inspection', {})
            if prompt_inspection_config.get('enabled', True):
                logging.info("Initialising prompt inspection system")

                # Create violation logger
                violation_logger = ViolationLogger(
                    self.database.conn,
                    prompt_inspection_config
                )

                # Create LLM service for inspection if strict mode
                inspection_llm_service = None
                llm_config = prompt_inspection_config.get('llm_inspection', {})
                if llm_config.get('enabled', False):
                    try:
                        # Create inspection LLM service with provider manager
                        inspection_llm_service = InspectionLLMService(
                            config=llm_config,
                            provider_manager=self.llm_manager  # Use existing LLM manager
                        )

                        if inspection_llm_service.is_available():
                            logging.info(f"LLM inspection available: {llm_config.get('model')} via {llm_config.get('provider', 'auto-detect')}")
                        else:
                            logging.warning("LLM inspection requested but not available")
                    except Exception as e:
                        logging.warning(f"Failed to initialise LLM inspection: {e}")
                        inspection_llm_service = None

                # Create prompt inspector
                prompt_inspector = PromptInspector(
                    config=prompt_inspection_config,
                    llm_service=inspection_llm_service,
                    violation_logger=violation_logger
                )

                logging.info(f"Prompt inspector initialised: level={prompt_inspector.inspection_level}, action={prompt_inspector.action}")
            else:
                logging.info("Prompt inspection disabled")

            # Build config dictionary with model_context_limits and embedded_tools
            # Settings uses dot notation, so we need to build the nested dict structure
            config_for_manager = {
                'model_context_limits': self._build_model_context_limits(),
                'embedded_tools': {
                    'filesystem': {
                        'enabled': self.settings.get('embedded_tools.filesystem.enabled', False),
                        'allowed_path': self.settings.get('embedded_tools.filesystem.allowed_path', './'),
                        'access_mode': self.settings.get('embedded_tools.filesystem.access_mode', 'read')
                    },
                    'documents': {
                        'enabled': self.settings.get('embedded_tools.documents.enabled', False),
                        'allowed_path': self.settings.get('embedded_tools.documents.allowed_path', './'),
                        'access_mode': self.settings.get('embedded_tools.documents.access_mode', 'read'),
                        'max_file_size_mb': self.settings.get('embedded_tools.documents.max_file_size_mb', 50),
                        'reading': {
                            'max_pdf_pages': self.settings.get('embedded_tools.documents.reading.max_pdf_pages', 100),
                            'max_excel_rows': self.settings.get('embedded_tools.documents.reading.max_excel_rows', 10000)
                        },
                        'creation': {
                            'templates_path': self.settings.get('embedded_tools.documents.creation.templates_path'),
                            'default_author': self.settings.get('embedded_tools.documents.creation.default_author')
                        }
                    },
                    'archives': {
                        'enabled': self.settings.get('embedded_tools.archives.enabled', False),
                        'allowed_path': self.settings.get('embedded_tools.archives.allowed_path', './'),
                        'access_mode': self.settings.get('embedded_tools.archives.access_mode', 'read'),
                        'max_file_size_mb': self.settings.get('embedded_tools.archives.max_file_size_mb', 100),
                        'max_files_to_list': self.settings.get('embedded_tools.archives.max_files_to_list', 1000)
                    }
                }
            }

            self.conversation_manager = ConversationManager(
                self.database,
                self.bedrock_service,
                max_tokens=max_tokens,
                rollup_threshold=rollup_threshold,
                rollup_summary_ratio=rollup_summary_ratio,
                max_tool_result_tokens=max_tool_result_tokens,
                max_tool_iterations=max_tool_iterations,
                max_tool_selections=max_tool_selections,
                emergency_rollup_threshold=emergency_rollup_threshold,
                mcp_manager=self.mcp_manager,
                cli_interface=self.cli,
                global_instructions=global_instructions,
                token_manager=self.token_manager,
                prompt_inspector=prompt_inspector,
                user_guid=self.user_guid,
                config=config_for_manager
            )
            progress.update(task_conv, advance=100)

            # Task 7: Initialise autonomous action scheduler (if enabled)
            self.actions_enabled = self._get_nested_setting('autonomous_actions.enabled', False)
            self.new_conversations_allowed = self._get_nested_setting('predefined_conversations.allow_new_conversations', True)
            task_scheduler = progress.add_task("[cyan]Initialising action scheduler...", total=100)

            if not self.actions_enabled:
                logging.info("Autonomous actions are disabled via configuration")
                self.action_scheduler = None
                self.execution_queue = None
                self.action_executor = None
                self.daemon_is_running = False
                progress.update(task_scheduler, advance=100)
            else:
                try:
                    from dtSpark.scheduler import (
                        ActionSchedulerManager,
                        ActionExecutionQueue,
                        ActionExecutor
                    )

                    # Get database path for scheduler job store
                    db_path = self.database.db_path or ':memory:'

                    # Create executor with LLM manager and optional MCP manager
                    get_tools_func = None
                    if self.mcp_manager:
                        def get_tools_func():
                            import asyncio
                            loop = getattr(self.mcp_manager, '_initialization_loop', None)
                            if loop and not loop.is_closed():
                                return loop.run_until_complete(self.mcp_manager.list_all_tools())
                            return []

                    self.action_executor = ActionExecutor(
                        database=self.database,
                        llm_manager=self.llm_manager,
                        mcp_manager=self.mcp_manager,
                        get_tools_func=get_tools_func,
                        config=config_for_manager
                    )

                    # Create execution queue
                    self.execution_queue = ActionExecutionQueue(
                        executor_func=self.action_executor.execute
                    )

                    # Create scheduler manager
                    self.action_scheduler = ActionSchedulerManager(
                        db_path=db_path,
                        execution_callback=lambda action_id, user_guid: self.execution_queue.enqueue(
                            action_id, user_guid, is_manual=False
                        )
                    )

                    # Check if daemon is running (for warning display later)
                    self.daemon_is_running = self._check_daemon_running()

                    # Initialise execution components (for manual "Run Now" from UI)
                    # Note: Scheduled execution is ONLY handled by the daemon process
                    self.action_scheduler.initialise()
                    self.execution_queue.start()

                    # UI never starts the scheduler - daemon handles all scheduled execution
                    if self.daemon_is_running:
                        logging.info("Daemon is running - scheduled actions will be executed by daemon")
                    else:
                        logging.warning("Daemon is not running - scheduled actions will NOT execute until daemon is started")

                    progress.update(task_scheduler, advance=100)

                except ImportError as e:
                    logging.warning(f"Action scheduler not available (APScheduler not installed): {e}")
                    self.action_scheduler = None
                    self.execution_queue = None
                    self.action_executor = None
                    progress.update(task_scheduler, advance=100)
                except Exception as e:
                    logging.error(f"Failed to initialise action scheduler: {e}")
                    self.action_scheduler = None
                    self.execution_queue = None
                    self.action_executor = None
                    progress.update(task_scheduler, advance=100)

        # Display application info first (user identification)
        self.cli.display_application_info(self.user_guid)

        # Display authentication info after progress completes (only if AWS is enabled)
        if self.authenticator:
            account_info = self.authenticator.get_account_info()
            if account_info:
                self.cli.display_aws_account_info(account_info)

        # Display MCP info if enabled
        if mcp_enabled and self.mcp_manager:
            self.cli.display_mcp_status(self.mcp_manager)

        # Display daemon status warning if daemon is not running (only when actions are enabled)
        if self.actions_enabled and hasattr(self, 'daemon_is_running') and not self.daemon_is_running:
            # Check if there are any scheduled actions
            try:
                actions = self.database.get_all_actions(include_disabled=False)
                scheduled_count = sum(1 for a in actions if a.get('schedule_type') != 'manual')
                if scheduled_count > 0:
                    self.cli.print_warning(
                        f"Daemon is not running - {scheduled_count} scheduled action(s) will NOT execute. "
                        f"Start the daemon with: spark daemon start"
                    )
            except Exception:
                pass  # Don't fail if we can't check actions

        # Display AWS Bedrock Usage Costs (after all initialization)
        self.display_bedrock_costs()

        # Sync predefined conversations if enabled
        self.sync_predefined_conversations()

        logging.info('Application components initialised successfully')

    def launch_web_interface(self):
        """
        Launch the web interface.

        Starts a FastAPI web server on localhost with one-time authentication.
        """
        from dtSpark.web import WebServer

        # Get web interface settings
        host = self.settings.get('interface.web.host', '127.0.0.1')
        port = self.settings.get('interface.web.port', 0)
        session_timeout = self.settings.get('interface.web.session_timeout_minutes', 30)
        dark_theme = self.settings.get('interface.web.dark_theme', True)

        # Get SSL settings
        ssl_enabled = self.settings.get('interface.web.ssl.enabled', False)
        ssl_auto_generate = self.settings.get('interface.web.ssl.auto_generate_cert', True)
        ssl_cert_file = self.settings.get('interface.web.ssl.cert_file', 'certs/ssl_cert.pem')
        ssl_key_file = self.settings.get('interface.web.ssl.key_file', 'certs/ssl_key.pem')

        # Get browser auto-open setting
        auto_open_browser = self.settings.get('interface.web.auto_open_browser', True)

        protocol = "HTTPS" if ssl_enabled else "HTTP"
        logging.info(f"Launching web interface on {protocol}://{host}:{port if port != 0 else 'random port'}")
        if ssl_enabled:
            logging.info("SSL is enabled - self-signed certificate will be used")

        # Create web server
        server = WebServer(
            app_instance=self,
            host=host,
            port=port,
            session_timeout_minutes=session_timeout,
            dark_theme=dark_theme,
            ssl_enabled=ssl_enabled,
            ssl_cert_file=ssl_cert_file,
            ssl_key_file=ssl_key_file,
            ssl_auto_generate=ssl_auto_generate,
            auto_open_browser=auto_open_browser,
        )

        # Get access information
        access_info = server.get_access_info()

        # Display access information in CLI
        self.cli.print_separator("═")
        self.cli.print_info("Web Interface Started")
        self.cli.print_separator("═")
        self.cli.console.print()

        # Show protocol indicator
        if access_info.get('ssl_enabled'):
            self.cli.console.print("[bold green]🔒 HTTPS Enabled[/bold green] (Self-signed certificate)")
            self.cli.console.print()

        self.cli.console.print(f"[bold cyan]URL:[/bold cyan] [bold]{access_info['url']}[/bold]")
        self.cli.console.print(f"[bold cyan]Authentication Code:[/bold cyan] [bold yellow]{access_info['code']}[/bold yellow]")
        self.cli.console.print()

        # Update instructions based on auto-open setting
        if auto_open_browser:
            self.cli.console.print("[dim]Your browser should open automatically.[/dim]")
            self.cli.console.print("[dim]If it doesn't, open the URL above and enter the authentication code.[/dim]")
        else:
            self.cli.console.print("[dim]Open the URL in your web browser and enter the authentication code.[/dim]")

        self.cli.console.print("[dim]The code can only be used once for security.[/dim]")

        # Add note about self-signed certificates
        if access_info.get('ssl_enabled'):
            self.cli.console.print()
            self.cli.console.print("[bold yellow]Note:[/bold yellow] [dim]Your browser will show a security warning for the self-signed certificate.[/dim]")
            self.cli.console.print("[dim]This is expected. You can safely proceed past this warning.[/dim]")

        self.cli.console.print()
        self.cli.console.print("[dim]Press Ctrl+C to stop the server.[/dim]")
        self.cli.console.print()
        self.cli.print_separator("═")

        try:
            # Start server (blocking)
            server.run()
        except KeyboardInterrupt:
            self.cli.console.print()
            self.cli.print_info("Shutting down web server...")
        except Exception as e:
            logging.error(f"Web server error: {e}")
            self.cli.print_error(f"Web server error: {e}")

    def sync_predefined_conversations(self):
        """
        Synchronise predefined conversations from config.

        This method:
        - Checks if predefined conversations are enabled in config
        - For each enabled predefined conversation:
          - Calculates a config hash to detect changes
          - Creates the conversation if it doesn't exist
          - Updates it if the config has changed
          - Attaches configured files
        """
        import json
        import hashlib
        from dtSpark.files import FileManager

        try:
            # Check if predefined conversations are enabled
            predef_enabled = self.settings.get('predefined_conversations.enabled', False)
            if not predef_enabled:
                logging.debug("Predefined conversations not enabled in config")
                return

            # Get the mandatory model and provider settings
            mandatory_model = self._get_nested_setting('llm_providers.mandatory_model', None)
            mandatory_provider = self._get_nested_setting('llm_providers.mandatory_provider', None)

            # Get list of predefined conversations
            predefined_convs = self.settings.get('predefined_conversations.conversations', [])

            if not predefined_convs:
                logging.debug("No predefined conversations configured")
                return

            logging.info(f"Synchronising {len(predefined_convs)} predefined conversation(s)")

            for conv_config in predefined_convs:
                # Skip if not enabled
                if not conv_config.get('enabled', True):
                    logging.debug(f"Skipping disabled predefined conversation: {conv_config.get('name')}")
                    continue

                name = conv_config.get('name')
                if not name:
                    logging.warning("Predefined conversation missing 'name', skipping")
                    continue

                # Load instructions from file using ResourceManager, with fallback to direct path
                instructions_source = conv_config.get('instructions', '')
                instructions = self._load_text_resource(instructions_source, f"instructions for '{name}'")

                files = conv_config.get('files', [])

                # Determine which model and provider to use
                # If mandatory_model is set, use it regardless of conversation config
                if mandatory_model:
                    model_id = mandatory_model
                    provider_name = mandatory_provider  # Use mandatory provider if set
                    logging.debug(f"Using mandatory model '{model_id}' for predefined conversation '{name}'")
                else:
                    model_id = conv_config.get('model')
                    provider_name = conv_config.get('provider')  # Get provider from config
                    if not model_id:
                        logging.warning(f"Predefined conversation '{name}' has no model specified and no mandatory model set, skipping")
                        continue

                # Calculate config hash (hash of name, instructions, files, model, and provider)
                config_data = {
                    'name': name,
                    'instructions': instructions,
                    'files': sorted(files),  # Sort for consistent hashing
                    'model': model_id,
                    'provider': provider_name  # Include provider in hash
                }
                config_json = json.dumps(config_data, sort_keys=True)
                config_hash = hashlib.sha256(config_json.encode()).hexdigest()

                # Check if conversation exists
                existing_conv = self.database.get_predefined_conversation_by_name(name)

                if existing_conv:
                    # Conversation exists - check if config has changed
                    if existing_conv['config_hash'] != config_hash:
                        logging.info(f"Predefined conversation '{name}' config changed, updating...")

                        # Update the conversation
                        self.database.update_predefined_conversation(
                            existing_conv['id'],
                            model_id,
                            instructions,
                            config_hash
                        )

                        # Delete old files and re-attach
                        self.database.delete_conversation_files(existing_conv['id'])

                        # Attach new files
                        if files:
                            self._attach_files_to_conversation(existing_conv['id'], files)

                        logging.info(f"Updated predefined conversation '{name}'")
                    else:
                        logging.debug(f"Predefined conversation '{name}' unchanged")
                else:
                    # Create new predefined conversation
                    logging.info(f"Creating predefined conversation '{name}'...")

                    conversation_id = self.database.create_predefined_conversation(
                        name,
                        model_id,
                        instructions,
                        config_hash
                    )

                    # Attach files
                    if files:
                        self._attach_files_to_conversation(conversation_id, files)

                    logging.info(f"Created predefined conversation '{name}' (ID: {conversation_id})")

        except Exception as e:
            logging.error(f"Error synchronising predefined conversations: {e}")
            logging.exception(e)

    def _load_text_resource(self, source: str, description: str = "resource") -> str:
        """
        Load text content from a resource file using ResourceManager with fallback to direct path.

        Attempts to load the resource in this order:
        1. Via ResourceManager (for resources in package)
        2. Direct file path (if ResourceManager returns None)
        3. If both fail or source is empty, returns the source string as-is (inline text)

        Args:
            source: Resource path/name, file path, or inline text
            description: Description of what's being loaded (for logging)

        Returns:
            The loaded text content or the original source string
        """
        if not source or not source.strip():
            return source

        import os

        # Determine if source looks like a file path or resource name
        # (contains path separators, has a file extension, or doesn't contain spaces)
        looks_like_path = (
            os.sep in source
            or '/' in source
            or '\\' in source
            or (
                '.' in source
                and not source.strip().endswith('.')
                and ' ' not in source.strip()
            )
        )

        if looks_like_path:
            # Try ResourceManager first (for package resources)
            try:
                resource_content = ResourceManager().load_resource(source)
                if resource_content is not None:
                    logging.info(f"Loaded {description} via ResourceManager from: {source}")
                    return resource_content
            except Exception as e:
                logging.debug(f"ResourceManager could not load {description} from '{source}': {e}")

            # Try direct file path
            try:
                if os.path.isfile(source):
                    with open(source, 'r', encoding='utf-8') as f:
                        content = f.read()
                        logging.info(f"Loaded {description} from file path: {source}")
                        return content
            except Exception as e:
                logging.debug(f"Could not load {description} from file path '{source}': {e}")

            # Path-like source but couldn't load - log warning and return as-is
            logging.warning(f"Could not load {description} from path '{source}', using as inline text")

        # Treat as inline text
        logging.debug(f"Using inline text for {description}")
        return source

    def _attach_files_to_conversation(self, conversation_id: int, file_paths: List[str]):
        """
        Attach files to a conversation.

        Tries to load files using ResourceManager first, then falls back to direct file path.

        Args:
            conversation_id: ID of the conversation
            file_paths: List of file paths to attach
        """
        from dtSpark.files import FileManager
        import tempfile
        import os

        file_manager = FileManager()

        for file_path in file_paths:
            try:
                resolved_path = file_path
                temp_file_path = None

                # Try ResourceManager first
                try:
                    resource_content = ResourceManager().load_resource(file_path)
                    if resource_content is not None:
                        # ResourceManager returned content - create temp file
                        # Extract filename from path
                        filename = os.path.basename(file_path)
                        # Create temporary file with same extension
                        suffix = os.path.splitext(filename)[1] if '.' in filename else ''
                        temp_fd, temp_file_path = tempfile.mkstemp(suffix=suffix, text=False)

                        # Write content to temp file
                        if isinstance(resource_content, str):
                            os.write(temp_fd, resource_content.encode('utf-8'))
                        else:
                            os.write(temp_fd, resource_content)
                        os.close(temp_fd)

                        resolved_path = temp_file_path
                        logging.info(f"Loaded file via ResourceManager from: {file_path}")
                except Exception as e:
                    logging.debug(f"ResourceManager could not load file '{file_path}': {e}")
                    # Will fall back to direct file path

                # Process the file (either from temp file or original path)
                file_info = file_manager.process_file(resolved_path)

                # Clean up temp file if created
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.warning(f"Could not delete temp file '{temp_file_path}': {e}")

                if file_info:
                    # Add file to database
                    self.database.add_file(
                        conversation_id=conversation_id,
                        filename=file_info['filename'],
                        file_type=file_info['file_type'],
                        file_size=file_info['file_size'],
                        content_text=file_info.get('content_text'),
                        content_base64=file_info.get('content_base64'),
                        mime_type=file_info.get('mime_type'),
                        token_count=file_info.get('token_count', 0)
                    )
                    logging.debug(f"Attached file '{file_info['filename']}' to conversation {conversation_id}")
                else:
                    logging.warning(f"Failed to process file: {file_path}")
            except Exception as e:
                logging.error(f"Error attaching file '{file_path}': {e}")

    def setup_wizard(self):
        """
        Interactive setup wizard to create config.yaml with all commentary.

        Walks the user through:
        - LLM provider selection (AWS Bedrock, Ollama, Anthropic API)
        - Database selection (SQLite, MySQL, MariaDB, PostgreSQL, MSSQL)
        - Interface configuration (CLI or Web)
        - Additional features (MCP, security)

        Creates a properly formatted config.yaml file in the user data directory.
        """
        import shutil
        from rich.panel import Panel
        from rich.prompt import Prompt, Confirm

        # Initialize CLI interface for prompts
        from dtSpark.cli_interface import CLIInterface
        cli = CLIInterface()

        # Display SPARK splash screen
        cli.print_splash_screen(
            full_name=full_name(),
            description=module_package.description,
            version=version()
        )

        # Display setup wizard context
        cli.console.print(Panel(
            "[bold cyan]Setup Wizard[/bold cyan]\n\n"
            "This wizard will guide you through configuring:\n"
            "  • LLM Providers (AWS Bedrock, Ollama, Anthropic API)\n"
            "  • Database (SQLite, MySQL, PostgreSQL, MSSQL)\n"
            "  • Interface (CLI or Web)\n"
            "  • Additional Features\n\n"
            "A config.yaml file will be created with all settings and documentation.",
            border_style="cyan",
            padding=(1, 2)
        ))
        cli.console.print()

        # Destination: depends on CONTAINER_MODE environment variable
        container_mode = os.environ.get('CONTAINER_MODE', '').lower() == 'true'
        if container_mode:
            # Container mode: use working directory with config subfolder
            dest_config_dir = os.path.join(os.getcwd(), 'config')
            secrets_dir = os.getcwd()
        else:
            # Normal mode: use user data directory directly (no config subfolder)
            user_data_path = ApplicationPaths().usr_data_root_path
            dest_config_dir = user_data_path
            secrets_dir = user_data_path

        dest_config = os.path.join(dest_config_dir, 'config.yaml')
        secrets_file = os.path.join(secrets_dir, 'secrets.yaml')

        # Collection for secrets to be written to secrets.yaml
        secrets_to_store = []

        cli.print_info(f"Configuration will be created at: {dest_config}")
        cli.console.print()

        # Check if config already exists
        if os.path.exists(dest_config):
            cli.print_warning("A configuration file already exists!")
            if not Confirm.ask("[bold yellow]Do you want to overwrite it?[/bold yellow]", default=False):
                cli.print_info("Setup cancelled. Existing configuration unchanged.")
                return
            cli.console.print()

        # ═══════════════════════════════════════════════════════════════
        # LLM Provider Selection
        # ═══════════════════════════════════════════════════════════════
        cli.print_separator("═")
        cli.console.print("[bold]LLM Provider Selection[/bold]")
        cli.print_separator("═")
        cli.console.print()
        cli.console.print("Select which LLM providers you want to configure:")
        cli.console.print()

        # AWS Bedrock
        use_aws_bedrock = Confirm.ask("Do you wish to use AWS Bedrock?", default=True)

        # Ollama
        use_ollama = Confirm.ask("Do you wish to use Ollama (local LLM server)?", default=False)

        # Anthropic Direct API
        use_anthropic = Confirm.ask("Do you wish to use Anthropic Direct API?", default=False)

        # Ensure at least one provider is selected
        if not (use_aws_bedrock or use_ollama or use_anthropic):
            cli.print_error("You must enable at least one LLM provider!")
            cli.print_info("Setup cancelled.")
            return

        # ═══════════════════════════════════════════════════════════════
        # AWS Bedrock Configuration
        # ═══════════════════════════════════════════════════════════════
        aws_auth_method = "sso"
        aws_profile = "default"
        aws_region = "us-east-1"
        aws_account_name = ""
        aws_account_id = ""
        aws_access_key_id = ""
        aws_secret_access_key = ""
        aws_session_token = ""
        enable_cost_tracking = False

        if use_aws_bedrock:
            cli.console.print()
            cli.print_separator("═")
            cli.console.print("[bold]AWS Bedrock Configuration[/bold]")
            cli.print_separator("═")
            cli.console.print()

            # Authentication method selection
            cli.console.print("[bold]Authentication Method[/bold]")
            cli.console.print()
            cli.console.print("  [1] SSO Profile - AWS Single Sign-On (recommended for interactive use)")
            cli.console.print("  [2] IAM Access Keys - Long-lived credentials (recommended for autonomous actions)")
            cli.console.print("  [3] Session Credentials - Temporary credentials with session token")
            cli.console.print()
            cli.console.print("[dim]Note: SSO and session credentials have timeouts which may interrupt[/dim]")
            cli.console.print("[dim]autonomous actions running on a schedule. IAM access keys are recommended[/dim]")
            cli.console.print("[dim]for unattended/scheduled operations as they do not expire.[/dim]")
            cli.console.print()

            auth_method_choices = {
                "1": "sso",
                "2": "iam",
                "3": "session"
            }
            auth_method_choice = Prompt.ask(
                "Select authentication method",
                choices=["1", "2", "3"],
                default="1"
            )
            aws_auth_method = auth_method_choices[auth_method_choice]

            cli.console.print()

            # Region (common to all methods)
            aws_region = Prompt.ask(
                "AWS region",
                default="us-east-1"
            )

            # SSO Profile authentication
            if aws_auth_method == "sso":
                cli.console.print()
                aws_profile = Prompt.ask(
                    "AWS SSO profile name",
                    default="default"
                )

            # IAM or Session authentication
            if aws_auth_method in ["iam", "session"]:
                cli.console.print()
                cli.console.print("[dim]AWS Account Information (optional, for reference):[/dim]")
                aws_account_name = Prompt.ask(
                    "AWS account name (friendly name)",
                    default=""
                )
                aws_account_id = Prompt.ask(
                    "AWS account ID (12-digit number)",
                    default=""
                )

                cli.console.print()
                cli.console.print("[dim]AWS Credentials (will be stored in secrets.yaml for secure ingestion):[/dim]")

                # Access Key ID (not typically considered secret, but mask anyway for consistency)
                aws_access_key_id_input = Prompt.ask(
                    "AWS access key ID",
                    default=""
                )
                if aws_access_key_id_input:
                    secrets_to_store.append({"name": "aws_access_key_id", "value": aws_access_key_id_input})
                    aws_access_key_id = "SEC/aws_access_key_id"

                # Secret Access Key (sensitive - mask input)
                aws_secret_access_key_input = Prompt.ask(
                    "AWS secret access key",
                    default="",
                    password=True
                )
                if aws_secret_access_key_input:
                    secrets_to_store.append({"name": "aws_secret_access_key", "value": aws_secret_access_key_input})
                    aws_secret_access_key = "SEC/aws_secret_access_key"

                # Session Token (only for session auth)
                if aws_auth_method == "session":
                    cli.console.print()
                    aws_session_token_input = Prompt.ask(
                        "AWS session token",
                        default="",
                        password=True
                    )
                    if aws_session_token_input:
                        secrets_to_store.append({"name": "aws_session_token", "value": aws_session_token_input})
                        aws_session_token = "SEC/aws_session_token"

            cli.console.print()
            enable_cost_tracking = Confirm.ask(
                "Enable AWS cost tracking?",
                default=False
            )

        # ═══════════════════════════════════════════════════════════════
        # Ollama Configuration
        # ═══════════════════════════════════════════════════════════════
        ollama_base_url = "http://localhost:11434"

        if use_ollama:
            cli.console.print()
            cli.print_separator("═")
            cli.console.print("[bold]Ollama Configuration[/bold]")
            cli.print_separator("═")
            cli.console.print()

            ollama_base_url = Prompt.ask(
                "Ollama base URL",
                default="http://localhost:11434"
            )

        # ═══════════════════════════════════════════════════════════════
        # Anthropic Direct API Configuration
        # ═══════════════════════════════════════════════════════════════
        anthropic_api_key = ""

        if use_anthropic:
            cli.console.print()
            cli.print_separator("═")
            cli.console.print("[bold]Anthropic Direct API Configuration[/bold]")
            cli.print_separator("═")
            cli.console.print()

            anthropic_api_key_input = Prompt.ask(
                "Anthropic API key (or press Enter to set via environment variable later)",
                default="",
                password=True
            )

            # Store API key in secrets.yaml if provided
            if anthropic_api_key_input:
                secrets_to_store.append({"name": "anthropic_api_key", "value": anthropic_api_key_input})
                anthropic_api_key = "SEC/anthropic_api_key"
            else:
                anthropic_api_key = ""

        # ═══════════════════════════════════════════════════════════════
        # Database Configuration
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        cli.print_separator("═")
        cli.console.print("[bold]Database Configuration[/bold]")
        cli.print_separator("═")
        cli.console.print()

        database_choices = {
            "1": "sqlite",
            "2": "mysql",
            "3": "mariadb",
            "4": "postgresql",
            "5": "mssql"
        }
        cli.console.print("  [1] SQLite (local file, no setup required) [default]")
        cli.console.print("  [2] MySQL (remote database server)")
        cli.console.print("  [3] MariaDB (remote database server)")
        cli.console.print("  [4] PostgreSQL (remote database server)")
        cli.console.print("  [5] Microsoft SQL Server (remote database server)")
        cli.console.print()
        database_choice = Prompt.ask("Select database type", choices=["1", "2", "3", "4", "5"], default="1")
        database_type = database_choices[database_choice]

        # Remote database configuration (MySQL, MariaDB, PostgreSQL, MSSQL)
        db_host = "localhost"
        db_port = "3306"
        db_database = "dtawsbedrockcli"
        db_username = "null"
        db_password = "null"
        db_ssl = False
        db_driver = "ODBC Driver 17 for SQL Server"

        if database_type != "sqlite":
            cli.console.print()
            cli.console.print("[dim]Configure connection details for remote database:[/dim]")
            cli.console.print()

            # Default ports
            default_ports = {
                "mysql": "3306",
                "mariadb": "3306",
                "postgresql": "5432",
                "mssql": "1433"
            }

            db_host = Prompt.ask("Database host", default="localhost")
            db_port = Prompt.ask("Database port", default=default_ports.get(database_type, "3306"))
            db_database = Prompt.ask("Database name", default="dtawsbedrockcli")

            cli.console.print()
            cli.console.print("[dim]Leave username/password empty (null) to be prompted on startup (more secure)[/dim]")
            db_username_input = Prompt.ask("Database username (or press Enter for null)", default="")

            # Store database username in secrets.yaml if provided
            if db_username_input:
                secret_key = f"db_{database_type}_username"
                secrets_to_store.append({"name": secret_key, "value": db_username_input})
                db_username = f"SEC/{secret_key}"
            else:
                db_username = "null"

            db_password_input = Prompt.ask("Database password (or press Enter for null)", default="", password=True)

            # Store database password in secrets.yaml if provided
            if db_password_input:
                secret_key = f"db_{database_type}_password"
                secrets_to_store.append({"name": secret_key, "value": db_password_input})
                db_password = f"SEC/{secret_key}"
            else:
                db_password = "null"

            db_ssl = Confirm.ask("Use SSL/TLS connection?", default=False)

            # MSSQL-specific: ODBC driver
            if database_type == "mssql":
                cli.console.print()
                db_driver = Prompt.ask(
                    "ODBC driver name",
                    default="ODBC Driver 17 for SQL Server"
                )

        cli.console.print()
        cli.print_separator("═")
        cli.console.print("[bold]Interface Configuration[/bold]")
        cli.print_separator("═")
        cli.console.print()

        interface_choices = {
            "1": "cli",
            "2": "web"
        }
        cli.console.print("  [1] CLI (Command-line interface)")
        cli.console.print("  [2] Web (Browser-based interface)")
        interface_choice = Prompt.ask("Select interface type", choices=["1", "2"], default="1")
        interface_type = interface_choices[interface_choice]

        # Web-specific settings
        web_ssl_enabled = False
        web_dark_theme = True
        if interface_type == "web":
            cli.console.print()
            web_ssl_enabled = Confirm.ask("Enable HTTPS with self-signed certificate?", default=True)
            web_dark_theme = Confirm.ask("Use dark theme?", default=True)

        cli.console.print()
        cli.print_separator("═")
        cli.console.print("[bold]Model Configuration[/bold]")
        cli.print_separator("═")
        cli.console.print()

        max_tokens = Prompt.ask(
            "Maximum tokens per response",
            default="8192"
        )

        temperature = Prompt.ask(
            "Temperature (0.0-1.0, higher = more creative)",
            default="0.7"
        )

        cli.console.print()
        cli.print_separator("═")
        cli.console.print("[bold]Additional Features[/bold]")
        cli.print_separator("═")
        cli.console.print()

        enable_mcp = Confirm.ask("Enable MCP (Model Context Protocol) integration?", default=True)

        # ═══════════════════════════════════════════════════════════════
        # Embedded Filesystem Tools
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        enable_filesystem_tools = Confirm.ask("Enable embedded filesystem tools?", default=False)

        # Default values
        filesystem_allowed_path = _DEFAULT_RUNNING_DIR
        filesystem_access_mode = "read_write"

        if enable_filesystem_tools:
            cli.console.print()
            cli.console.print("[dim]Embedded filesystem tools provide LLM access to local files.[/dim]")
            cli.console.print()

            filesystem_allowed_path = Prompt.ask(
                "Allowed directory path (tools can only access files within this directory)",
                default=_DEFAULT_RUNNING_DIR
            )

            # Access mode
            access_mode_choices = {
                "1": "read",
                "2": "read_write"
            }
            cli.console.print()
            cli.console.print("  [1] Read - Read-only access (list, search, read files)")
            cli.console.print("  [2] Read/Write - Full access (read + write files, create directories)")
            cli.console.print()
            access_mode_choice = Prompt.ask(
                _PROMPT_ACCESS_MODE,
                choices=["1", "2"],
                default="2"
            )
            filesystem_access_mode = access_mode_choices[access_mode_choice]

        # ═══════════════════════════════════════════════════════════════
        # Embedded Document Tools (MS Office & PDF)
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        enable_document_tools = Confirm.ask("Enable embedded document tools (MS Office & PDF)?", default=False)

        # Default values
        document_allowed_path = _DEFAULT_RUNNING_DIR
        document_access_mode = "read"
        document_max_file_size = "50"
        document_max_pdf_pages = "100"
        document_max_excel_rows = "10000"
        document_templates_path = ""
        document_default_author = ""

        if enable_document_tools:
            cli.console.print()
            cli.console.print("[dim]Document tools allow reading and creating MS Office documents (Word, Excel, PowerPoint) and PDFs.[/dim]")
            cli.console.print()

            document_allowed_path = Prompt.ask(
                "Allowed directory path for documents",
                default=_DEFAULT_RUNNING_DIR
            )

            # Access mode
            doc_access_mode_choices = {
                "1": "read",
                "2": "read_write"
            }
            cli.console.print()
            cli.console.print("  [1] Read - Read documents only")
            cli.console.print("  [2] Read/Write - Read and create documents")
            cli.console.print()
            doc_access_mode_choice = Prompt.ask(
                _PROMPT_ACCESS_MODE,
                choices=["1", "2"],
                default="1"
            )
            document_access_mode = doc_access_mode_choices[doc_access_mode_choice]

            document_max_file_size = Prompt.ask(
                "Maximum file size in MB",
                default="50"
            )

            document_max_pdf_pages = Prompt.ask(
                "Maximum PDF pages to read",
                default="100"
            )

            document_max_excel_rows = Prompt.ask(
                "Maximum Excel rows to read",
                default="10000"
            )

            if document_access_mode == "read_write":
                cli.console.print()
                cli.console.print("[dim]Templates allow creating documents with placeholder substitution.[/dim]")
                document_templates_path = Prompt.ask(
                    "Templates directory path (leave empty to disable)",
                    default=""
                )
                document_default_author = Prompt.ask(
                    "Default author for created documents (leave empty to disable)",
                    default=""
                )

        # ═══════════════════════════════════════════════════════════════
        # Embedded Archive Tools
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        enable_archive_tools = Confirm.ask("Enable embedded archive tools (ZIP, TAR)?", default=False)

        # Default values
        archive_allowed_path = _DEFAULT_RUNNING_DIR
        archive_access_mode = "read"
        archive_max_file_size = "100"
        archive_max_files_to_list = "1000"

        if enable_archive_tools:
            cli.console.print()
            cli.console.print("[dim]Archive tools allow reading and extracting ZIP and TAR archives.[/dim]")
            cli.console.print()

            archive_allowed_path = Prompt.ask(
                "Allowed directory path for archives",
                default=_DEFAULT_RUNNING_DIR
            )

            # Access mode
            archive_access_mode_choices = {
                "1": "read",
                "2": "read_write"
            }
            cli.console.print()
            cli.console.print("  [1] Read - List contents and read files from archives")
            cli.console.print("  [2] Read/Write - Read and extract archives to disk")
            cli.console.print()
            archive_access_mode_choice = Prompt.ask(
                _PROMPT_ACCESS_MODE,
                choices=["1", "2"],
                default="1"
            )
            archive_access_mode = archive_access_mode_choices[archive_access_mode_choice]

            archive_max_file_size = Prompt.ask(
                "Maximum archive file size in MB",
                default="100"
            )

            archive_max_files_to_list = Prompt.ask(
                "Maximum files to list from archive",
                default="1000"
            )

        # ═══════════════════════════════════════════════════════════════
        # Tool Permissions
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        cli.console.print("[dim]Tool permissions control how the LLM uses tools (MCP servers, embedded tools).[/dim]")
        auto_approve_tools = Confirm.ask(
            "Auto-approve all tools without prompting (recommended for trusted environments only)?",
            default=False
        )

        # ═══════════════════════════════════════════════════════════════
        # Prompt Inspection (Cyber Security)
        # ═══════════════════════════════════════════════════════════════
        cli.console.print()
        enable_prompt_inspection = Confirm.ask("Enable prompt security inspection (Cyber Security)?", default=False)

        # Default values
        inspection_level = "basic"
        inspection_action = "warn"
        llm_inspection_enabled = False
        llm_inspection_model = "anthropic.claude-3-haiku-20240307-v1:0"
        llm_inspection_provider = "AWS Bedrock"
        llm_inspection_confidence = "0.7"

        if enable_prompt_inspection:
            cli.console.print()
            cli.console.print("[dim]Prompt inspection detects and mitigates security risks in user prompts.[/dim]")
            cli.console.print()

            # Inspection level
            inspection_level_choices = {
                "1": "basic",
                "2": "standard",
                "3": "strict"
            }
            cli.console.print("  [1] Basic - Fast pattern matching only")
            cli.console.print("  [2] Standard - Pattern matching + keyword analysis")
            cli.console.print("  [3] Strict - Pattern matching + LLM semantic analysis")
            cli.console.print()
            inspection_level_choice = Prompt.ask(
                "Select inspection level",
                choices=["1", "2", "3"],
                default="1"
            )
            inspection_level = inspection_level_choices[inspection_level_choice]

            # Action on violations
            cli.console.print()
            inspection_action_choices = {
                "1": "warn",
                "2": "block",
                "3": "sanitise",
                "4": "log_only"
            }
            cli.console.print("  [1] Warn - Show warning and ask for confirmation [default]")
            cli.console.print("  [2] Block - Reject prompt completely")
            cli.console.print("  [3] Sanitise - Attempt to clean the prompt (with confirmation)")
            cli.console.print("  [4] Log only - Log violation but allow prompt")
            cli.console.print()
            inspection_action_choice = Prompt.ask(
                "Action when violations detected",
                choices=["1", "2", "3", "4"],
                default="1"
            )
            inspection_action = inspection_action_choices[inspection_action_choice]

            # LLM-based inspection (for strict level)
            if inspection_level == "strict":
                cli.console.print()
                cli.console.print("[dim]Strict level can use LLM for semantic analysis of prompts.[/dim]")
                llm_inspection_enabled = Confirm.ask(
                    "Enable LLM-based semantic analysis?",
                    default=True
                )

                if llm_inspection_enabled:
                    cli.console.print()
                    llm_inspection_model = Prompt.ask(
                        "LLM model for analysis (fast, cheap model recommended)",
                        default="anthropic.claude-3-haiku-20240307-v1:0"
                    )

                    # Provider selection
                    llm_provider_choices = {
                        "1": "AWS Bedrock",
                        "2": "Ollama",
                        "3": "Anthropic Direct"
                    }
                    cli.console.print()
                    cli.console.print("  [1] AWS Bedrock [default]")
                    cli.console.print("  [2] Ollama")
                    cli.console.print("  [3] Anthropic Direct")
                    cli.console.print()
                    llm_provider_choice = Prompt.ask(
                        "Select provider for LLM inspection",
                        choices=["1", "2", "3"],
                        default="1"
                    )
                    llm_inspection_provider = llm_provider_choices[llm_provider_choice]

                    cli.console.print()
                    llm_inspection_confidence = Prompt.ask(
                        "Confidence threshold (0.0-1.0, higher = more strict)",
                        default="0.7"
                    )

        # Load template config from package resources
        cli.console.print()
        cli.print_info("Generating configuration file...")

        try:
            # Load template from package resources
            config_content = ResourceManager().load_resource('config.yaml.template')
            if config_content is None:
                raise FileNotFoundError("Configuration template not found in package resources")

            # Replace placeholders with user values
            import re

            # Database settings
            config_content = re.sub(
                r'(type:\s+)(sqlite|mysql|mariadb|postgresql|mssql)(\s+#)',
                f'\\g<1>{database_type}\\g<3>',
                config_content
            )

            # MySQL/MariaDB settings
            if database_type in ["mysql", "mariadb"]:
                config_content = re.sub(
                    r'(mysql:\s*\n\s+host:\s+)[^\n]+',
                    f'\\g<1>{db_host}',
                    config_content
                )
                config_content = re.sub(
                    r'(mysql:\s*\n(?:.*\n)*?\s+port:\s+)\d+',
                    f'\\g<1>{db_port}',
                    config_content
                )
                config_content = re.sub(
                    r'(mysql:\s*\n(?:.*\n)*?\s+database:\s+)[^\n]+',
                    f'\\g<1>{db_database}',
                    config_content
                )
                config_content = re.sub(
                    r'(mysql:\s*\n(?:.*\n)*?\s+username:\s+)[^\s#]+',
                    f'\\g<1>{db_username}',
                    config_content
                )
                config_content = re.sub(
                    r'(mysql:\s*\n(?:.*\n)*?\s+password:\s+)[^\s#]+',
                    f'\\g<1>{db_password}',
                    config_content
                )
                config_content = re.sub(
                    r'(mysql:\s*\n(?:.*\n)*?\s+ssl:\s+)(true|false)',
                    f'\\g<1>{str(db_ssl).lower()}',
                    config_content
                )

            # PostgreSQL settings
            if database_type == "postgresql":
                config_content = re.sub(
                    r'(postgresql:\s*\n\s+host:\s+)[^\n]+',
                    f'\\g<1>{db_host}',
                    config_content
                )
                config_content = re.sub(
                    r'(postgresql:\s*\n(?:.*\n)*?\s+port:\s+)\d+',
                    f'\\g<1>{db_port}',
                    config_content
                )
                config_content = re.sub(
                    r'(postgresql:\s*\n(?:.*\n)*?\s+database:\s+)[^\n]+',
                    f'\\g<1>{db_database}',
                    config_content
                )
                config_content = re.sub(
                    r'(postgresql:\s*\n(?:.*\n)*?\s+username:\s+)[^\s#]+',
                    f'\\g<1>{db_username}',
                    config_content
                )
                config_content = re.sub(
                    r'(postgresql:\s*\n(?:.*\n)*?\s+password:\s+)[^\s#]+',
                    f'\\g<1>{db_password}',
                    config_content
                )
                config_content = re.sub(
                    r'(postgresql:\s*\n(?:.*\n)*?\s+ssl:\s+)(true|false)',
                    f'\\g<1>{str(db_ssl).lower()}',
                    config_content
                )

            # MSSQL settings
            if database_type == "mssql":
                config_content = re.sub(
                    r'(mssql:\s*\n\s+host:\s+)[^\n]+',
                    f'\\g<1>{db_host}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+port:\s+)\d+',
                    f'\\g<1>{db_port}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+database:\s+)[^\n]+',
                    f'\\g<1>{db_database}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+username:\s+)[^\s#]+',
                    f'\\g<1>{db_username}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+password:\s+)[^\s#]+',
                    f'\\g<1>{db_password}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+ssl:\s+)(true|false)',
                    f'\\g<1>{str(db_ssl).lower()}',
                    config_content
                )
                config_content = re.sub(
                    r'(mssql:\s*\n(?:.*\n)*?\s+driver:\s+")[^"]+(")',
                    f'\\g<1>{db_driver}\\g<2>',
                    config_content
                )

            # LLM Provider settings
            config_content = re.sub(
                r'(aws_bedrock:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(use_aws_bedrock).lower()}',
                config_content
            )
            config_content = re.sub(
                r'(ollama:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(use_ollama).lower()}',
                config_content
            )
            config_content = re.sub(
                r'(anthropic:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(use_anthropic).lower()}',
                config_content
            )

            # AWS settings
            if use_aws_bedrock:
                # Auth method
                config_content = re.sub(
                    r'(auth_method:\s+)[^\s#]+',
                    f'\\g<1>{aws_auth_method}',
                    config_content
                )
                # Region
                config_content = re.sub(
                    r'(aws_bedrock:\s*\n(?:.*\n)*?\s+region:\s+)[^\s#]+',
                    f'\\g<1>{aws_region}',
                    config_content
                )
                # Account name (only if provided)
                if aws_account_name:
                    config_content = re.sub(
                        r'(account_name:\s+)[^\s#]+',
                        f'\\g<1>{aws_account_name}',
                        config_content
                    )
                # Account ID (only if provided)
                if aws_account_id:
                    config_content = re.sub(
                        r'(account_id:\s+)[^\s#]+',
                        f'\\g<1>{aws_account_id}',
                        config_content
                    )
                # SSO profile
                config_content = re.sub(
                    r'(sso_profile:\s+)[^\s#]+',
                    f'\\g<1>{aws_profile}',
                    config_content
                )
                # Access key ID (only if provided)
                if aws_access_key_id:
                    config_content = re.sub(
                        r'(access_key_id:\s+)[^\s#]+',
                        f'\\g<1>{aws_access_key_id}',
                        config_content
                    )
                # Secret access key (only if provided)
                if aws_secret_access_key:
                    config_content = re.sub(
                        r'(secret_access_key:\s+)[^\s#]+',
                        f'\\g<1>{aws_secret_access_key}',
                        config_content
                    )
                # Session token (only if provided)
                if aws_session_token:
                    config_content = re.sub(
                        r'(session_token:\s+)[^\s#]+',
                        f'\\g<1>{aws_session_token}',
                        config_content
                    )
                # Cost tracking
                config_content = re.sub(
                    r'(cost_tracking:\s*\n\s+enabled:\s+)(true|false)',
                    f'\\g<1>{str(enable_cost_tracking).lower()}',
                    config_content
                )

            # Ollama settings
            if use_ollama:
                config_content = re.sub(
                    r'(base_url:\s+")[^"]+(")',
                    f'\\g<1>{ollama_base_url}\\g<2>',
                    config_content
                )

            # Anthropic settings - update api_key under anthropic section
            if use_anthropic and anthropic_api_key:
                config_content = re.sub(
                    r'(anthropic:\s*\n\s+enabled:\s+(?:true|false)\s*#[^\n]*\n\s+api_key:\s+)[^\s#]+',
                    f'\\g<1>{anthropic_api_key}',
                    config_content
                )

            # Interface settings
            config_content = re.sub(
                r'(type:\s+)(cli|web)(\s+#)',
                f'\\g<1>{interface_type}\\g<3>',
                config_content
            )

            # Web settings
            if interface_type == "web":
                config_content = re.sub(
                    r'(ssl:\s*\n\s+enabled:\s+)(true|false)',
                    f'\\g<1>{str(web_ssl_enabled).lower()}',
                    config_content
                )
                config_content = re.sub(
                    r'(dark_theme:\s+)(true|false)',
                    f'\\g<1>{str(web_dark_theme).lower()}',
                    config_content
                )

            # Model settings
            config_content = re.sub(
                r'(max_tokens:\s+)\d+',
                f'\\g<1>{max_tokens}',
                config_content
            )
            config_content = re.sub(
                r'(temperature:\s+)[\d.]+',
                f'\\g<1>{temperature}',
                config_content
            )

            # Features
            config_content = re.sub(
                r'(mcp_config:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(enable_mcp).lower()}',
                config_content
            )

            # Embedded Filesystem Tools
            config_content = re.sub(
                r'(filesystem:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(enable_filesystem_tools).lower()}',
                config_content
            )
            if enable_filesystem_tools:
                # Allowed path - need to handle both Unix and Windows paths
                escaped_path = filesystem_allowed_path.replace('\\', '/')
                config_content = re.sub(
                    r'(allowed_path:\s+)[^\s#]+',
                    f'\\g<1>{escaped_path}',
                    config_content
                )
                # Access mode
                config_content = re.sub(
                    r'(access_mode:\s+)(read|read_write)',
                    f'\\g<1>{filesystem_access_mode}',
                    config_content
                )

            # Embedded Document Tools
            config_content = re.sub(
                r'(documents:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(enable_document_tools).lower()}',
                config_content
            )
            if enable_document_tools:
                # Allowed path
                escaped_doc_path = document_allowed_path.replace('\\', '/')
                config_content = re.sub(
                    r'(documents:\s*\n\s+enabled:\s+(?:true|false)\s*\n\s+allowed_path:\s+)[^\s#]+',
                    f'\\g<1>{escaped_doc_path}',
                    config_content
                )
                # Access mode
                config_content = re.sub(
                    r'(documents:\s*\n\s+enabled:\s+(?:true|false)\s*\n\s+allowed_path:\s+[^\s#]+\s*\n\s+access_mode:\s+)(read|read_write)',
                    f'\\g<1>{document_access_mode}',
                    config_content
                )
                # Max file size
                config_content = re.sub(
                    r'(documents:.*?max_file_size_mb:\s+)\d+',
                    f'\\g<1>{document_max_file_size}',
                    config_content,
                    flags=re.DOTALL
                )
                # Max PDF pages
                config_content = re.sub(
                    r'(max_pdf_pages:\s+)\d+',
                    f'\\g<1>{document_max_pdf_pages}',
                    config_content
                )
                # Max Excel rows
                config_content = re.sub(
                    r'(max_excel_rows:\s+)\d+',
                    f'\\g<1>{document_max_excel_rows}',
                    config_content
                )
                # Templates path (if provided)
                if document_templates_path:
                    escaped_templates_path = document_templates_path.replace('\\', '/')
                    config_content = re.sub(
                        r'(templates_path:\s+)([^\s#]+)',
                        f'\\g<1>{escaped_templates_path}',
                        config_content
                    )
                # Default author (if provided)
                if document_default_author:
                    config_content = re.sub(
                        r'(default_author:\s+)([^\s#]+)',
                        f'\\g<1>{document_default_author}',
                        config_content
                    )

            # Embedded Archive Tools
            config_content = re.sub(
                r'(archives:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(enable_archive_tools).lower()}',
                config_content
            )
            if enable_archive_tools:
                # Allowed path
                escaped_archive_path = archive_allowed_path.replace('\\', '/')
                config_content = re.sub(
                    r'(archives:\s*\n\s+enabled:\s+(?:true|false)\s*\n\s+allowed_path:\s+)[^\s#]+',
                    f'\\g<1>{escaped_archive_path}',
                    config_content
                )
                # Access mode
                config_content = re.sub(
                    r'(archives:\s*\n\s+enabled:\s+(?:true|false)\s*\n\s+allowed_path:\s+[^\s#]+\s*\n\s+access_mode:\s+)(read|read_write)',
                    f'\\g<1>{archive_access_mode}',
                    config_content
                )
                # Max file size
                config_content = re.sub(
                    r'(archives:.*?max_file_size_mb:\s+)\d+',
                    f'\\g<1>{archive_max_file_size}',
                    config_content,
                    flags=re.DOTALL
                )
                # Max files to list
                config_content = re.sub(
                    r'(max_files_to_list:\s+)\d+',
                    f'\\g<1>{archive_max_files_to_list}',
                    config_content
                )

            # Tool Permissions
            config_content = re.sub(
                r'(tool_permissions:\s*\n\s+auto_approve:\s+)(true|false)',
                f'\\g<1>{str(auto_approve_tools).lower()}',
                config_content
            )

            # Prompt Inspection settings
            config_content = re.sub(
                r'(prompt_inspection:\s*\n\s+enabled:\s+)(true|false)',
                f'\\g<1>{str(enable_prompt_inspection).lower()}',
                config_content
            )

            if enable_prompt_inspection:
                # Inspection level
                config_content = re.sub(
                    r'(inspection_level:\s+)(basic|standard|strict)',
                    f'\\g<1>{inspection_level}',
                    config_content
                )
                # Action
                config_content = re.sub(
                    r'(action:\s+)(warn|block|sanitise|log_only)',
                    f'\\g<1>{inspection_action}',
                    config_content
                )
                # LLM inspection enabled
                config_content = re.sub(
                    r'(llm_inspection:\s*\n\s+enabled:\s+)(true|false)',
                    f'\\g<1>{str(llm_inspection_enabled).lower()}',
                    config_content
                )
                # LLM inspection settings (only if enabled)
                if llm_inspection_enabled:
                    config_content = re.sub(
                        r'(llm_inspection:.*?model:\s+)[^\n]+',
                        f'\\g<1>{llm_inspection_model}',
                        config_content,
                        flags=re.DOTALL
                    )
                    config_content = re.sub(
                        r'(llm_inspection:.*?provider:\s+)[^\n]+',
                        f'\\g<1>{llm_inspection_provider}',
                        config_content,
                        flags=re.DOTALL
                    )
                    config_content = re.sub(
                        r'(llm_inspection:.*?confidence_threshold:\s+)[\d.]+',
                        f'\\g<1>{llm_inspection_confidence}',
                        config_content,
                        flags=re.DOTALL
                    )

            # Create destination directory if it doesn't exist
            os.makedirs(dest_config_dir, exist_ok=True)

            # Write config file
            with open(dest_config, 'w', encoding='utf-8') as f:
                f.write(config_content)

            cli.console.print()
            cli.print_success("✓ Configuration file created successfully!")
            cli.console.print()
            cli.print_info(f"Location: {dest_config}")
            cli.console.print()

            # Write secrets.yaml if there are secrets to store
            if secrets_to_store:
                import yaml
                secrets_yaml_content = {"secrets": secrets_to_store}

                # Ensure secrets directory exists
                os.makedirs(secrets_dir, exist_ok=True)

                with open(secrets_file, 'w', encoding='utf-8') as f:
                    yaml.dump(secrets_yaml_content, f, default_flow_style=False, sort_keys=False)

                cli.console.print()
                cli.print_separator("─")
                cli.console.print("[bold green]Secrets Written to secrets.yaml:[/bold green]")
                for secret in secrets_to_store:
                    cli.console.print(f"  • {secret['name']}")
                cli.console.print()
                cli.print_info(f"Location: {secrets_file}")
                cli.console.print()
                cli.console.print("[dim]On next application startup, secrets will be automatically[/dim]")
                cli.console.print("[dim]ingested into the secrets manager and secrets.yaml will be deleted.[/dim]")
                cli.console.print()
                cli.console.print("[dim]Secrets are referenced in config.yaml as SEC/<key_name>.[/dim]")
                cli.print_separator("─")
                cli.console.print()

            cli.console.print("[dim]You can manually edit this file to customise additional settings.[/dim]")
            cli.console.print("[dim]All configuration options are documented with comments in the file.[/dim]")
            cli.console.print()

        except Exception as e:
            cli.print_error(f"Failed to create configuration: {e}")
            logging.exception("Setup wizard error")
            return

    def define_args(self, arg_parser: ArgumentParser):
        """Define command-line arguments."""
        arg_parser.add_argument(
            '--setup',
            action='store_true',
            help='Run interactive setup wizard to create config.yaml'
        )

    def display_bedrock_costs(self):
        """Display AWS Bedrock usage costs if available."""
        if self.bedrock_costs and self.cost_tracker:
            self.cli.display_bedrock_costs(self.bedrock_costs)
        else:
            logging.debug("No Bedrock cost information available to display")

    def regather_and_display_costs(self):
        """Re-gather AWS Bedrock cost information and display it."""
        # Check if cost tracking is enabled (new path with legacy fallback)
        cost_tracking_enabled = self._get_nested_setting(_SETTING_BEDROCK_COST_TRACKING, None)
        if cost_tracking_enabled is None:
            cost_tracking_enabled = self.settings.get(_SETTING_COST_TRACKING, False)
        if not cost_tracking_enabled:
            self.cli.print_warning("Cost tracking is disabled in configuration")
            return

        if not self.authenticator:
            self.cli.print_warning("AWS Bedrock is not configured - cannot retrieve costs")
            return

        self.cli.print_info("Re-gathering AWS Bedrock cost information...")

        try:
            if not hasattr(self, 'cost_tracker') or self.cost_tracker is None:
                cost_explorer_client = self.authenticator.get_client('ce')
                from dtSpark.aws import CostTracker
                self.cost_tracker = CostTracker(cost_explorer_client)

            with self.cli.status_indicator("Retrieving usage costs..."):
                self.bedrock_costs = self.cost_tracker.get_bedrock_costs()

            if self.bedrock_costs:
                self.display_bedrock_costs()
                self.cli.print_success("Cost information updated successfully")
            else:
                self.cli.print_warning("No cost information available")
        except Exception as e:
            logging.error(f"Error retrieving cost information: {e}")
            self.cli.print_error(f"Failed to retrieve cost information: {e}")

    def start_new_conversation(self) -> bool:
        """
        Create a new conversation.

        Returns:
            True if conversation was created successfully, False otherwise
        """
        # Get conversation name
        conv_name = self.cli.get_input("\nEnter a name for this conversation")
        if not conv_name:
            self.cli.print_error("Conversation name cannot be empty")
            return False

        # Select model for this conversation (or use configured model)
        if self.configured_model_id:
            # Model is locked via configuration
            model_id = self.configured_model_id
            try:
                self.llm_manager.set_model(model_id, self.configured_provider)
                # Update references after model change
                self.bedrock_service = self.llm_manager.get_active_service()
                self.conversation_manager.bedrock_service = self.bedrock_service
                provider_info = f" via {self.configured_provider}" if self.configured_provider else ""
                self.cli.print_info(f"Using configured model: {model_id}{provider_info}")
            except ValueError as e:
                self.cli.print_error(f"Failed to set configured model: {e}")
                if self.configured_provider:
                    self.cli.print_info(f"Provider '{self.configured_provider}' may not be enabled or model not available")
                return False
        else:
            # Allow user to select model
            model_id = self.select_model()
            if not model_id or model_id == 'QUIT':
                self.cli.print_error("Model selection cancelled")
                return False

        # Ask if user wants to provide instructions
        provide_instructions = self.cli.confirm("Would you like to provide instructions for this conversation?")
        instructions = None

        if provide_instructions:
            instructions = self.cli.get_multiline_input("Enter instructions/system prompt for this conversation")
            if not instructions.strip():
                instructions = None

        # Ask for compaction threshold
        default_threshold = self.settings.get('conversation.rollup_threshold', 0.3)
        compaction_threshold = None  # None means use global default

        self.cli.print_info(f"\nContext compaction triggers when token usage reaches a percentage of the model's context window.")
        self.cli.print_info(f"Lower values compact sooner (reduces costs), higher values preserve more context.")
        self.cli.print_info(f"Default: {default_threshold:.0%} of context window")

        custom_threshold = self.cli.confirm("Would you like to set a custom compaction threshold?")

        if custom_threshold:
            while True:
                threshold_input = self.cli.get_input(f"Enter threshold (0.1-1.0) [default: {default_threshold}]")
                if not threshold_input.strip():
                    # User pressed enter, use default
                    compaction_threshold = default_threshold
                    self.cli.print_info(f"Using default threshold: {default_threshold:.0%}")
                    break
                try:
                    threshold_value = float(threshold_input)
                    if 0.1 <= threshold_value <= 1.0:
                        compaction_threshold = threshold_value
                        self.cli.print_success(f"Compaction threshold set to: {threshold_value:.0%}")
                        break
                    else:
                        self.cli.print_error("Threshold must be between 0.1 and 1.0")
                except ValueError:
                    self.cli.print_error("Please enter a valid number between 0.1 and 1.0")

        # Ask if user wants to attach files
        from dtSpark.files import FileManager
        supported_extensions = FileManager.get_supported_extensions()
        file_paths = self.cli.get_file_attachments(supported_extensions)

        # Create the conversation
        conversation_id = self.conversation_manager.create_conversation(
            name=conv_name,
            model_id=model_id,
            instructions=instructions,
            compaction_threshold=compaction_threshold
        )

        if conversation_id:
            self.conversation_manager.load_conversation(conversation_id)

            # Attach files if any
            if file_paths:
                self.conversation_manager.attach_files(file_paths)
                files = self.conversation_manager.get_attached_files()
                if files:
                    self.cli.display_attached_files(files)

            self.cli.print_success(f"Created new conversation: {conv_name}")
            return True
        else:
            self.cli.print_error("Failed to create conversation")
            return False

    def select_existing_conversation(self) -> bool:
        """
        List and select an existing conversation.

        Returns:
            True if conversation was loaded successfully, False otherwise
        """
        conversations = self.conversation_manager.get_active_conversations()
        conversation_id = self.cli.display_conversations(conversations)

        if conversation_id:
            # Load existing conversation
            if self.conversation_manager.load_conversation(conversation_id):
                conv_info = self.conversation_manager.get_current_conversation_info()

                # Set the model from the conversation
                model_id = conv_info['model_id']
                self.llm_manager.set_model(model_id)
                # Update references after model change
                self.bedrock_service = self.llm_manager.get_active_service()
                self.conversation_manager.bedrock_service = self.bedrock_service

                self.cli.print_success(f"Loaded conversation: {conv_info['name']}")
                self.cli.print_info(f"Using model: {model_id}")

                # Display attached files if any
                files = self.conversation_manager.get_attached_files()
                if files:
                    self.cli.display_attached_files(files)

                return True
            else:
                self.cli.print_error("Failed to load conversation")
                return False
        else:
            return False

    def manage_autonomous_actions(self):
        """
        Manage autonomous actions - display menu and handle user choices.
        """
        import asyncio

        while True:
            # Get count of failed actions for display
            failed_count = self.database.get_failed_action_count()

            choice = self.cli.display_autonomous_actions_menu(failed_count)

            if choice == 'back':
                break

            elif choice == 'list':
                # List all actions
                actions = self.database.get_all_actions()
                self.cli.display_actions_list(actions)

            elif choice == 'create':
                # Choose creation method
                creation_method = self.cli.select_action_creation_method()

                if creation_method == 'manual':
                    # Manual wizard
                    models = self.llm_manager.list_all_models()

                    # Get available tools
                    tools = []
                    if self.mcp_manager:
                        try:
                            loop = getattr(self.mcp_manager, '_initialization_loop', None)
                            if loop and not loop.is_closed():
                                tools = loop.run_until_complete(self.mcp_manager.list_all_tools())
                        except Exception as e:
                            logging.warning(f"Could not get tools list: {e}")

                    action_config = self.cli.create_action_wizard(models, tools)

                    if action_config:
                        try:
                            # Create the action
                            action_id = self.database.create_action(
                                name=action_config['name'],
                                description=action_config['description'],
                                action_prompt=action_config['action_prompt'],
                                model_id=action_config['model_id'],
                                schedule_type=action_config['schedule_type'],
                                schedule_config=action_config['schedule_config'],
                                context_mode=action_config['context_mode'],
                                max_failures=action_config['max_failures'],
                                max_tokens=action_config.get('max_tokens', 8192)
                            )

                            # Set tool permissions
                            if action_config.get('tool_permissions'):
                                self.database.set_action_tool_permissions_batch(
                                    action_id, action_config['tool_permissions']
                                )

                            # Schedule the action
                            if self.action_scheduler:
                                self.action_scheduler.schedule_action(
                                    action_id=action_id,
                                    action_name=action_config['name'],
                                    schedule_type=action_config['schedule_type'],
                                    schedule_config=action_config['schedule_config'],
                                    user_guid=self.user_guid
                                )

                            self.cli.print_success(f"Created action: {action_config['name']}")

                        except Exception as e:
                            self.cli.print_error(f"Failed to create action: {e}")

                elif creation_method == 'prompt_driven':
                    # Prompt-driven creation with LLM
                    self._create_action_prompt_driven()

            elif choice == 'runs':
                # View action runs
                actions = self.database.get_all_actions()
                action_id = self.cli.select_action(actions, "Select action to view runs")

                if action_id:
                    action = self.database.get_action(action_id)
                    runs = self.database.get_action_runs(action_id)
                    self.cli.display_action_runs(runs, action['name'] if action else None)

                    # Option to view run details
                    if runs:
                        run_id = self.cli.select_run(runs, "Select a run for details (or 0 to go back)")
                        if run_id:
                            run = self.database.get_action_run(run_id)
                            if run:
                                self.cli.display_run_details(run)

            elif choice == 'run_now':
                # Run action immediately
                actions = self.database.get_all_actions()
                action_id = self.cli.select_action(actions, "Select action to run now")

                if action_id and self.action_scheduler:
                    success = self.action_scheduler.run_action_now(action_id, self.user_guid)
                    if success:
                        self.cli.print_success("Action triggered for immediate execution")
                    else:
                        self.cli.print_error("Failed to trigger action")
                elif not self.action_scheduler:
                    self.cli.print_error("Action scheduler not available")

            elif choice == 'toggle':
                # Enable/disable action
                actions = self.database.get_all_actions()
                action_id = self.cli.select_action(actions, "Select action to toggle")

                if action_id:
                    action = self.database.get_action(action_id)
                    if action:
                        if action['is_enabled']:
                            self.database.disable_action(action_id)
                            if self.action_scheduler:
                                self.action_scheduler.unschedule_action(action_id)
                            self.cli.print_success(f"Disabled action: {action['name']}")
                        else:
                            self.database.enable_action(action_id)
                            if self.action_scheduler:
                                self.action_scheduler.schedule_action(
                                    action_id=action_id,
                                    action_name=action['name'],
                                    schedule_type=action['schedule_type'],
                                    schedule_config=action['schedule_config'],
                                    user_guid=self.user_guid
                                )
                            self.cli.print_success(f"Enabled action: {action['name']}")

            elif choice == 'delete':
                # Delete action
                actions = self.database.get_all_actions()
                action_id = self.cli.select_action(actions, "Select action to delete")

                if action_id:
                    action = self.database.get_action(action_id)
                    if action and self.cli.confirm(f"Delete action '{action['name']}'?"):
                        if self.action_scheduler:
                            self.action_scheduler.unschedule_action(action_id)
                        self.database.delete_action(action_id)
                        self.cli.print_success(f"Deleted action: {action['name']}")

            elif choice == 'export':
                # Export run results
                actions = self.database.get_all_actions()
                action_id = self.cli.select_action(actions, "Select action")

                if action_id:
                    runs = self.database.get_action_runs(action_id)
                    run_id = self.cli.select_run(runs, "Select run to export")

                    if run_id:
                        export_format = self.cli.select_export_format()
                        if export_format:
                            run = self.database.get_action_run(run_id)
                            if run:
                                if export_format == 'html':
                                    content = run.get('result_html') or f"<pre>{run.get('result_text', 'No result')}</pre>"
                                elif export_format == 'markdown':
                                    content = f"# Action Run {run_id}\n\n"
                                    content += f"**Status:** {run['status']}\n\n"
                                    content += f"## Result\n\n{run.get('result_text', 'No result')}"
                                else:
                                    content = run.get('result_text', 'No result')

                                # Copy to clipboard
                                if copy_to_clipboard(content):
                                    self.cli.print_success(f"Exported {export_format.upper()} to clipboard")
                                else:
                                    # Show content if clipboard failed
                                    self.cli.console.print(f"\n{content}\n")

            else:
                self.cli.print_error("Invalid option")

    def _create_action_prompt_driven(self):
        """
        Create an autonomous action using conversational LLM approach.

        The user describes what they want to schedule in natural language,
        and the LLM guides them through the creation process.
        """
        import json
        from dtSpark.scheduler.creation_tools import (
            get_action_creation_tools,
            execute_creation_tool,
            ACTION_CREATION_SYSTEM_PROMPT
        )

        # Step 1: Select model (will be used for both creation and execution)
        models = self.llm_manager.list_all_models()
        if not models:
            self.cli.print_error(_MSG_NO_MODELS)
            return

        self.cli.console.print("\n[bold cyan]Select Model[/bold cyan]")
        self.cli.console.print("[dim]This model will be used for the creation process AND the scheduled task.[/dim]\n")

        for i, model in enumerate(models, 1):
            from dtSpark.cli_interface import extract_friendly_model_name
            friendly_name = extract_friendly_model_name(model.get('id', ''))
            self.cli.console.print(f"  [{i}] {friendly_name}")

        model_choice = self.cli.get_input("Enter choice")
        try:
            model_idx = int(model_choice) - 1
            if model_idx < 0 or model_idx >= len(models):
                self.cli.print_error("Invalid model selection")
                return
            model_id = models[model_idx]['id']
        except ValueError:
            self.cli.print_error("Invalid input")
            return

        # Step 2: Get creation tools
        creation_tools = get_action_creation_tools()

        # Build config for tool listing (includes embedded_tools settings)
        creation_config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': self.settings.get('embedded_tools.filesystem.enabled', False),
                    'allowed_path': self.settings.get('embedded_tools.filesystem.allowed_path', './'),
                    'access_mode': self.settings.get('embedded_tools.filesystem.access_mode', 'read')
                }
            }
        }

        # Step 3: Set the model for the creation conversation
        # Store the previous model to restore after creation
        previous_model = None
        previous_provider = self.llm_manager.get_active_provider()
        if self.llm_manager.active_service:
            previous_model = getattr(self.llm_manager.active_service, 'model_id', None)

        try:
            self.llm_manager.set_model(model_id)
        except Exception as e:
            self.cli.print_error(f"Failed to set model: {e}")
            return

        # Step 4: Display header and start conversation
        self.cli.display_creation_prompt_header()

        # Conversation loop
        messages = []
        action_created = False

        try:
            while not action_created:
                # Get user input
                user_input = self.cli.get_multiline_input("Your message")

                if not user_input:
                    continue

                # Check for cancel command
                if user_input.lower().strip() == 'cancel':
                    self.cli.print_warning("Action creation cancelled.")
                    return

                # Add user message to history
                messages.append({'role': 'user', 'content': user_input})
                self.cli.display_creation_conversation_message('user', user_input)

                # Continue processing tool results until we get a final response
                while True:
                    try:
                        # Invoke LLM with creation tools
                        response = self.llm_manager.invoke_model(
                            messages=messages,
                            system=ACTION_CREATION_SYSTEM_PROMPT,
                            tools=creation_tools,
                            max_tokens=4096
                        )
                    except Exception as e:
                        self.cli.print_error(f"LLM invocation failed: {e}")
                        break

                    # Check for error response
                    if response.get('error'):
                        error_msg = response.get('error_message', 'Unknown error')
                        self.cli.print_error(f"LLM error: {error_msg}")
                        break

                    # Process response
                    # Note: Bedrock service returns 'content' as text string and
                    # 'content_blocks' as the list of content blocks (text, tool_use)
                    assistant_content = ""
                    tool_calls = []

                    content_blocks = response.get('content_blocks', [])
                    for block in content_blocks:
                        if block.get('type') == 'text':
                            assistant_content += block.get('text', '')
                        elif block.get('type') == 'tool_use':
                            tool_calls.append(block)

                    # Display assistant text if any
                    if assistant_content:
                        self.cli.display_creation_conversation_message('assistant', assistant_content)

                    # If no tool calls, we're done with this turn
                    if not tool_calls:
                        # Add assistant message to history
                        messages.append({
                            'role': 'assistant',
                            'content': content_blocks
                        })
                        break

                    # Process tool calls
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call.get('name')
                        tool_input = tool_call.get('input', {})
                        tool_id = tool_call.get('id')

                        # Execute the creation tool
                        try:
                            result = execute_creation_tool(
                                tool_name=tool_name,
                                tool_input=tool_input,
                                mcp_manager=self.mcp_manager,
                                database=self.database,
                                scheduler_manager=self.action_scheduler,
                                model_id=model_id,
                                user_guid=self.user_guid,
                                config=creation_config
                            )

                            # Display tool call result
                            self.cli.display_creation_tool_call(tool_name, result)

                            # Check if action was created successfully
                            if tool_name == 'create_autonomous_action' and result.get('success'):
                                action_created = True

                            tool_results.append({
                                'type': 'tool_result',
                                'tool_use_id': tool_id,
                                'content': json.dumps(result)
                            })

                        except Exception as e:
                            logging.error(f"Tool execution error: {e}")
                            tool_results.append({
                                'type': 'tool_result',
                                'tool_use_id': tool_id,
                                'content': json.dumps({'error': str(e)})
                            })

                    # Add assistant message and tool results to history
                    messages.append({
                        'role': 'assistant',
                        'content': content_blocks
                    })
                    messages.append({
                        'role': 'user',
                        'content': tool_results
                    })

                    # If action was created, we can exit
                    if action_created:
                        break

        finally:
            # Restore previous model if one was active
            if previous_model:
                try:
                    self.llm_manager.set_model(previous_model)
                except Exception:
                    pass  # Silently ignore if we can't restore

        if action_created:
            self.cli.console.print("\n[bold green]━━━ Action created successfully ━━━[/bold green]\n")

    def select_model(self):
        """Handle model selection."""
        # Show progress while fetching models
        with self.cli.create_progress() as progress:
            task = progress.add_task("[cyan]Fetching available models...", total=100)
            models = self.llm_manager.list_all_models()
            progress.update(task, advance=100)

        if not models:
            self.cli.print_error(_MSG_NO_MODELS)
            return None

        model_id = self.cli.display_models(models)

        if model_id:
            # Check for quit command
            if model_id == 'QUIT':
                return None

            # LLM manager will automatically determine the provider for this model
            self.llm_manager.set_model(model_id)
            # Update references after model change
            self.bedrock_service = self.llm_manager.get_active_service()
            self.conversation_manager.bedrock_service = self.bedrock_service
            self.cli.print_success(f"Selected model: {model_id}")
            return model_id
        else:
            self.cli.print_error("No model selected")
            return None

    def setup_conversation(self):
        """Setup conversation - either load existing or create new."""
        conversations = self.conversation_manager.get_active_conversations()

        conversation_id = self.cli.display_conversations(conversations)

        if conversation_id:
            # Load existing conversation
            if self.conversation_manager.load_conversation(conversation_id):
                conv_info = self.conversation_manager.get_current_conversation_info()

                # Set the model from the conversation
                model_id = conv_info['model_id']
                self.llm_manager.set_model(model_id)
                # Update references after model change
                self.bedrock_service = self.llm_manager.get_active_service()
                self.conversation_manager.bedrock_service = self.bedrock_service

                self.cli.print_success(f"Loaded conversation: {conv_info['name']}")
                self.cli.print_info(f"Using model: {model_id}")

                # Display attached files if any
                files = self.conversation_manager.get_attached_files()
                if files:
                    self.cli.display_attached_files(files)

                return True
            else:
                self.cli.print_error("Failed to load conversation")
                return False
        else:
            # Create new conversation
            # Step 1: Get conversation name
            conv_name = self.cli.get_input("\nEnter a name for this conversation")
            if not conv_name:
                self.cli.print_error("Conversation name cannot be empty")
                return False

            # Step 2: Select model for this conversation (or use configured model)
            if self.configured_model_id:
                # Model is locked via configuration
                model_id = self.configured_model_id
                try:
                    self.llm_manager.set_model(model_id, self.configured_provider)
                    # Update references after model change
                    self.bedrock_service = self.llm_manager.get_active_service()
                    self.conversation_manager.bedrock_service = self.bedrock_service
                    provider_info = f" via {self.configured_provider}" if self.configured_provider else ""
                    self.cli.print_info(f"Using configured model: {model_id}{provider_info}")
                except ValueError as e:
                    self.cli.print_error(f"Failed to set configured model: {e}")
                    if self.configured_provider:
                        self.cli.print_info(f"Provider '{self.configured_provider}' may not be enabled or model not available")
                    return False
            else:
                # Allow user to select model
                model_id = self.select_model()
                if not model_id or model_id == 'QUIT':
                    self.cli.print_error("Model selection cancelled")
                    return False

            # Step 3: Ask if user wants to provide instructions
            provide_instructions = self.cli.confirm("Would you like to provide instructions for this conversation?")
            instructions = None

            if provide_instructions:
                instructions = self.cli.get_multiline_input("Enter instructions/system prompt for this conversation")
                if not instructions.strip():
                    instructions = None

            # Step 4: Ask if user wants to attach files
            from dtSpark.files import FileManager
            supported_extensions = FileManager.get_supported_extensions()
            file_paths = self.cli.get_file_attachments(supported_extensions)

            # Create conversation with selected model
            self.conversation_manager.create_conversation(conv_name, model_id, instructions)
            self.cli.print_success(f"Created new conversation: {conv_name}")
            self.cli.print_info(f"Using model: {model_id}")
            if instructions:
                self.cli.print_info("Instructions have been set for this conversation")

            # Attach files if any were selected
            if file_paths:
                self.conversation_manager.attach_files(file_paths)

            return True

    def chat_loop(self):
        """Main chat loop."""
        while True:
            # Display conversation info
            conv_info = self.conversation_manager.get_current_conversation_info()
            token_count = self.conversation_manager.get_current_token_count()
            attached_files = self.conversation_manager.get_attached_files()
            # Get context window (actual input limit) instead of max_tokens (output limit)
            context_window = self.conversation_manager.get_context_window()

            # Get access method from active service
            access_method = self.llm_manager.get_active_service().get_access_info() if self.llm_manager.get_active_service() else None

            if conv_info:
                self.cli.display_conversation_info(conv_info, token_count, context_window, attached_files, access_method=access_method)

            # Get user input
            user_message = self.cli.chat_prompt()

            if user_message is None:
                # User wants to quit
                if self.cli.confirm("Are you sure you want to exit?"):
                    break
                else:
                    continue

            if user_message == 'END_CHAT':
                # End current chat and return to conversation/model selection
                self.cli.print_info("Ending current chat session")
                break

            if user_message == 'SHOW_HISTORY':
                # Show conversation history
                messages = self.conversation_manager.get_conversation_history()
                self.cli.display_conversation_history(messages)
                self.cli.wait_for_enter()
                continue

            if user_message == 'SHOW_INFO':
                # Show detailed info with model usage breakdown
                model_usage = self.conversation_manager.get_model_usage_breakdown()
                self.cli.display_conversation_info(conv_info, token_count, context_window, attached_files, model_usage, detailed=True, access_method=access_method)
                # Also show attached files details if any
                if attached_files:
                    self.cli.display_attached_files(attached_files)
                # Show MCP server states if MCP is enabled
                if self.mcp_manager:
                    try:
                        server_states = self.conversation_manager.get_mcp_server_states()
                        if server_states:
                            self.cli.display_mcp_server_states(server_states)
                    except Exception as e:
                        logging.error(f"Failed to get MCP server states for info display: {e}")
                        self.cli.print_warning("Could not retrieve MCP server states")

                # Show AWS Bedrock usage costs if available
                if self.cost_tracker:
                    try:
                        bedrock_costs = self.cost_tracker.get_bedrock_costs()
                        self.cli.print_separator("─")
                        self.cli.print_info("💰 AWS Bedrock Usage Costs")
                        self.cli.print_separator("─")

                        cost_lines = self.cost_tracker.format_cost_report(bedrock_costs)
                        for line in cost_lines:
                            if line.startswith('  •'):
                                # Indent breakdown items
                                self.cli.print_info(f"  {line}")
                            else:
                                self.cli.print_info(line)
                    except Exception as e:
                        logging.debug(f"Could not retrieve cost information for /info: {e}")
                        self.cli.print_info("Cost information temporarily unavailable")

                self.cli.wait_for_enter()
                continue

            if user_message == 'EXPORT_CONVERSATION':
                # Export conversation with format and tool inclusion options
                self.cli.print_separator("═")
                self.cli.print_info("Export Conversation")
                self.cli.print_separator("═")

                # Select export format
                format_choice = self.cli.get_input("Select export format:\n"
                                                   "  [1] Markdown (.md)\n"
                                                   "  [2] HTML (.html)\n"
                                                   "  [3] CSV (.csv)\n"
                                                   "Enter choice")

                format_map = {
                    '1': ('markdown', '.md'),
                    '2': ('html', '.html'),
                    '3': ('csv', '.csv')
                }

                if format_choice not in format_map:
                    self.cli.print_error("Invalid choice")
                    self.cli.wait_for_enter()
                    continue

                export_format, file_extension = format_map[format_choice]

                # Ask about tool inclusion
                include_tools = self.cli.confirm("Include tool use details in export?")

                # Get filename
                base_name = conv_info['name'].replace(' ', '_')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                default_filename = f"{base_name}_{timestamp}{file_extension}"

                file_path = self.cli.get_input(f"Enter export file path (default: ./{default_filename})")

                if not file_path.strip():
                    file_path = default_filename

                # Ensure correct extension
                if not file_path.endswith(file_extension):
                    # Remove any existing extension and add correct one
                    if '.' in file_path:
                        file_path = file_path.rsplit('.', 1)[0]
                    file_path += file_extension

                # Export conversation
                if self.conversation_manager.export_conversation(file_path, export_format, include_tools):
                    self.cli.print_success(f"Conversation exported to: {file_path}")
                    self.cli.print_info(f"Format: {export_format.upper()}")
                    self.cli.print_info(f"Tool details: {'Included' if include_tools else 'Excluded'}")
                else:
                    self.cli.print_error("Failed to export conversation")

                self.cli.wait_for_enter()
                continue

            if user_message == 'DELETE_CONVERSATION':
                # Delete current conversation
                if self.cli.confirm(f"Are you sure you want to delete '{conv_info['name']}'? This cannot be undone"):
                    if self.conversation_manager.delete_current_conversation():
                        self.cli.print_success("Conversation deleted")
                        break  # Exit chat loop
                    else:
                        self.cli.print_error("Failed to delete conversation")
                else:
                    self.cli.print_info("Deletion cancelled")
                continue

            if user_message == 'ATTACH_FILES':
                # Attach files to current conversation
                from dtSpark.files import FileManager
                supported_extensions = FileManager.get_supported_extensions()
                file_paths = self.cli.get_file_attachments(supported_extensions)

                if file_paths:
                    # Process and attach files
                    success = self.conversation_manager.attach_files_with_message(file_paths)
                    if success:
                        self.cli.print_success(f"Attached {len(file_paths)} file(s) to conversation")
                        # Refresh attached_files list
                        attached_files = self.conversation_manager.get_attached_files()
                        self.cli.display_attached_files(attached_files)
                    else:
                        self.cli.print_error("Some files failed to attach")
                else:
                    self.cli.print_info("No files attached")

                self.cli.wait_for_enter()
                continue

            if user_message == 'DELETE_FILES':
                # Check if conversation is predefined - if so, block file deletion
                if self.database.is_conversation_predefined(self.conversation_manager.current_conversation_id):
                    self.cli.print_error("Cannot delete files from predefined conversations")
                    self.cli.print_info(_MSG_MANAGED_CONVERSATION)
                    self.cli.wait_for_enter()
                    continue

                # Delete files from current conversation
                if not attached_files:
                    self.cli.print_info("No files attached to this conversation")
                    self.cli.wait_for_enter()
                    continue

                self.cli.print_separator("═")
                self.cli.print_info("Delete Attached Files")
                self.cli.print_separator("═")
                self.cli.console.print()

                # Display current attached files
                self.cli.display_attached_files(attached_files)
                self.cli.console.print()

                # Ask user for file IDs to delete
                self.cli.print_info("Enter file IDs to delete (comma-separated), or 'all' to delete all files")
                file_ids_input = self.cli.get_input("File IDs to delete").strip()

                if not file_ids_input:
                    self.cli.print_info(_MSG_DELETE_CANCELLED)
                    self.cli.wait_for_enter()
                    continue

                # Parse file IDs
                if file_ids_input.lower() == 'all':
                    # Confirm deleting all files
                    if self.cli.confirm(f"Are you sure you want to delete all {len(attached_files)} file(s)?"):
                        deleted_count = 0
                        for file_info in attached_files:
                            if self.conversation_manager.database.delete_file(file_info['id']):
                                deleted_count += 1

                        if deleted_count > 0:
                            self.cli.print_success(f"Deleted {deleted_count} file(s)")
                            # Refresh attached_files list
                            attached_files = self.conversation_manager.get_attached_files()
                        else:
                            self.cli.print_error("Failed to delete files")
                    else:
                        self.cli.print_info(_MSG_DELETE_CANCELLED)
                else:
                    # Parse comma-separated IDs
                    try:
                        file_ids = [int(id.strip()) for id in file_ids_input.split(',') if id.strip()]

                        if not file_ids:
                            self.cli.print_error("No valid file IDs provided")
                            self.cli.wait_for_enter()
                            continue

                        # Confirm deletion
                        if self.cli.confirm(f"Are you sure you want to delete {len(file_ids)} file(s)?"):
                            deleted_count = 0
                            failed_ids = []

                            for file_id in file_ids:
                                if self.conversation_manager.database.delete_file(file_id):
                                    deleted_count += 1
                                else:
                                    failed_ids.append(file_id)

                            if deleted_count > 0:
                                self.cli.print_success(f"Deleted {deleted_count} file(s)")
                                # Refresh attached_files list
                                attached_files = self.conversation_manager.get_attached_files()

                            if failed_ids:
                                self.cli.print_error(f"Failed to delete files with IDs: {', '.join(map(str, failed_ids))}")
                        else:
                            self.cli.print_info(_MSG_DELETE_CANCELLED)

                    except ValueError:
                        self.cli.print_error("Invalid file IDs. Please enter comma-separated numbers or 'all'")

                self.cli.wait_for_enter()
                continue

            if user_message == 'CHANGE_MODEL':
                # Check if conversation is predefined - if so, block model changes
                if self.database.is_conversation_predefined(self.conversation_manager.current_conversation_id):
                    self.cli.print_error("Cannot change model for predefined conversations")
                    self.cli.print_info(_MSG_MANAGED_CONVERSATION)
                    self.cli.wait_for_enter()
                    continue

                # Check if model is locked via configuration
                if self.configured_model_id:
                    self.cli.print_error("Model changing is disabled - model is locked via configuration")
                    self.cli.print_info(f"Configured model: {self.configured_model_id}")
                    self.cli.wait_for_enter()
                    continue

                # Change the model for the current conversation - show ALL available models from ALL providers
                with self.cli.create_progress() as progress:
                    task = progress.add_task("[cyan]Fetching available models from all providers...", total=100)
                    models = self.llm_manager.list_all_models()
                    progress.update(task, advance=100)

                if not models:
                    self.cli.print_error(_MSG_NO_MODELS)
                    self.cli.wait_for_enter()
                    continue

                # Let user select new model
                new_model_id = self.cli.display_models(models)

                if new_model_id:
                    # Update the model via LLM manager (which will switch providers if needed)
                    self.llm_manager.set_model(new_model_id)
                    # Update references after model change
                    self.bedrock_service = self.llm_manager.get_active_service()
                    self.conversation_manager.bedrock_service = self.bedrock_service

                    # Change the model in the conversation
                    if self.conversation_manager.change_model(new_model_id):
                        self.cli.print_success(f"Changed model to: {new_model_id}")
                    else:
                        self.cli.print_error("Failed to change model")
                else:
                    self.cli.print_info("Model change cancelled")

                self.cli.wait_for_enter()
                continue

            if user_message == 'COPY_LAST':
                # Copy last assistant response to clipboard
                last_message = self.conversation_manager.get_last_assistant_message()

                if last_message:
                    if copy_to_clipboard(last_message):
                        char_count = len(last_message)
                        self.cli.print_success(f"✓ Last assistant response copied to clipboard ({char_count:,} characters)")
                    else:
                        self.cli.print_error("Failed to copy to clipboard. Please ensure clipboard utilities are installed.")
                        if sys.platform not in ['win32', 'darwin']:
                            self.cli.print_info("Linux users: Install xclip or xsel (e.g., 'sudo apt install xclip')")
                else:
                    self.cli.print_warning("No assistant response found to copy")

                self.cli.wait_for_enter()
                continue

            if user_message == 'CHANGE_INSTRUCTIONS':
                # Check if conversation is predefined - if so, block instruction changes
                if self.database.is_conversation_predefined(self.conversation_manager.current_conversation_id):
                    self.cli.print_error("Cannot change instructions for predefined conversations")
                    self.cli.print_info(_MSG_MANAGED_CONVERSATION)
                    self.cli.wait_for_enter()
                    continue

                # Change/update the instructions for the current conversation
                self.cli.print_separator("═")
                self.cli.print_info("Update Conversation Instructions")
                self.cli.print_separator("═")

                # Show current instructions if any
                if conv_info.get('instructions'):
                    self.cli.console.print()
                    self.cli.console.print("[bold cyan]Current Instructions:[/bold cyan]")
                    self.cli.console.print(f"[dim italic]{conv_info['instructions']}[/dim italic]")
                    self.cli.console.print()
                else:
                    self.cli.console.print()
                    self.cli.print_info("No instructions currently set for this conversation")
                    self.cli.console.print()

                # Ask if user wants to set new instructions or clear them
                if self.cli.confirm("Would you like to set new instructions?"):
                    new_instructions = self.cli.get_multiline_input("Enter new instructions/system prompt (press Enter twice to finish)")

                    if new_instructions.strip():
                        # Set new instructions
                        if self.conversation_manager.update_instructions(new_instructions.strip()):
                            self.cli.print_success("Instructions updated successfully")
                        else:
                            self.cli.print_error("Failed to update instructions")
                    else:
                        self.cli.print_info("Instructions update cancelled (empty input)")
                elif conv_info.get('instructions') and self.cli.confirm("Would you like to clear the existing instructions?"):
                    # Clear instructions
                    if self.conversation_manager.update_instructions(None):
                        self.cli.print_success("Instructions cleared successfully")
                    else:
                        self.cli.print_error("Failed to clear instructions")
                else:
                    self.cli.print_info("Instructions unchanged")

                self.cli.wait_for_enter()
                continue

            if user_message == 'MCP_AUDIT':
                # Show MCP transaction audit information
                self.cli.print_separator("═")
                self.cli.print_info("MCP Transaction Audit")
                self.cli.print_separator("═")

                # Display options
                audit_choice = self.cli.get_input("Options:\n"
                                                 "  [1] View transactions for this conversation\n"
                                                 "  [2] View all recent transactions (last 50)\n"
                                                 "  [3] View statistics\n"
                                                 "  [4] Export to CSV\n"
                                                 "Enter choice")

                if audit_choice == '1':
                    # Show transactions for current conversation
                    transactions = self.database.get_mcp_transactions(
                        conversation_id=self.conversation_manager.current_conversation_id,
                        limit=50
                    )
                    self.cli.display_mcp_transactions(transactions, "Conversation MCP Transactions")

                elif audit_choice == '2':
                    # Show all recent transactions
                    transactions = self.database.get_mcp_transactions(limit=50)
                    self.cli.display_mcp_transactions(transactions, "Recent MCP Transactions")

                elif audit_choice == '3':
                    # Show statistics
                    stats = self.database.get_mcp_transaction_stats()
                    self.cli.display_mcp_stats(stats)

                elif audit_choice == '4':
                    # Export to CSV
                    default_filename = f"mcp_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    file_path = self.cli.get_input(f"Enter export file path (default: ./{default_filename})")

                    if not file_path.strip():
                        file_path = default_filename

                    # Ensure .csv extension
                    if not file_path.endswith('.csv'):
                        file_path += '.csv'

                    # Ask if user wants to export all or just this conversation
                    export_all = self.cli.confirm("Export all transactions? (No = current conversation only)")

                    conversation_id = None if export_all else self.conversation_manager.current_conversation_id

                    if self.database.export_mcp_transactions_to_csv(file_path, conversation_id):
                        self.cli.print_success(f"MCP transactions exported to: {file_path}")
                    else:
                        self.cli.print_error("Failed to export MCP transactions")

                else:
                    self.cli.print_error("Invalid choice")

                self.cli.wait_for_enter()
                continue

            if user_message == 'MCP_SERVERS':
                # Manage MCP server enabled/disabled states
                if not self.mcp_manager:
                    self.cli.print_error("MCP is not enabled")
                    self.cli.wait_for_enter()
                    continue

                try:
                    server_states = self.conversation_manager.get_mcp_server_states()

                    if not server_states:
                        self.cli.print_error("No MCP servers available")
                        self.cli.wait_for_enter()
                        continue
                except Exception as e:
                    logging.error(f"Failed to get MCP server states: {e}")
                    self.cli.print_error(f"Failed to retrieve MCP server states: {e}")
                    self.cli.wait_for_enter()
                    continue

                # Display current state
                self.cli.display_mcp_server_states(server_states)

                # Ask user if they want to toggle a server
                if self.cli.confirm("\nWould you like to enable/disable a server?"):
                    selected_server = self.cli.select_mcp_server(server_states, "toggle")

                    if selected_server:
                        try:
                            # Find current state
                            current_state = next((s for s in server_states if s['server_name'] == selected_server), None)

                            if current_state:
                                # Toggle the state
                                new_state = not current_state['enabled']
                                if self.conversation_manager.set_mcp_server_enabled(selected_server, new_state):
                                    action = "enabled" if new_state else "disabled"
                                    self.cli.print_success(f"Server '{selected_server}' {action}")
                                else:
                                    self.cli.print_error(f"Failed to update server state")

                                # Show updated states
                                self.cli.print_separator("─")
                                updated_states = self.conversation_manager.get_mcp_server_states()
                                self.cli.display_mcp_server_states(updated_states)
                            else:
                                self.cli.print_error("Server not found")
                        except Exception as e:
                            logging.error(f"Failed to toggle MCP server state: {e}")
                            self.cli.print_error(f"Failed to update server state: {e}")
                    else:
                        self.cli.print_info("Cancelled")

                self.cli.wait_for_enter()
                continue

            if not user_message.strip():
                continue

            # Send message and get response
            self.cli.display_message('user', user_message)

            # Show animated status indicator during processing
            with self.cli.status_indicator("Generating response..."):
                assistant_response = self.conversation_manager.send_message(user_message)

            if assistant_response:
                self.cli.display_message('assistant', assistant_response)
            # Note: If None is returned, it could be because:
            # 1. Prompt was blocked by security (already displayed violation message)
            # 2. Model failed (error already logged)
            # In both cases, the user has already been notified, so no additional error needed

    def main(self, args):
        """Main application entry point."""

        ResourceManager().add_resource_path(os.path.join(parent_dir, 'resources'))

        try:
            # Check if --setup flag was provided
            if hasattr(args, 'setup') and args.setup:
                # Run setup wizard and exit
                self.setup_wizard()
                ProcessManager().call_shutdown()
                return

            # Initialise settings
            # Point to the correct config location
            self.settings = Settings()
            self.settings.init_settings_readers()


            # Check if model is locked via configuration
            # Priority 1: Check for mandatory_model (forces model for ALL conversations)
            # Priority 2: Check for bedrock.model_id (legacy configuration)
            self.configured_model_id = self._get_nested_setting('llm_providers.mandatory_model', None)
            self.configured_provider = self._get_nested_setting('llm_providers.mandatory_provider', None)

            if not self.configured_model_id:
                self.configured_model_id = self.settings.get('bedrock.model_id', None)
                # Legacy config doesn't support provider specification

            # Initialise components
            self.initialise_singletons()

            # If model is locked via config, disable model changing in CLI
            if self.configured_model_id:
                logging.info(f"Model locked via configuration: {self.configured_model_id}")
                self.cli.model_changing_enabled = False

            if not self.auth_failed:

                # Check interface type from configuration
                interface_type = self.settings.get('interface.type', 'cli')

                if interface_type == 'web':
                    # Launch web interface
                    self.launch_web_interface()
                    return  # Web server is blocking, so return after it exits

                # Main application loop - menu-driven interface (CLI)
                while True:
                    # Display main menu
                    choice = self.cli.display_main_menu()

                    if choice == 'costs':
                        # Re-gather and display AWS Bedrock costs
                        self.regather_and_display_costs()

                    elif choice == 'new':
                        # Start a new conversation
                        if self.start_new_conversation():
                            # Start chat loop
                            self.chat_loop()
                        else:
                            self.cli.print_warning("Failed to create new conversation")

                    elif choice == 'list':
                        # List and select existing conversation
                        if self.select_existing_conversation():
                            # Start chat loop
                            self.chat_loop()
                        else:
                            self.cli.print_warning("No conversation selected")

                    elif choice == 'autonomous':
                        # Manage autonomous actions
                        self.manage_autonomous_actions()

                    elif choice == 'quit':
                        # User chose to quit
                        break

                    else:
                        # Invalid choice
                        self.cli.print_error("Invalid option. Please select 1-5.")

                # Farewell message
                self.cli.print_farewell(version())

        except KeyboardInterrupt:
            if self.cli:
                self.cli.print_info("\nOperation cancelled by user")
                self.cli.print_farewell(version())
            else:
                print("\nOperation cancelled by user")
        except Exception as e:
            logging.exception("Unexpected error in main application")
            if self.cli:
                self.cli.print_error(f"Unexpected error: {e}")
            else:
                print(f"Unexpected error: {e}", file=sys.stderr)
            raise

        ProcessManager().call_shutdown()

    def exiting(self):
        """Clean up resources on exit."""
        import asyncio
        logging.info('Shutting down application')
        if not self.auth_failed:
            # Stop action scheduler and execution queue
            if self.action_scheduler:
                try:
                    self.action_scheduler.stop()
                    logging.info('Action scheduler stopped')
                except Exception as e:
                    logging.warning(f'Error stopping action scheduler: {e}')

            if self.execution_queue:
                try:
                    self.execution_queue.stop()
                    logging.info('Execution queue stopped')
                except Exception as e:
                    logging.warning(f'Error stopping execution queue: {e}')

            # Disconnect from MCP servers
            if self.mcp_manager:
                try:
                    # Try to disconnect gracefully, but don't fail if it errors
                    # The asyncio context manager cleanup can be tricky with reused loops
                    if hasattr(self.mcp_manager, '_initialization_loop') and self.mcp_manager._initialization_loop:
                        loop = self.mcp_manager._initialization_loop
                        logging.debug('Using stored initialisation loop for MCP disconnection')
                        try:
                            # Try to disconnect, but catch any asyncio-specific errors
                            loop.run_until_complete(self.mcp_manager.disconnect_all())
                            logging.info('Disconnected from MCP servers')
                        except RuntimeError as e:
                            # Ignore asyncio context manager errors during shutdown
                            logging.debug(f'Ignoring asyncio cleanup error during shutdown: {e}')
                        finally:
                            # Close the loop
                            if not loop.is_closed():
                                loop.close()
                            logging.debug('Event loop closed')
                    else:
                        logging.debug('No stored event loop, skipping MCP disconnection')
                except Exception as e:
                    logging.warning(f'Error during MCP cleanup (non-critical): {e}')

        if self.database:
            self.database.close()
            logging.info('Database connection closed')



def main():
    """Entry point for the console script."""
    AWSBedrockCLI().run()

if __name__ == '__main__':
    main()

