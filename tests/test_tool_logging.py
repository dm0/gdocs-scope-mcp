"""Exercise logging around MCP calls without Google API access."""


import asyncio
import logging
import re
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.tool_logging import (
    LOG_LEVEL_ENV,
    LOGGER_NAME,
    ToolCallLoggingMiddleware,
    configure_logging,
)


@pytest.fixture
def logging_server():
    """Provide successful, rejected, and exception-raising tools."""
    app = FastMCP('logging-test', middleware=[ToolCallLoggingMiddleware()])

    @app.tool
    def succeed(value: str) -> dict:
        return {'echo': value}

    @app.tool
    def fail(value: str) -> dict:
        del value
        raise ValueError('Example failure')

    @app.tool
    def reject(value: str) -> EditFailedResponse:
        del value
        return EditFailedResponse(
            code='HEADING_NOT_FOUND',
            description='Missing heading',
            suggested_action='Read outline',
        )

    return app


@pytest.mark.parametrize(
    ('name', 'status', 'level', 'error'),
    [
        ('succeed', 'success', logging.INFO, None),
        ('fail', 'failure', logging.ERROR, 'Example failure'),
        ('reject', 'failure', logging.ERROR, 'Missing heading'),
    ],
)
def test_tool_outcomes_are_logged(
    logging_server,
    caplog,
    *,
    name,
    status,
    level,
    error,
):
    """Log timing and failures while preserving results and MCP errors."""
    private_value = 'private-document-text'

    async def call():
        async with Client(logging_server) as client:
            return await client.call_tool(
                name,
                {'value': private_value},
                raise_on_error=False,
            )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = asyncio.run(call())

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    record = records[0]
    message = record.getMessage()
    assert record.levelno == level
    assert f'tool={name} status={status}' in message
    timing = re.search(r'duration_ms=(\d+\.\d+)', message)
    assert timing is not None
    assert float(timing[1]) >= 0
    assert private_value not in message
    if name == 'fail':
        assert result.is_error
        assert record.exc_info is not None
        assert error in str(record.exc_info[1])
    elif name == 'reject':
        assert result.is_error
        assert result.structured_content['ok'] is False
        assert 'code=HEADING_NOT_FOUND' in message
        assert error not in message
    else:
        assert not result.is_error
        assert result.structured_content == {'echo': private_value}


@pytest.mark.parametrize('level', [None, 'warning', 'DEBUG'])
def test_log_level_controls_stderr(level, monkeypatch, capsys):
    """Configuration controls our logger and leaves stdout for MCP traffic."""
    logger = logging.getLogger(LOGGER_NAME)
    monkeypatch.setattr(logger, 'handlers', [])
    monkeypatch.setattr(logger, 'level', logger.level)
    monkeypatch.setattr(logger, 'propagate', logger.propagate)
    # Reproduce main(): a WARNING root must not suppress our INFO/DEBUG logs.
    root = logging.getLogger()
    monkeypatch.setattr(root, 'level', logging.WARNING)
    if level is None:
        monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    else:
        monkeypatch.setenv(LOG_LEVEL_ENV, level)

    selected = configure_logging()
    logger.debug('debug probe')
    logger.info('info probe')
    logger.warning('warning probe')
    captured = capsys.readouterr()

    assert selected == (level or 'INFO').upper()
    assert captured.out == ''
    assert 'warning probe' in captured.err
    assert ('info probe' in captured.err) == (selected != 'WARNING')
    assert ('debug probe' in captured.err) == (selected == 'DEBUG')


def test_invalid_log_level_is_rejected(monkeypatch):
    """A typo should fail clearly instead of silently disabling logging."""
    monkeypatch.setenv(LOG_LEVEL_ENV, 'VERBOSE')

    with pytest.raises(ValueError, match=LOG_LEVEL_ENV):
        configure_logging()


def test_cancellation_propagates_and_logs_cancelled(caplog):
    """A cancelled operation must not become an ordinary failure result."""
    context = SimpleNamespace(message=SimpleNamespace(name='cancel_probe'))

    async def cancel(_context):
        raise asyncio.CancelledError

    with (
        caplog.at_level(logging.INFO, logger=LOGGER_NAME),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(ToolCallLoggingMiddleware().on_call_tool(context, cancel))

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert 'status=cancelled' in records[0].getMessage()
