"""Run bounded Desktop Picker sessions independently of MCP requests."""

import json
import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from filelock import Timeout
from pydantic import BaseModel, Field

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import authorization, oauth
from gdocs_scope_mcp.google_api.access import (
    DRIVE_FILE,
    require_selected_scopes,
)
from gdocs_scope_mcp.settings import get_settings

MAX_SESSIONS = 32
RESULT_RETENTION = 300
log = logging.getLogger(__name__)


class SelectedDocument(BaseModel):
    """Verified metadata for a selected Google Doc."""

    id: str
    name: str
    url: str


class SelectionStatus(BaseModel):
    """Public session state without credentials or callback contents."""

    session_id: str
    status: Literal['pending', 'completed', 'cancelled', 'expired', 'failed']
    expires_at: float
    authorization_url: str | None = None
    browser_opened: bool = False
    documents: list[SelectedDocument] = Field(default_factory=list)
    failure_code: str | None = None


def fail(code, description):
    """Return actionable authorization failures at the transport boundary."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action='Check access_mode and the configured token path. '
        'Use gdocs-scope-mcp-auth for initial authorization or migration. '
        'Keep the same MCP process when polling a selection session.',
    ))


class LoopbackServer(HTTPServer):
    """Bound a stalled callback connection as well as the accept loop."""

    def get_request(self):
        """Limit local clients to a short socket read deadline."""
        connection, address = super().get_request()
        connection.settimeout(1)
        return connection, address


def selection_handler(session, result):
    """Accept authenticated Picker callbacks without logging their content."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """Ignore unrelated and unauthenticated requests."""
            if (len(self.path) > oauth.MAX_CALLBACK_LENGTH
                    or urlsplit(self.path).path != oauth.CALLBACK_PATH):
                self.send_error(404)
                return
            callback = (session.redirect_uri.removesuffix(oauth.CALLBACK_PATH)
                        + self.path)
            params = parse_qs(urlsplit(callback).query, keep_blank_values=True)
            try:
                # Validate destination, duplicate parameters and state first.
                session.callback_code(callback)
            except oauth.AuthorizationError:
                # Denial is terminal only after independently checking state.
                state = params.get('state', [])
                valid_state = (len(state) == 1 and secrets.compare_digest(
                    state[0].encode(), session.state.encode(),
                ))
                if (valid_state and params.get('error') == ['access_denied']
                        and 'code' not in params
                        and all(len(v) == 1 for v in params.values())):
                    result['status'] = 'cancelled'
                self.respond(400)
                return
            try:
                result['ids'] = session.picked_files(callback)
                result['code'] = params['code'][0]
            except oauth.AuthorizationError:
                result['status'] = 'failed'
            self.respond(200 if 'code' in result else 400)

        def respond(self, status):
            """Return a static page without reflecting user input."""
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(b'Return to your MCP client to check the result.')

        def log_message(self, *args):
            """Keep authorization codes and callback parameters out of logs."""

    return Handler


class SelectionManager:
    """Own bounded listeners, session state and credential locks."""

    def __init__(self):
        """Initialize without opening listeners or accessing Google."""
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.entries = {}
        self.workers = []

    def status(self, session_id):
        """Read a public snapshot without external effects."""
        with self.lock:
            self.prune()
            if session_id not in self.entries:
                fail('RESOURCE_NOT_FOUND', 'Unknown or expired selection ID.')
            entry = self.entries[session_id]
            if entry.status == 'pending' and time.time() >= entry.expires_at:
                self.finish(session_id, 'expired')
            return self.entries[session_id].model_copy(deep=True)

    def prune(self):
        """Bound result retention and discard finished thread references."""
        now = time.time()
        self.entries = {
            key: value for key, value in self.entries.items()
            if value.status == 'pending'
            or now < value.expires_at + RESULT_RETENTION
        }
        self.workers = [worker for worker in self.workers if worker.is_alive()]

    def start(self, *, open_browser=True, timeout=oauth.DEFAULT_TIMEOUT):
        """Start selection without waiting for browser interaction."""
        if get_settings().access_mode != 'selected_files':
            fail('INVALID_ARGUMENT', 'Selection requires selected_files mode.')
        if not 1 <= timeout <= oauth.DEFAULT_TIMEOUT:
            fail('INVALID_ARGUMENT', 'Timeout must be 1 to 300 seconds.')
        path = authorization.token_path().resolve()
        with self.lock:
            self.prune()
            if self.stop.is_set() or len(self.entries) >= MAX_SESSIONS:
                fail('EDIT_CONFLICT', 'Selection service is busy or stopping.')
            destination = authorization.destination_lock(path)
            try:
                destination.acquire()
            except Timeout:
                fail('EDIT_CONFLICT', 'Another authorization owns this path.')
            server = None
            try:
                previous = (json.loads(path.read_text())
                            if path.exists() else None)
                if previous:
                    require_selected_scopes(previous.get('scopes'))
                    if not previous.get('account_id'):
                        fail('AUTHENTICATION_REQUIRED',
                             'Existing credentials lack an account binding.')
                    client = previous['client_id']
                    secret = previous.get('client_secret')
                else:
                    client, secret = authorization.client_pair()
                server = LoopbackServer(
                    ('127.0.0.1', 0), BaseHTTPRequestHandler,
                )
                redirect = (f'http://127.0.0.1:{server.server_port}'
                            + oauth.CALLBACK_PATH)
                session = oauth.AuthorizationSession.create(
                    client, redirect, [DRIVE_FILE], timeout, picker=True,
                )
                session_id = secrets.token_urlsafe(24)
                public = SelectionStatus(
                    session_id=session_id, status='pending',
                    expires_at=session.expires_at,
                    authorization_url=session.authorization_url(),
                )
                self.entries[session_id] = public
                worker = threading.Thread(
                    target=self.run,
                    args=(session_id, session, secret, server, destination,
                          path, authorization.generation(path), previous),
                    daemon=True, name='gdocs-picker',
                )
                self.workers.append(worker)
                worker.start()
            except BaseException:
                if server is not None:
                    server.server_close()
                destination.release()
                raise
        if open_browser:
            try:
                opened = bool(webbrowser.open(public.authorization_url))
            except (OSError, webbrowser.Error):
                opened = False
            with self.lock:
                self.entries[session_id].browser_opened = opened
        return self.status(session_id)

    def finish(self, session_id, status, *, documents=(), failure_code=None):
        """Replace public state without retaining URL or secrets."""
        with self.lock:
            self.entries[session_id] = self.entries[session_id].model_copy(
                update={'status': status, 'authorization_url': None,
                        'documents': [SelectedDocument(**item)
                                      for item in documents],
                        'failure_code': failure_code},
            )
            log.info('selection status=%s failure_code=%s',
                     status, failure_code)

    def run(self, session_id, session, secret, server, destination,  # noqa: PLR0917
            path, expected, previous):
        """Exchange once and always close resources."""
        result = {}
        server.RequestHandlerClass = selection_handler(session, result)
        server.timeout = 0.2
        try:
            with server:
                while not result and not self.stop.is_set():
                    if time.time() >= session.expires_at:
                        self.finish(session_id, 'expired')
                        return
                    server.handle_request()
            if self.stop.is_set():
                self.finish(session_id, 'cancelled')
                return
            if 'code' not in result:
                status = result.get('status', 'failed')
                self.finish(session_id, status,
                            failure_code=('INVALID_SELECTION'
                                          if status == 'failed' else None))
                return
            tokens = oauth.exchange_code(session, result['code'], secret)
            data, documents = authorization.verify_selection(
                tokens, session, secret, result['ids'], previous,
            )
            session.check_active()
            if self.stop.is_set():
                self.finish(session_id, 'cancelled')
                return
            authorization.install_token(path, data, expected)
            self.finish(session_id, 'completed', documents=documents)
        except Exception as error:  # noqa: BLE001
            # Exception strings may contain token endpoint or callback data.
            if time.time() >= session.expires_at:
                self.finish(session_id, 'expired')
                return
            if isinstance(error, authorization.SelectionError):
                code = error.code
            elif isinstance(error, ToolFailureError):
                code = 'INVALID_SCOPES'
            else:
                code = 'SELECTION_FAILED'
            self.finish(session_id, 'failed', failure_code=code)
        finally:
            server.server_close()
            destination.release()

    def close(self):
        """Stop listeners; network completion remains timeout bounded."""
        self.stop.set()
        for worker in list(self.workers):
            worker.join(timeout=1.5)


manager = SelectionManager()
