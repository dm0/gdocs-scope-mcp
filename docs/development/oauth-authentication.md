# Desktop OAuth implementation and verification

[Development](../development.md) · [Getting started](../getting-started.md) · [Configuration](../configuration.md)

This document records implementation details and verification evidence for
issue #39. User setup instructions belong in Getting started.

## Implementation

`google_api/oauth.py` owns PKCE S256 sessions, callback validation, private
session files and token exchange. `auth_setup.py` owns the CLI and loopback
listener. Each attempt has independent random state and verifier values. The
listener uses an available port on `127.0.0.1`, enforces a deadline and closes
on success, failure or cancellation.

Headless sessions retain the originating client, redirect URI, verifier, state,
scopes and expiry. Completion consumes the session under a file lock; a bare
code cannot replace the original session context. The verifier and state are
not written to the resulting token file.

Secret-bearing tokens use the standard google-auth credentials implementation.
The public-client adapter removes the library's empty `client_secret` field
from refresh requests. Tokens marked `pkce-public` ignore ambient secret
overrides. Adapter coverage does not establish that a registered Google client
accepts secretless requests. No automatic fallback changes the flow after a
rejection.

PKCE and a Desktop client secret serve different roles. A distributed client
cannot keep a shared secret confidential; PKCE binds each authorization code
to a fresh verifier. A captured code alone is insufficient for exchange, even
when the shared client credentials are known. PKCE does not protect stolen
access or refresh tokens.

## Verification

Live checks on 2026-10-29 used the registered project Desktop client:

| Check | Result |
| --- | --- |
| Browser consent and validated loopback callback | Passed |
| PKCE code exchange without client secret | Rejected twice; Google reported `client_secret is missing.` |
| Secretless refresh | Not reached: no token was issued |
| PKCE code exchange with locally supplied Desktop credentials JSON | Passed |
| Refresh and authorized document read in an isolated STDIO process | Passed |
| Refresh and document read after restarting in another isolated process | Passed |

The saved token had owner-only permissions and contained a refresh token but
no access token, so each fresh process had to refresh before reading. Existing
user credentials were not replaced. The client secret, credentials JSON and
test token remained outside the repository. These checks establish
compatibility for the supplied client with its secret, not general acceptance
of ID-only Desktop authorization.

Permanent coverage is in `tests/test_auth_setup.py` and `tests/test_oauth_pkce.py`.
It exercises actual loopback sockets and the installed google-auth refresh
implementation with substituted token-endpoint responses. The complete offline
suite passed with 1711 tests and 91 skips. Ruff, wheel/sdist builds and both
installed entry points passed; installed-wheel discovery exposed 32 MCP tools.

## Distribution considerations

The bundled client ID alone cannot complete authorization for the registered
project client. Local credentials JSON is the verified setup. Distribution of
a shared client secret is not implemented; do not commit one to the repository.

The project owner manages branding, consent, verification, quotas and client
lifecycle. Publishing the consent screen and completing verification are
separate steps. PKCE does not change scope classifications, and changing the
bundled client does not migrate existing refresh tokens or grants.

References: [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies),
[production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview).
