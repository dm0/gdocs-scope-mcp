"""Authorize the local Google Docs MCP client using Desktop OAuth and PKCE."""

import argparse
import json
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from google.auth.exceptions import GoogleAuthError

from gdocs_scope_mcp.google_api import oauth
from gdocs_scope_mcp.settings import (
    default_token_path,
    get_settings,
    optional_env,
)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
]
CLIENT_ID_ENV_VAR = 'GDOCS_SCOPE_MCP_CLIENT_ID'
CLIENT_SECRET_ENV_VAR = 'GDOCS_SCOPE_MCP_CLIENT_SECRET'


def load_client_config(creds_path: Path) -> dict:
    """Read Desktop client settings; reject web application registrations."""
    raw = json.loads(creds_path.read_text())
    if 'installed' in raw:
        return raw['installed']
    if 'client_id' in raw:
        return raw
    raise oauth.AuthorizationError(
        'Use credentials for an OAuth Desktop app, not a Web application.'
    )


def save_token(token_response, session, client_secret, out_path):
    """Save refresh credentials without PKCE or identity material."""
    data = {
        'client_id': session.client_id,
        'refresh_token': token_response['refresh_token'],
        'scopes': token_response.get(
            'scope', ' '.join(session.scopes),
        ).split(),
        'token_uri': oauth.TOKEN_URI,
        'auth_method': 'pkce-secret' if client_secret else 'pkce-public',
    }
    if client_secret:
        data['client_secret'] = client_secret
    oauth.write_private_json(out_path, data)


class CallbackServer(HTTPServer):
    """Bound accepted connections as well as the total authorization wait."""

    def get_request(self):
        """Limit a stalled local connection to the remaining session time."""
        connection, address = super().get_request()
        remaining = self.deadline - time.monotonic()
        connection.settimeout(max(0.01, min(1, remaining)))
        return connection, address


