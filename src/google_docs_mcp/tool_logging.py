"""Log tool outcomes to stderr without recording arguments or results."""

import logging
import os
import sys
from asyncio import CancelledError
from time import perf_counter

from fastmcp.server.middleware import Middleware, MiddlewareContext

LOGGER_NAME = 'google_docs_mcp'
LOG_LEVEL_ENV = 'GOOGLE_DOCS_MCP_LOG_LEVEL'
logger = logging.getLogger(LOGGER_NAME)


def configure_logging() -> str:
    """Configure our stderr handler and return the selected log level."""
    level = os.environ.get(LOG_LEVEL_ENV, 'INFO').strip().upper()
    valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
    if level not in valid_levels:
        raise ValueError(
            f'{LOG_LEVEL_ENV} must be one of {sorted(valid_levels)}'
        )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s pid=%(process)d %(message)s'
        )
    )
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return level


class ToolCallLoggingMiddleware(Middleware):
    """Record completion time and errors without changing tool behavior."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Time and log a call without changing its result or exception."""
        started = perf_counter()
        name = context.message.name
        logger.debug('tool=%s status=started', name)
        try:
            result = await call_next(context)
        except CancelledError:
            logger.warning(
                'tool=%s status=cancelled duration_ms=%.3f',
                name,
                (perf_counter() - started) * 1000,
            )
            raise
        except Exception:
            logger.exception(
                'tool=%s status=failure duration_ms=%.3f',
                name,
                (perf_counter() - started) * 1000,
            )
            raise

        duration_ms = (perf_counter() - started) * 1000
        payload = getattr(result, 'structured_content', None)
        if isinstance(payload, dict) and payload.get('ok') is False:
            logger.error(
                'tool=%s status=failure duration_ms=%.3f error=%s',
                name,
                duration_ms,
                payload.get('description', 'Edit failed'),
            )
        else:
            logger.info(
                'tool=%s status=success duration_ms=%.3f',
                name,
                duration_ms,
            )
        return result
