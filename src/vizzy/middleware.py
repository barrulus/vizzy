"""FastAPI middleware for performance monitoring and optimization."""

import time
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("vizzy.performance")


class TimingMiddleware(BaseHTTPMiddleware):
    """Middleware that adds timing information to responses.

    Features:
    - Adds X-Response-Time header to all responses
    - Logs slow requests (> threshold) as warnings
    - Optionally logs all requests at debug level
    """

    def __init__(
        self,
        app,
        slow_request_threshold: float = 1.0,
        log_all_requests: bool = False
    ):
        """Initialize the timing middleware.

        Args:
            app: The ASGI application
            slow_request_threshold: Time in seconds above which requests are logged as warnings
            log_all_requests: If True, log all requests at debug level
        """
        super().__init__(app)
        self.slow_request_threshold = slow_request_threshold
        self.log_all_requests = log_all_requests

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and add timing information."""
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as e:
            # Log errors with timing info
            duration = time.perf_counter() - start_time
            logger.error(
                f"Request error: {request.method} {request.url.path} - "
                f"{duration:.3f}s - {type(e).__name__}: {e}"
            )
            raise

        duration = time.perf_counter() - start_time

        # Add timing header
        response.headers["X-Response-Time"] = f"{duration:.3f}"

        # Log slow requests as warnings
        if duration > self.slow_request_threshold:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} - {duration:.2f}s"
            )
        elif self.log_all_requests:
            logger.debug(
                f"Request: {request.method} {request.url.path} - {duration:.3f}s"
            )

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs all incoming requests.

    Useful for debugging and monitoring request patterns.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log the request and process it."""
        # Extract useful request info
        client_host = request.client.host if request.client else "unknown"
        query_string = str(request.url.query) if request.url.query else ""

        logger.info(
            f"Request: {request.method} {request.url.path}"
            + (f"?{query_string}" if query_string else "")
            + f" from {client_host}"
        )

        response = await call_next(request)

        logger.info(
            f"Response: {request.method} {request.url.path} - "
            f"Status {response.status_code}"
        )

        return response


def setup_logging(log_level: str = "INFO") -> None:
    """Configure logging for the Vizzy application.

    Args:
        log_level: The logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Set specific loggers
    logging.getLogger("vizzy").setLevel(logging.DEBUG)
    logging.getLogger("vizzy.performance").setLevel(logging.INFO)
    logging.getLogger("vizzy.cache").setLevel(logging.DEBUG)

    # Quiet down noisy libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
