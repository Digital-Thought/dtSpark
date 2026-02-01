"""
FastAPI server for the web interface.

Provides HTTP endpoints and SSE streaming for the Spark web UI.

"""

import os
import sys
import socket
import logging
import time
import webbrowser
import signal
import asyncio
from typing import Optional
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import AuthManager
from .session import SessionManager
from .ssl_utils import setup_ssl_certificates

# Import application metadata functions
from dtSpark.core.application import version, full_name, agent_name, description


# Logger for web server
logger = logging.getLogger(__name__)


class WebServer:
    """
    FastAPI-based web server for Spark.

    Provides web interface as alternative to CLI, with authentication,
    session management, and real-time streaming.
    """

    def __init__(
        self,
        app_instance,  # AWSBedrockCLI instance
        host: str = "127.0.0.1",
        port: int = 0,
        session_timeout_minutes: int = 0,
        dark_theme: bool = True,
        ssl_enabled: bool = False,
        ssl_cert_file: Optional[str] = None,
        ssl_key_file: Optional[str] = None,
        ssl_auto_generate: bool = True,
        auto_open_browser: bool = False,
    ):
        """
        Initialise the web server.

        Args:
            app_instance: Instance of AWSBedrockCLI
            host: Host to bind to (default: 127.0.0.1 for localhost only)
            port: Port to bind to (0 for random available port)
            session_timeout_minutes: Session timeout in minutes
            dark_theme: Whether to use dark theme
            ssl_enabled: Whether to enable HTTPS with SSL/TLS
            ssl_cert_file: Path to SSL certificate file (required if ssl_enabled)
            ssl_key_file: Path to SSL private key file (required if ssl_enabled)
            ssl_auto_generate: Whether to auto-generate self-signed certificate if files not found
            auto_open_browser: Whether to automatically open browser with authentication URL
        """
        self.app_instance = app_instance
        self.host = host
        self.port = port
        self.session_timeout_minutes = session_timeout_minutes
        self.dark_theme = dark_theme
        self.ssl_enabled = ssl_enabled
        self.auto_open_browser = auto_open_browser

        # SSL certificate paths
        self.ssl_cert_file = None
        self.ssl_key_file = None

        # Setup SSL certificates if enabled
        if self.ssl_enabled:
            logger.info("SSL enabled - setting up certificates")
            success, cert_path, key_path = setup_ssl_certificates(
                cert_file=ssl_cert_file,
                key_file=ssl_key_file,
                auto_generate=ssl_auto_generate,
                hostname=host if host != "0.0.0.0" else "localhost",
            )
            if success:
                self.ssl_cert_file = cert_path
                self.ssl_key_file = key_path
                logger.info(f"SSL certificates ready: {cert_path}, {key_path}")
            else:
                logger.error("Failed to setup SSL certificates - SSL will be disabled")
                self.ssl_enabled = False

        # Initialise auth and session managers
        self.auth_manager = AuthManager()
        self.session_manager = SessionManager(timeout_minutes=session_timeout_minutes)

        # Initialise web interface for tool permission prompts
        from .web_interface import WebInterface
        self.web_interface = WebInterface()
        # Set web interface on conversation manager so it uses web prompts instead of CLI
        if hasattr(app_instance, 'conversation_manager') and app_instance.conversation_manager:
            app_instance.conversation_manager.web_interface = self.web_interface
            logger.info("Web interface set on conversation manager for tool permission prompts")

        # Generate one-time authentication code
        self.auth_code = self.auth_manager.generate_code()

        # Get cost tracking configuration from app instance settings
        from dtPyAppFramework.settings import Settings
        settings = Settings()
        cost_tracking_enabled = settings.get('llm_providers.aws_bedrock.cost_tracking.enabled', None)
        if cost_tracking_enabled is None:
            cost_tracking_enabled = settings.get('aws.cost_tracking.enabled', False)

        # Create FastAPI app
        self.app = create_app(
            auth_manager=self.auth_manager,
            session_manager=self.session_manager,
            app_instance=self.app_instance,
            dark_theme=self.dark_theme,
            cost_tracking_enabled=cost_tracking_enabled,
            ssl_enabled=self.ssl_enabled,
            session_timeout_minutes=self.session_timeout_minutes,
        )

        # Determine actual port if using random port
        if self.port == 0:
            self.port = self._find_free_port()

    def get_access_info(self) -> dict:
        """
        Get information needed to access the web interface.

        Returns:
            Dictionary with URL and authentication code
        """
        protocol = "https" if self.ssl_enabled else "http"
        return {
            'url': f"{protocol}://{self.host}:{self.port}",
            'code': self.auth_code,
            'host': self.host,
            'port': self.port,
            'ssl_enabled': self.ssl_enabled,
        }

    def run(self):
        """
        Start the web server.

        Blocks until server is shut down.
        """
        protocol = "https" if self.ssl_enabled else "http"
        logger.info(f"Starting web server on {protocol}://{self.host}:{self.port}")
        logger.info(f"Authentication code: {self.auth_code}")
        logger.info(f"SSL enabled: {self.ssl_enabled}")

        # Auto-open browser if enabled
        if self.auto_open_browser:
            access_info = self.get_access_info()
            auth_url = f"{access_info['url']}/login?code={self.auth_code}"
            logger.info(f"Attempting to open browser: {auth_url}")
            try:
                webbrowser.open(auth_url)
                logger.info("Browser opened successfully")
            except Exception as e:
                logger.warning(f"Failed to open browser: {e}")
                logger.info("Please open the URL manually in your browser")

        # Prepare uvicorn configuration
        uvicorn_config = {
            "app": self.app,
            "host": self.host,
            "port": self.port,
            "log_level": "info",
        }

        # Add SSL configuration if enabled
        if self.ssl_enabled and self.ssl_cert_file and self.ssl_key_file:
            uvicorn_config["ssl_keyfile"] = self.ssl_key_file
            uvicorn_config["ssl_certfile"] = self.ssl_cert_file
            logger.info(f"SSL configured with cert: {self.ssl_cert_file}")

        uvicorn.run(**uvicorn_config)

    @staticmethod
    def _find_free_port() -> int:
        """
        Find a free port on localhost.

        Returns:
            Available port number
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port


def create_app(
    auth_manager: AuthManager,
    session_manager: SessionManager,
    app_instance,  # AWSBedrockCLI instance
    dark_theme: bool = True,
    cost_tracking_enabled: bool = False,
    ssl_enabled: bool = False,
    session_timeout_minutes: int = 0,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        auth_manager: Authentication manager instance
        session_manager: Session manager instance
        app_instance: AWSBedrockCLI instance
        dark_theme: Whether to use dark theme
        cost_tracking_enabled: Whether cost tracking is enabled
        ssl_enabled: Whether SSL/HTTPS is enabled (affects cookie security)
        session_timeout_minutes: Session timeout in minutes (0 = no timeout)

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=f"{full_name()} Web Interface",
        description="Web interface for AWS Bedrock CLI with MCP integration",
        version=version(),
    )

    # Custom exception handler to suppress Windows asyncio connection reset errors
    def _suppress_connection_reset_errors(loop, context):
        """Suppress ConnectionResetError noise on Windows."""
        exception = context.get('exception')
        if isinstance(exception, ConnectionResetError):
            # Silently ignore connection reset errors (common on Windows when browser closes)
            return
        # For other exceptions, use the default handler
        loop.default_exception_handler(context)

    @app.on_event("startup")
    async def setup_exception_handler():
        """Install custom exception handler on startup."""
        if sys.platform == 'win32':
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(_suppress_connection_reset_errors)

    # Set to hold references to background tasks (prevents garbage collection)
    _background_tasks = set()

    # Browser heartbeat state
    app.state.last_heartbeat = 0.0

    @app.post("/api/heartbeat")
    async def heartbeat():
        """Receive browser heartbeat ping."""
        app.state.last_heartbeat = time.time()
        return JSONResponse({"status": "ok"})

    @app.on_event("startup")
    async def start_heartbeat_monitor():
        """Start background task to monitor browser heartbeat."""
        if not heartbeat_enabled:
            return

        async def _monitor_heartbeat():
            # Initial grace period - wait for browser to connect and send first heartbeat
            grace_period = heartbeat_timeout * 2
            logger.info(
                f"Browser heartbeat monitor started (interval={heartbeat_interval}s, "
                f"timeout={heartbeat_timeout}s, grace={grace_period}s)"
            )
            await asyncio.sleep(grace_period)

            while True:
                await asyncio.sleep(heartbeat_interval)
                last = app.state.last_heartbeat
                if last > 0 and (time.time() - last) > heartbeat_timeout:
                    logger.info(
                        f"No browser heartbeat for {heartbeat_timeout}s - "
                        f"shutting down (browser likely closed)"
                    )
                    os.kill(os.getpid(), signal.SIGTERM)
                    return

        task = asyncio.create_task(_monitor_heartbeat())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # Get template and static directories
    web_dir = Path(__file__).parent
    templates_dir = web_dir / "templates"
    static_dir = web_dir / "static"

    # Setup templates
    templates = Jinja2Templates(directory=str(templates_dir))

    # Determine feature flags from app instance
    actions_enabled = getattr(app_instance, 'actions_enabled', False)
    new_conversations_allowed = getattr(app_instance, 'new_conversations_allowed', True)

    # Read heartbeat configuration
    from dtPyAppFramework.settings import Settings as _Settings
    _hb_settings = _Settings()
    heartbeat_enabled = _hb_settings.get('interface.web.browser_heartbeat.enabled', True)
    heartbeat_interval = _hb_settings.get('interface.web.browser_heartbeat.interval_seconds', 15)
    heartbeat_timeout = _hb_settings.get('interface.web.browser_heartbeat.timeout_seconds', 60)

    # Add global template variables for app name and version
    templates.env.globals['app_name'] = full_name()
    templates.env.globals['app_version'] = version()
    templates.env.globals['app_description'] = description()
    templates.env.globals['agent_name'] = agent_name()
    templates.env.globals['actions_enabled'] = actions_enabled
    templates.env.globals['new_conversations_allowed'] = new_conversations_allowed
    templates.env.globals['heartbeat_enabled'] = heartbeat_enabled
    templates.env.globals['heartbeat_interval_ms'] = heartbeat_interval * 1000

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Store references for use in endpoints
    app.state.auth_manager = auth_manager
    app.state.session_manager = session_manager
    app.state.app_instance = app_instance
    app.state.templates = templates
    app.state.dark_theme = dark_theme
    app.state.cost_tracking_enabled = cost_tracking_enabled
    app.state.new_conversations_allowed = new_conversations_allowed

    # Session dependency
    async def get_session(session_id: Optional[str] = Cookie(default=None)) -> str:
        """
        Dependency to validate session.

        Raises:
            HTTPException: If session is invalid or expired
        """
        if session_id is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        if not session_manager.validate_session(session_id):
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        return session_id

    # Store session dependency for use in routers
    app.state.get_session = get_session

    # Custom exception handler for HTTPException - redirect to login for 401 on HTML pages
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """
        Handle HTTP exceptions.

        For 401 errors on HTML page requests, redirect to login page.
        For API requests or other errors, return appropriate response.
        """
        if exc.status_code == 401:
            # Check if this is an API request or a page request
            accept_header = request.headers.get("accept", "")
            is_api_request = (
                request.url.path.startswith("/api/") or
                "application/json" in accept_header or
                request.headers.get("x-requested-with") == "XMLHttpRequest"
            )

            if not is_api_request:
                # Redirect to login for page requests
                logger.info(f"Session invalid for page request {request.url.path}, redirecting to login")
                return RedirectResponse(url="/login", status_code=303)

        # Return JSON error for API requests and other errors
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail if hasattr(exc, 'detail') else str(exc)}
        )

    # Basic routes
    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        """Root endpoint - redirects to login page."""
        return RedirectResponse(url="/login")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        """Display login page."""
        # Check if code is provided as query parameter (for auto-open browser)
        code = request.query_params.get("code", "")

        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "code": code,  # Pass code to template for auto-fill
            }
        )

    @app.post("/login")
    async def login(request: Request):
        """
        Handle login form submission.

        Validates one-time code and creates session.
        """
        form = await request.form()
        code = form.get("code", "").strip().upper()

        # Validate code
        if not auth_manager.validate_code(code):
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "dark_theme": dark_theme,
                    "error": "Invalid or expired authentication code",
                }
            )

        # Create session
        session_id = session_manager.create_session()

        # Redirect to main menu with session cookie
        response = RedirectResponse(url="/menu", status_code=303)

        # Calculate cookie max_age:
        # - If session_timeout_minutes > 0, use that value
        # - If session_timeout_minutes == 0 (no timeout), use 1 year (persistent session)
        if session_timeout_minutes > 0:
            cookie_max_age = session_timeout_minutes * 60  # Convert to seconds
        else:
            cookie_max_age = 365 * 24 * 60 * 60  # 1 year in seconds

        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=ssl_enabled,  # Use secure cookies when SSL is enabled
            samesite="strict",
            max_age=cookie_max_age,  # Persistent cookie instead of session cookie
        )

        return response

    @app.get("/logout")
    async def logout(request: Request, session_id: str = Depends(get_session)):
        """Handle logout - invalidate session and show goodbye page."""
        session_manager.invalidate_session()
        response = templates.TemplateResponse(
            "goodbye.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "shutdown": False,
            }
        )
        response.delete_cookie(key="session_id")
        return response

    @app.get("/quit")
    async def quit_app(request: Request, session_id: str = Depends(get_session)):
        """Handle quit - invalidate session, show goodbye page, and trigger shutdown."""
        session_manager.invalidate_session()
        response = templates.TemplateResponse(
            "goodbye.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "shutdown": True,
            }
        )
        response.delete_cookie(key="session_id")
        return response

    @app.post("/api/shutdown")
    async def shutdown():
        """Shutdown the web server."""
        logger.info("Shutdown request received via API")
        # Send shutdown signal to the process
        # Use a background task to allow the response to be sent first
        async def shutdown_server():
            await asyncio.sleep(0.5)  # Give time for response to be sent
            logger.info("Shutting down web server...")
            os.kill(os.getpid(), signal.SIGTERM)

        task = asyncio.create_task(shutdown_server())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return JSONResponse({"status": "shutdown initiated"})

    @app.get("/menu", response_class=HTMLResponse)
    async def main_menu(request: Request, session_id: str = Depends(get_session)):
        """Display main menu page."""
        return templates.TemplateResponse(
            "main_menu.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "cost_tracking_enabled": cost_tracking_enabled,
            }
        )

    # Import and register routers
    from .endpoints import (
        main_menu_router,
        conversations_router,
        chat_router,
        streaming_router,
    )
    app.include_router(main_menu_router, prefix="/api", tags=["Main Menu"])
    app.include_router(conversations_router, prefix="/api", tags=["Conversations"])
    app.include_router(chat_router, prefix="/api", tags=["Chat"])
    app.include_router(streaming_router, prefix="/api", tags=["Streaming"])

    if actions_enabled:
        from .endpoints.autonomous_actions import router as autonomous_actions_router
        app.include_router(autonomous_actions_router, prefix="/api", tags=["Autonomous Actions"])

    # Add template routes for conversations and chat
    @app.get("/conversations", response_class=HTMLResponse)
    async def conversations_page(request: Request, session_id: str = Depends(get_session)):
        """Display conversations list page."""
        return templates.TemplateResponse(
            "conversations.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "session_active": True,
            }
        )

    @app.get("/conversations/new", response_class=HTMLResponse)
    async def new_conversation_page(request: Request, session_id: str = Depends(get_session)):
        """Display new conversation creation page."""
        if not new_conversations_allowed:
            return RedirectResponse(url="/conversations", status_code=303)
        return templates.TemplateResponse(
            "new_conversation.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "session_active": True,
            }
        )

    @app.get("/chat/{conversation_id}", response_class=HTMLResponse)
    async def chat_page(
        conversation_id: int,
        request: Request,
        session_id: str = Depends(get_session)
    ):
        """Display chat page for a conversation."""
        # Get conversation name
        conv = app_instance.database.get_conversation(conversation_id)
        if not conv:
            return RedirectResponse(url="/conversations", status_code=303)

        return templates.TemplateResponse(
            "chat.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "session_active": True,
                "conversation_id": conversation_id,
                "conversation_name": conv['name'],
            }
        )

    @app.get("/actions", response_class=HTMLResponse)
    async def actions_page(request: Request, session_id: str = Depends(get_session)):
        """Display autonomous actions management page."""
        if not actions_enabled:
            return RedirectResponse(url="/menu", status_code=303)
        return templates.TemplateResponse(
            "actions.html",
            {
                "request": request,
                "dark_theme": dark_theme,
                "session_active": True,
            }
        )

    return app


def run_server(
    app_instance,  # AWSBedrockCLI instance
    host: str = "127.0.0.1",
    port: int = 0,
    session_timeout_minutes: int = 0,
    dark_theme: bool = True,
    ssl_enabled: bool = False,
    ssl_cert_file: Optional[str] = None,
    ssl_key_file: Optional[str] = None,
    ssl_auto_generate: bool = True,
    auto_open_browser: bool = False,
) -> dict:
    """
    Convenience function to create and run the web server.

    Args:
        app_instance: Instance of AWSBedrockCLI
        host: Host to bind to
        port: Port to bind to (0 for random available port)
        session_timeout_minutes: Session timeout in minutes
        dark_theme: Whether to use dark theme
        ssl_enabled: Whether to enable HTTPS with SSL/TLS
        ssl_cert_file: Path to SSL certificate file
        ssl_key_file: Path to SSL private key file
        ssl_auto_generate: Whether to auto-generate self-signed certificate if files not found
        auto_open_browser: Whether to automatically open browser with authentication URL

    Returns:
        Dictionary with access information (url, code)
    """
    server = WebServer(
        app_instance=app_instance,
        host=host,
        port=port,
        session_timeout_minutes=session_timeout_minutes,
        dark_theme=dark_theme,
        ssl_enabled=ssl_enabled,
        ssl_cert_file=ssl_cert_file,
        ssl_key_file=ssl_key_file,
        ssl_auto_generate=ssl_auto_generate,
        auto_open_browser=auto_open_browser,
    )

    access_info = server.get_access_info()

    # Start server (blocking)
    server.run()

    return access_info
