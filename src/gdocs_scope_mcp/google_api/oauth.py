"""Manage isolated Desktop OAuth PKCE sessions and token requests."""

import base64
import hashlib
import json
import math
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from filelock import FileLock
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

TOKEN_URI = 'https://oauth2.googleapis.com/token'
CALLBACK_PATH = '/oauth2/callback'
DEFAULT_TIMEOUT = 300
# Shared Desktop client credentials are public application identifiers.
# They do not grant access to user data; user tokens must remain private.
PROJECT_CLIENT_SECRET = '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'
PROJECT_CLIENT_ID = (
    '988487172113-bf649u95noqubdtn4jcvrlfdmd37sii5.apps.googleusercontent.com'
)


class AuthorizationError(ValueError):
    """Report an authorization failure without returning sensitive payloads."""


@dataclass(repr=False)
class AuthorizationSession:
    """Tie the verifier and state to one client, redirect and deadline."""

    client_id: str
    redirect_uri: str
    scopes: list[str]
    expires_at: float
    verifier: str = field(repr=False)
    state: str = field(repr=False)

    def __post_init__(self):
        """Reject malformed saved sessions before they can make requests."""
        redirect = urlsplit(self.redirect_uri)
        if (not isinstance(self.client_id, str) or not self.client_id
                or redirect.scheme != 'http'
                or redirect.hostname != '127.0.0.1'
                or not redirect.port or redirect.username or redirect.password
                or redirect.path != CALLBACK_PATH
                or redirect.query or redirect.fragment
                or not isinstance(self.verifier, str)
                or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', self.verifier)
                or not isinstance(self.state, str) or not self.state.isascii()
                or not self.state
                or not isinstance(self.expires_at, (int, float))
                or not math.isfinite(self.expires_at)
                or not isinstance(self.scopes, list)
                or not all(isinstance(scope, str) for scope in self.scopes)):
            raise AuthorizationError('Invalid authorization session.')

    @classmethod
    def create(cls, client_id, redirect_uri, scopes, timeout=DEFAULT_TIMEOUT):
        """Generate independent cryptographic randomness for each attempt."""
        return cls(client_id, redirect_uri, list(scopes),
                   time.time() + timeout,
                   secrets.token_urlsafe(64), secrets.token_urlsafe(32))

    def check_active(self):
        """Reject expired sessions before using their authorization data."""
        if time.time() >= self.expires_at:
            raise AuthorizationError('Authorization session expired.')

    def authorization_url(self):
        """Construct consent using only the S256 verifier challenge."""
        self.check_active()
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.verifier.encode('ascii')).digest()
        ).rstrip(b'=').decode('ascii')
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': self.client_id, 'redirect_uri': self.redirect_uri,
            'response_type': 'code', 'scope': ' '.join(self.scopes),
            'access_type': 'offline', 'prompt': 'consent',
            'state': self.state, 'code_challenge': challenge,
            'code_challenge_method': 'S256',
        })

    def callback_code(self, callback_url):
        """Validate the exact callback destination and unambiguous response."""
        self.check_active()
        target = urlsplit(self.redirect_uri)
        callback = urlsplit(callback_url)
        if ((callback.scheme, callback.netloc, callback.path)
                != (target.scheme, target.netloc, target.path)
                or callback.fragment):
            raise AuthorizationError('Unexpected OAuth callback URL.')
        params = parse_qs(callback.query, keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()):
            raise AuthorizationError('Duplicate OAuth callback parameters.')
        state = params.get('state', [''])[0]
        if not state or not secrets.compare_digest(
            state.encode('utf-8'), self.state.encode('ascii'),
        ):
            raise AuthorizationError('OAuth callback state mismatch.')
        if 'error' in params:
            if 'code' in params:
                raise AuthorizationError('Ambiguous OAuth callback.')
            raise AuthorizationError('Google authorization was denied.')
        code = params.get('code', [''])[0]
        if not code:
            raise AuthorizationError('OAuth callback contains no code.')
        return code


def write_private_json(path: Path, data: dict, *, exclusive=False):
    """Write owner-only JSON without first creating a world-readable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        if hasattr(os, 'fchmod'):
            os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, indent=2)


def save_session(session: AuthorizationSession, path: Path):
    """Persist a pending session without overwriting another attempt."""
    write_private_json(path, asdict(session), exclusive=True)


def consume_session(path: Path, callback_url: str):
    """Validate and consume a persisted attempt once across CLI runs."""
    with FileLock(str(path) + '.lock', timeout=5):
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise AuthorizationError('Session file must have mode 0600.')
        try:
            session = AuthorizationSession(**json.loads(path.read_text()))
            code = session.callback_code(callback_url)
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise AuthorizationError('Invalid authorization session file.') \
                from exc
        finally:
            # A failed callback also consumes the attempt; never replay it.
            path.unlink()
    return session, code


def exchange_code(session, code, client_secret=None):
    """Exchange a code with its original verifier; never retry without PKCE."""
    session.check_active()
    body = {
        'client_id': session.client_id, 'code': code,
        'redirect_uri': session.redirect_uri,
        'code_verifier': session.verifier,
        'grant_type': 'authorization_code',
    }
    if client_secret:
        body['client_secret'] = client_secret
    response = Request()(
        TOKEN_URI, method='POST', body=urlencode(body).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=30,
    )
    if response.status != HTTPStatus.OK:
        reason = token_error_reason(response.data)
        raise AuthorizationError(
            f'Google rejected the PKCE token exchange ({reason}). '
            'Start a new session; '
            'check the Desktop client registration. No fallback was attempted.'
        )
    try:
        tokens = json.loads(response.data)
        if not all(isinstance(tokens.get(key), str) and tokens[key]
                   for key in ('access_token', 'refresh_token')):
            raise AuthorizationError('Google returned incomplete tokens.')
    except (ValueError, TypeError) as exc:
        raise AuthorizationError('Google returned invalid tokens.') from exc
    return tokens


def token_error_reason(payload):
    """Expose only recognized OAuth errors, never arbitrary response text."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return 'unrecognized response'
    if not isinstance(data, dict):
        return 'unrecognized response'
    if data.get('error_description') == 'client_secret is missing.':
        return 'client_secret is required by Google for this client'
    recognized = {
        'invalid_request', 'invalid_client', 'invalid_grant',
        'unauthorized_client', 'unsupported_grant_type', 'invalid_scope',
        'access_denied', 'temporarily_unavailable', 'server_error',
    }
    error = data.get('error')
    return error if isinstance(error, str) and error in recognized else (
        'unrecognized response'
    )


class PublicClientCredentials(Credentials):
    """Use google-auth refresh without sending an empty secret field."""

    def refresh(self, request):
        """Strip only the empty secret from this client's token request."""
        def public_request(
            url, method='GET', body=None, headers=None, **kwargs,
        ):
            if url == self.token_uri and method == 'POST' and body:
                params = parse_qs(body.decode(), keep_blank_values=True)
                if params.get('client_secret') != ['']:
                    raise RefreshError('Unexpected secret in public flow.')
                params.pop('client_secret')
                body = urlencode(params, doseq=True).encode()
            return request(url, method=method, body=body, headers=headers,
                           **kwargs)

        return super().refresh(public_request)
