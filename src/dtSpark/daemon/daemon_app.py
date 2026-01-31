"""
Daemon application for autonomous action execution.

Extends AbstractApp from dtPyAppFramework to provide a long-running
background process for executing scheduled autonomous actions.


"""

import os
import sys
import logging
import socket
import uuid
from typing import Optional, Dict, Any

from dtPyAppFramework.application import AbstractApp
from dtPyAppFramework.process import ProcessManager
from dtPyAppFramework.settings import Settings

from .pid_file import PIDFile
from .action_monitor import ActionChangeMonitor
from .execution_coordinator import ExecutionCoordinator

# Import version info
from dtSpark.core.application import version, full_name, agent_type

logger = logging.getLogger(__name__)


class DaemonApplication(AbstractApp):
    """
    Daemon process for executing autonomous actions.

    Runs independently of CLI/Web interface, polls database for changes,
    and executes scheduled actions.
    """

    def __init__(self):
        """Initialise the daemon application."""
        # Use same short_name as main app to share secret store (user_guid, etc.)
        super().__init__(
            short_name=agent_type(),
            full_name=f"{full_name()} (Daemon Mode)",
            version=version(),
            description="Background daemon for autonomous action execution",
            console_app=True
        )

        # Core components
        self.settings: Optional[Settings] = None
        self.database = None
        self.llm_manager = None
        self.mcp_manager = None

        # Scheduler components
        self.action_scheduler = None
        self.execution_queue = None
        self.action_executor = None

        # Daemon-specific components
        self.action_monitor = None
        self.execution_coordinator = None
        self.pid_file = None

        # Identifiers
        self.daemon_id = None
        self.user_guid = None
        self.hostname = socket.gethostname()

    def define_args(self, arg_parser):
        """Define daemon-specific command-line arguments."""
        arg_parser.add_argument(
            '--poll-interval',
            type=int,
            default=30,
            help='Seconds between database polls for changes (default: 30)'
        )
        arg_parser.add_argument(
            '--daemon-id',
            type=str,
            default=None,
            help='Unique daemon identifier (default: auto-generated)'
        )

    def main(self, args):
        """
        Main daemon loop.

        Implements the long-running application pattern.
        """
        import threading
        self._shutdown_event = threading.Event()

        print("=" * 60)
        print(f"Starting {self.full_name} v{self.version}")
        print("Running in DAEMON MODE")
        print("=" * 60)
        logger.info("=" * 60)
        logger.info(f"Starting {self.full_name} v{self.version}")
        logger.info("Running in DAEMON MODE - background autonomous action execution")
        logger.info("=" * 60)

        # Load settings
        print("Loading settings...")
        self.settings = Settings()
        print("Settings loaded successfully")

        # Get daemon configuration
        poll_interval = args.poll_interval if hasattr(args, 'poll_interval') else 30
        poll_interval = self.settings.get('daemon.poll_interval', poll_interval)

        # Generate or use provided daemon ID
        self.daemon_id = args.daemon_id if hasattr(args, 'daemon_id') and args.daemon_id else str(uuid.uuid4())[:8]

        # Get or create user GUID from secret manager
        # Since daemon uses same short_name as main app, they share the secret store
        self.user_guid = self.settings.secret_manager.get_secret('user_guid', None, 'User_Local_Store')
        if self.user_guid is None:
            # Generate new GUID for this user (only if main app hasn't run yet)
            self.user_guid = str(uuid.uuid4())
            self.settings.secret_manager.set_secret('user_guid', self.user_guid, 'User_Local_Store')
            print(f"Generated new user GUID: {self.user_guid}")
            logger.info(f"Generated new user GUID: {self.user_guid}")
        else:
            print(f"Using existing user GUID: {self.user_guid}")
            logger.info(f"Using existing user GUID: {self.user_guid}")
        print(f"Daemon ID: {self.daemon_id}")
        logger.info(f"Daemon ID: {self.daemon_id}")

        # Set up PID file
        pid_file_path = self.settings.get('daemon.pid_file', './daemon.pid')
        self.pid_file = PIDFile(pid_file_path)

        if not self.pid_file.acquire():
            print("Failed to acquire PID file - another daemon may be running")
            logger.error("Failed to acquire PID file - another daemon may be running")
            return 1

        try:
            # Initialise all components
            print("Initialising components...")
            self._initialise_components()
            print("Components initialised")

            # Register daemon in database
            self._register_daemon()

            # Set up action monitor with callbacks
            lock_timeout = self.settings.get('daemon.lock_timeout', 300)
            self.execution_coordinator = ExecutionCoordinator(
                database=self.database,
                process_id=self.daemon_id,
                user_guid=self.user_guid,
                lock_timeout_seconds=lock_timeout
            )

            self.action_monitor = ActionChangeMonitor(
                database=self.database,
                user_guid=self.user_guid,
                poll_interval=poll_interval,
                on_action_added=self._on_action_added,
                on_action_modified=self._on_action_modified,
                on_action_deleted=self._on_action_deleted,
            )

            # Start all components
            self.execution_queue.start()
            self.action_scheduler.start()
            self.action_monitor.start()

            # Load and schedule existing actions
            self._load_existing_actions()

            # Start heartbeat thread
            self._start_heartbeat()

            print("=" * 60)
            print("Daemon started successfully")
            print(f"  PID: {os.getpid()}")
            print(f"  Daemon ID: {self.daemon_id}")
            print(f"  Poll interval: {poll_interval}s")
            print("Waiting for shutdown signal (SIGTERM/SIGINT)...")
            print("=" * 60)
            logger.info("=" * 60)
            logger.info("Daemon started successfully")
            logger.info(f"  PID: {os.getpid()}")
            logger.info(f"  Daemon ID: {self.daemon_id}")
            logger.info(f"  Poll interval: {poll_interval}s")
            logger.info("Waiting for shutdown signal (SIGTERM/SIGINT)...")
            logger.info("=" * 60)

            # Set up signal handlers and wait for shutdown
            self._setup_signal_handlers()
            self._wait_for_shutdown(pid_file_path)

            print("Shutdown signal received")
            logger.info("Shutdown signal received")

        except Exception as e:
            print(f"Daemon error: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"Daemon error: {e}", exc_info=True)
            return 1

        finally:
            # Graceful shutdown
            self._shutdown()

        return 0

    def _setup_signal_handlers(self):
        """Register OS signal handlers for graceful shutdown."""
        import signal

        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}, initiating shutdown...")
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if sys.platform == 'win32':
            signal.signal(signal.SIGBREAK, signal_handler)

    def _wait_for_shutdown(self, pid_file_path: str):
        """
        Block until a shutdown signal is received.

        Polls for stop signal file (Windows cross-console shutdown) and
        handles keyboard interrupts.

        Args:
            pid_file_path: Path to the PID file (used to derive stop signal file path)
        """
        stop_signal_file = pid_file_path + '.stop'

        while not self._shutdown_event.is_set():
            try:
                if os.path.exists(stop_signal_file):
                    print("\nStop signal file detected, initiating shutdown...")
                    logger.info("Stop signal file detected, initiating shutdown...")
                    try:
                        os.remove(stop_signal_file)
                    except Exception:
                        pass
                    self._shutdown_event.set()
                    break

                self._shutdown_event.wait(timeout=1.0)
            except KeyboardInterrupt:
                print("\nKeyboard interrupt received, initiating shutdown...")
                logger.info("Keyboard interrupt received, initiating shutdown...")
                self._shutdown_event.set()
                break

    def _initialise_components(self):
        """Initialise database, LLM manager, and scheduler components."""
        print("  - Initialising daemon components...")
        logger.info("Initialising daemon components...")

        # Initialise database
        print("  - Initialising database...")
        from dtSpark.database import ConversationDatabase
        db_type, db_credentials = self._load_database_configuration()
        self.database = ConversationDatabase(
            db_type=db_type,
            credentials=db_credentials,
            user_guid=self.user_guid
        )
        print("  - Database initialised")
        logger.info("Database initialised")

        # Initialise LLM manager
        print("  - Initialising LLM manager...")
        from dtSpark.llm import LLMManager
        self.llm_manager = LLMManager()
        self._configure_llm_providers()
        print("  - LLM manager initialised")
        logger.info("LLM manager initialised")

        # Optionally initialise MCP manager
        mcp_enabled = self.settings.get('mcp_config.enabled', False)
        print(f"  - MCP enabled: {mcp_enabled}")
        if mcp_enabled:
            print("  - Initialising MCP manager...")
            self._initialise_mcp()
            print("  - MCP manager initialised")

        # Initialise scheduler components
        print("  - Initialising scheduler components...")
        self._initialise_scheduler()
        print("  - Scheduler components initialised")

        print("  - All daemon components initialised")
        logger.info("All daemon components initialised")

    def _configure_llm_providers(self):
        """Configure LLM providers based on settings."""
        self._configure_aws_bedrock()
        self._configure_anthropic_direct()
        self._configure_ollama()

        # Log summary of configured providers
        providers = list(self.llm_manager.providers.keys())
        if providers:
            print(f"  - LLM providers configured: {', '.join(providers)}")
            logger.info(f"LLM providers configured: {providers}")
        else:
            print("  - Warning: No LLM providers configured!")
            logger.warning("No LLM providers configured - actions will fail to execute")

    def _configure_aws_bedrock(self):
        """Configure AWS Bedrock LLM provider if enabled."""
        aws_enabled = self._get_nested_setting('llm_providers.aws_bedrock.enabled', True)
        if not aws_enabled:
            return

        try:
            from dtSpark.llm import BedrockService
            from dtSpark.aws.authenticator import AWSAuthenticator

            aws_region = self._get_nested_setting('llm_providers.aws_bedrock.region', 'us-east-1')
            aws_profile = self._get_nested_setting('llm_providers.aws_bedrock.sso_profile', 'default')
            request_timeout = self.settings.get('bedrock.request_timeout', 300)

            aws_access_key_id = self._get_nested_setting('llm_providers.aws_bedrock.access_key_id', None)
            aws_secret_access_key = self._get_nested_setting('llm_providers.aws_bedrock.secret_access_key', None)

            authenticator = AWSAuthenticator(
                region=aws_region,
                sso_profile=aws_profile,
                access_key_id=aws_access_key_id,
                secret_access_key=aws_secret_access_key
            )

            if authenticator.authenticate():
                bedrock_service = BedrockService(
                    session=authenticator.session,
                    region=aws_region,
                    request_timeout=request_timeout
                )
                self.llm_manager.register_provider(bedrock_service)
                logger.info("AWS Bedrock provider configured")

        except Exception as e:
            logger.warning(f"Failed to configure AWS Bedrock: {e}")

    def _configure_anthropic_direct(self):
        """Configure Anthropic Direct LLM provider if enabled."""
        anthropic_enabled = self._get_nested_setting('llm_providers.anthropic.enabled', False)
        logger.debug(f"Anthropic Direct enabled: {anthropic_enabled}")
        if not anthropic_enabled:
            return

        try:
            from dtSpark.llm import AnthropicService

            api_key = self._get_nested_setting('llm_providers.anthropic.api_key', None)
            max_tokens = self.settings.get('bedrock.max_tokens', 8192)

            if api_key:
                key_prefix = api_key[:10] if len(api_key) > 10 else 'SHORT'
                logger.info("Anthropic API key found (starts with: %s...)", key_prefix)
            else:
                logger.warning("Anthropic API key not found in settings")

            anthropic_service = AnthropicService(
                api_key=api_key,
                default_max_tokens=max_tokens
            )
            self.llm_manager.register_provider(anthropic_service)
            print("  - Anthropic Direct provider configured")
            logger.info("Anthropic Direct provider configured")

        except Exception as e:
            print(f"  - Warning: Failed to configure Anthropic Direct: {e}")
            logger.warning(f"Failed to configure Anthropic Direct: {e}")

    def _configure_ollama(self):
        """Configure Ollama LLM provider if enabled."""
        ollama_enabled = self._get_nested_setting('llm_providers.ollama.enabled', False)
        if not ollama_enabled:
            return

        try:
            from dtSpark.llm import OllamaService

            base_url = self._get_nested_setting('llm_providers.ollama.base_url', 'http://localhost:11434')
            verify_ssl = self._get_nested_setting('llm_providers.ollama.verify_ssl', True)

            ollama_service = OllamaService(base_url=base_url, verify_ssl=verify_ssl)
            self.llm_manager.register_provider(ollama_service)
            logger.info("Ollama provider configured")

        except Exception as e:
            logger.warning(f"Failed to configure Ollama: {e}")

    def _initialise_mcp(self):
        """Initialise MCP manager if enabled."""
        import asyncio

        try:
            from dtSpark.mcp_integration import MCPManager

            servers_config = self.settings.get('mcp_config.servers', [])
            if not servers_config:
                print("    No MCP servers configured")
                logger.info("No MCP servers configured")
                return

            # Create MCP manager from config
            config_dict = {
                'mcp_config': {
                    'servers': servers_config
                }
            }
            self.mcp_manager = MCPManager.from_config(config_dict)

            num_servers = len(self.mcp_manager.clients)
            print(f"    Found {num_servers} MCP server(s) in configuration")
            logger.info(f"Found {num_servers} MCP server(s) in configuration")

            # Connect to all MCP servers
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                results = loop.run_until_complete(self.mcp_manager.connect_all())

                # Count successful connections
                connected_count = sum(1 for success in results.values() if success)
                failed_count = num_servers - connected_count

                # Log each server's status
                for server_name, success in results.items():
                    status = "connected" if success else "FAILED"
                    print(f"    - {server_name}: {status}")
                    logger.info(f"MCP server '{server_name}': {status}")

                print(f"    MCP servers: {connected_count} connected, {failed_count} failed")
                logger.info(f"MCP servers: {connected_count} connected, {failed_count} failed")

                # Fetch and cache tools if any servers connected
                if connected_count > 0:
                    try:
                        tools = loop.run_until_complete(
                            asyncio.wait_for(
                                self.mcp_manager.list_all_tools(),
                                timeout=15.0
                            )
                        )
                        print(f"    MCP tools available: {len(tools)}")
                        logger.info(f"MCP tools available: {len(tools)}")
                    except asyncio.TimeoutError:
                        print("    Warning: Timeout fetching MCP tools")
                        logger.warning("Timeout fetching MCP tools")
                    except Exception as e:
                        print(f"    Warning: Failed to fetch MCP tools: {e}")
                        logger.warning(f"Failed to fetch MCP tools: {e}")

            finally:
                # Store the loop for later use
                self.mcp_manager._initialization_loop = loop

        except Exception as e:
            print(f"    Failed to initialise MCP manager: {e}")
            logger.warning(f"Failed to initialise MCP manager: {e}")
            self.mcp_manager = None

    def _initialise_scheduler(self):
        """Initialise scheduler components."""
        from dtSpark.scheduler import (
            ActionSchedulerManager,
            ActionExecutionQueue,
            ActionExecutor
        )

        # Get database path
        db_path = self.database.db_path or ':memory:'

        # Build config for executor
        config = {}
        if self.settings:
            config = {
                'conversation': {
                    'max_tool_result_tokens': self.settings.get('conversation.max_tool_result_tokens', 10000),
                    'max_tool_iterations': self.settings.get('conversation.max_tool_iterations', 25),
                },
                'embedded_tools': self.settings.get('embedded_tools', {}),
            }

        # Create get_tools function for MCP tools
        get_tools_func = None
        if self.mcp_manager:
            def get_tools_func():
                import asyncio
                loop = getattr(self.mcp_manager, '_initialization_loop', None)
                if loop and not loop.is_closed():
                    return loop.run_until_complete(self.mcp_manager.list_all_tools())
                return []

        # Create executor
        self.action_executor = ActionExecutor(
            database=self.database,
            llm_manager=self.llm_manager,
            mcp_manager=self.mcp_manager,
            get_tools_func=get_tools_func,
            config=config
        )

        # Create execution queue
        self.execution_queue = ActionExecutionQueue(
            executor_func=self._execute_with_coordination
        )

        # Create scheduler manager
        self.action_scheduler = ActionSchedulerManager(
            db_path=db_path,
            execution_callback=lambda action_id, user_guid: self.execution_queue.enqueue(
                action_id, user_guid, is_manual=False
            )
        )

        self.action_scheduler.initialise()
        logger.info("Scheduler components initialised")

    def _execute_with_coordination(self, action_id: int, user_guid: str, is_manual: bool = False):
        """
        Execute an action with coordination to prevent conflicts.

        Args:
            action_id: Action ID to execute
            user_guid: User GUID
            is_manual: Whether this is a manual execution
        """
        # Try to acquire lock
        if not self.execution_coordinator.try_acquire_lock(action_id):
            lock_holder = self.execution_coordinator.get_lock_holder(action_id)
            logger.info(f"Skipping action {action_id} - locked by {lock_holder}")
            return None

        try:
            return self.action_executor.execute(action_id, user_guid, is_manual)
        finally:
            self.execution_coordinator.release_lock(action_id)

    def _load_existing_actions(self):
        """Load and schedule existing actions from database."""
        try:
            actions = self.database.get_all_actions(include_disabled=False)
            self.action_scheduler.reload_all_actions(actions)
            logger.info(f"Loaded {len(actions)} existing actions")
        except Exception as e:
            logger.error(f"Failed to load existing actions: {e}")

    def _register_daemon(self):
        """Register daemon in database."""
        try:
            from dtSpark.database.autonomous_actions import register_daemon
            register_daemon(
                conn=self.database.conn,
                daemon_id=self.daemon_id,
                hostname=self.hostname,
                pid=os.getpid(),
                user_guid=self.user_guid
            )
        except Exception as e:
            logger.warning(f"Failed to register daemon: {e}")

    def _unregister_daemon(self):
        """Unregister daemon from database."""
        try:
            from dtSpark.database.autonomous_actions import unregister_daemon
            unregister_daemon(
                conn=self.database.conn,
                daemon_id=self.daemon_id
            )
        except Exception as e:
            logger.warning(f"Failed to unregister daemon: {e}")

    def _start_heartbeat(self):
        """Start heartbeat thread to update daemon registry."""
        import threading

        heartbeat_interval = self.settings.get('daemon.heartbeat_interval', 60)

        def heartbeat_loop():
            while True:
                try:
                    from dtSpark.database.autonomous_actions import update_daemon_heartbeat
                    update_daemon_heartbeat(
                        conn=self.database.conn,
                        daemon_id=self.daemon_id
                    )
                except Exception as e:
                    logger.warning(f"Heartbeat failed: {e}")

                # Wait for next heartbeat or until daemon stops
                import time
                time.sleep(heartbeat_interval)

        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            name="DaemonHeartbeat",
            daemon=True  # Thread will stop when main process exits
        )
        heartbeat_thread.start()
        logger.info(f"Heartbeat thread started (interval: {heartbeat_interval}s)")

    def _on_action_added(self, action: Dict[str, Any]):
        """Handle new action detected by monitor."""
        logger.info(f"Scheduling new action: {action['name']} (ID: {action['id']})")
        try:
            self.action_scheduler.schedule_action(action)
        except Exception as e:
            logger.error(f"Failed to schedule action {action['id']}: {e}")

    def _on_action_modified(self, action: Dict[str, Any]):
        """Handle modified action detected by monitor."""
        logger.info(f"Rescheduling modified action: {action['name']} (ID: {action['id']})")
        try:
            # Unschedule and reschedule
            self.action_scheduler.unschedule_action(action['id'])
            if action.get('is_enabled', True):
                self.action_scheduler.schedule_action(action)
        except Exception as e:
            logger.error(f"Failed to reschedule action {action['id']}: {e}")

    def _on_action_deleted(self, action_id: int):
        """Handle deleted action detected by monitor."""
        logger.info(f"Unscheduling deleted action: {action_id}")
        try:
            self.action_scheduler.unschedule_action(action_id)
        except Exception as e:
            logger.error(f"Failed to unschedule action {action_id}: {e}")

    def _shutdown(self):
        """Graceful shutdown of all components."""
        logger.info("Shutting down daemon components...")

        # Stop action monitor
        if self.action_monitor:
            self.action_monitor.stop()

        # Stop scheduler
        if self.action_scheduler:
            self.action_scheduler.stop()

        # Stop execution queue
        if self.execution_queue:
            self.execution_queue.stop()

        # Unregister daemon
        self._unregister_daemon()

        # Close database
        if self.database:
            self.database.close()

        # Release PID file
        if self.pid_file:
            self.pid_file.release()

        logger.info("Daemon shutdown complete")

    def _load_database_configuration(self):
        """
        Load database configuration from settings.

        Returns:
            Tuple of (db_type, credentials)
        """
        from dtSpark.database.backends import DatabaseCredentials

        # Get database type from configuration
        db_type = self.settings.get('database.type', 'sqlite')
        print(f"  - Database type: {db_type}")
        logger.info(f"Database type: {db_type}")

        # Load credentials from configuration
        if db_type.lower() == 'sqlite':
            db_path = self.settings.get('database.sqlite.path', './data/conversations.db')
            # Expand path relative to current working directory (app root)
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(db_path)

            credentials = DatabaseCredentials(path=db_path)
            print(f"  - SQLite database path: {db_path}")
            logger.info(f"SQLite database path: {db_path}")

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

            # For daemon mode, credentials must be fully configured
            if not all([credentials.host, credentials.database, credentials.username, credentials.password]):
                raise RuntimeError(
                    f"Database credentials incomplete for {db_type}. "
                    f"Daemon mode requires fully configured database credentials in config.yaml."
                )

            print(f"  - Database: {db_type} at {credentials.host}:{credentials.port}/{credentials.database}")
            logger.info(f"Database configured: {db_type} at {credentials.host}:{credentials.port}/{credentials.database}")

        return db_type, credentials

    def _get_nested_setting(self, key: str, default=None):
        """
        Get a nested setting value, handling both dot notation and dict navigation.

        Args:
            key: Dot-separated key
            default: Default value if not found

        Returns:
            The setting value, or default if not found
        """
        value = self.settings.get(key, None)
        if value is not None:
            return value

        # Fallback: Navigate the dict manually
        parts = key.split('.')
        if len(parts) > 1:
            # Try getting the root key as a dict
            root_value = self.settings.get(parts[0], None)
            if isinstance(root_value, dict):
                current = root_value
                for part in parts[1:]:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return default
                return current

        return default

    def exiting(self):
        """Called when application is exiting."""
        logger.info("Daemon exiting...")