def callback_handler(session, result):
    """Create a per-attempt handler without shared callback state."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """Validate redirects before accepting a code for exchange."""
            if urlsplit(self.path).path != oauth.CALLBACK_PATH:
                self.send_error(404)
                return
            try:
                origin = session.redirect_uri.removesuffix(oauth.CALLBACK_PATH)
                result['code'] = session.callback_code(origin + self.path)
            except oauth.AuthorizationError as exc:
                result['error'] = exc
            self.send_response(400 if 'error' in result else 200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Return to the terminal to see the result.')

        def log_message(self, *args):
            """Never log callback URLs, authorization codes or state."""

    return Handler


def run_local_flow(client_id, client_secret, out_path, timeout):
    """Open the browser and receive one validated loopback callback."""
    result = {}
    with CallbackServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as server:
        redirect = f'http://127.0.0.1:{server.server_port}{oauth.CALLBACK_PATH}'
        session = oauth.AuthorizationSession.create(
            client_id, redirect, SCOPES, timeout,
        )
        server.RequestHandlerClass = callback_handler(session, result)
        server.deadline = time.monotonic() + timeout
        url = session.authorization_url()
        print('Open this URL in your system browser:\n' + url)
        webbrowser.open(url)
        while not result:
            remaining = server.deadline - time.monotonic()
            if remaining <= 0:
                raise oauth.AuthorizationError('Authorization timed out.')
            server.timeout = min(remaining, 1)
            server.handle_request()
        if 'error' in result:
            raise result['error']
    tokens = oauth.exchange_code(session, result['code'], client_secret)
    save_token(tokens, session, client_secret, out_path)


def prepare_headless(client_id, path, timeout):
    """Persist an attempt and print its URL for manual loopback completion."""
    with HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as server:
        redirect = f'http://127.0.0.1:{server.server_port}{oauth.CALLBACK_PATH}'
    session = oauth.AuthorizationSession.create(
        client_id, redirect, SCOPES, timeout,
    )
    oauth.save_session(session, path)
    print('Open this URL in your system browser:\n'
          + session.authorization_url())
    print('After consent, copy the complete loopback redirect URL, even if '
          'the browser cannot connect. Keep the session file private.')
    return session


def run_headless_flow(client_id, client_secret, out_path, timeout, path):
    """Retain PKCE state while the user pastes the complete redirect URL."""
    prepare_headless(client_id, path, timeout)
    try:
        callback = input('Paste the full redirect URL: ').strip()
        session, code = oauth.consume_session(path, callback)
        tokens = oauth.exchange_code(session, code, client_secret)
        save_token(tokens, session, client_secret, out_path)
    finally:
        path.unlink(missing_ok=True)


def main():
    """Select a client and run a bounded, session-bound PKCE authorization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', '-c', type=Path,
                        help='Desktop OAuth credentials JSON')
    parser.add_argument('--client-id', help='Custom Desktop OAuth client ID')
    parser.add_argument('--client-secret',
                        help='Matching secret for a custom Desktop client')
    parser.add_argument('--out', '-o', type=Path, default=default_token_path(),
                        help='Token output path (default: %(default)s)')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--headless', action='store_true')
    modes.add_argument('--prepare', action='store_true',
                       help='Save a PKCE session and print its consent URL')
    modes.add_argument('--callback-url', '--code', dest='callback_url',
                       help='Complete redirect URL for a saved PKCE session; '
                       'a bare authorization code is not accepted')
    parser.add_argument('--session', type=Path,
                        help='Private, single-use PKCE session file')
    parser.add_argument('--timeout', type=int, default=oauth.DEFAULT_TIMEOUT,
                        help='Authorization session lifetime in seconds')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if (args.prepare or args.callback_url) and not args.session:
        parser.error('--prepare and --callback-url require --session')
    if args.session and not (
        args.prepare or args.callback_url or args.headless
    ):
        parser.error('--session requires a headless or callback mode')

    try:
        if args.credentials:
            config = load_client_config(args.credentials.expanduser())
            client_id = config['client_id']
            secret = config.get('client_secret')
        else:
            client_id = args.client_id
            if not client_id:
                configured = optional_env(CLIENT_ID_ENV_VAR)
                client_id = (configured.strip() if configured
                             else get_settings().client_id)
            secret = args.client_secret or optional_env(CLIENT_SECRET_ENV_VAR)
        if args.callback_url:
            session, code = oauth.consume_session(args.session.expanduser(),
                                                  args.callback_url)
            if client_id and client_id != session.client_id:
                raise oauth.AuthorizationError(  # noqa: TRY301
                    'Session client mismatch.',
                )
            if (session.client_id == oauth.PROJECT_CLIENT_ID
                    and not args.credentials):
                secret = (secret or oauth.PROJECT_CLIENT_SECRET
                          if client_id else oauth.PROJECT_CLIENT_SECRET)
            tokens = oauth.exchange_code(session, code, secret)
            save_token(tokens, session, secret, args.out.expanduser())
        else:
            if not client_id:
                client_id = oauth.PROJECT_CLIENT_ID
                secret = oauth.PROJECT_CLIENT_SECRET
            elif client_id == oauth.PROJECT_CLIENT_ID and not args.credentials:
                secret = secret or oauth.PROJECT_CLIENT_SECRET
            if not client_id:
                raise oauth.AuthorizationError(  # noqa: TRY301
                    'No project client is configured. Provide --client-id '
                    'or --credentials for a registered Desktop app.'
                )
            print('Scopes: ' + ', '.join(SCOPES))
            path = (args.session.expanduser() if args.session else
                    args.out.expanduser().with_suffix('.oauth-session.json'))
            if args.prepare:
                prepare_headless(client_id, path, args.timeout)
                print(f'Session saved: {path}')
                return
            if args.headless:
                run_headless_flow(client_id, secret, args.out.expanduser(),
                                  args.timeout, path)
            else:
                run_local_flow(client_id, secret, args.out.expanduser(),
                               args.timeout)
    except oauth.AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, KeyError, ValueError, GoogleAuthError) as exc:
        print(f'Authorization failed ({type(exc).__name__}). '
              'Check the Desktop client and session; start a new attempt.',
              file=sys.stderr)
        raise SystemExit(1) from None
    except (KeyboardInterrupt, EOFError):
        print('Authorization cancelled.', file=sys.stderr)
        raise SystemExit(1) from None
    print('✓ Authorisation successful')
    print(f'✓ Token saved: {args.out.expanduser()}')
    print(f'Set GDOCS_SCOPE_MCP_TOKEN={args.out.expanduser()}')


if __name__ == '__main__':
    main()
