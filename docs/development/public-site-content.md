# Draft public website content

Preparation for [#46](https://github.com/dm0/gdocs-scope-mcp/issues/46).
These texts are unpublished drafts. The project owner must review the privacy
and terms statements against the final deployment before publication.
The [readiness audit](public-oauth-readiness.md) records unresolved requirements.

## Homepage

### gdocs-scope-mcp

Google Docs editing for AI assistants, organized around document sections.

Connect your MCP-compatible assistant to read document outlines, work with
selected sections, edit using text anchors, manage tables, and review native
comments and suggestions. The server runs on the computer or remote host
where you install it and communicates with your chosen MCP application.

Choose selected-file access through Google Picker, or configure broad Drive
access for account-wide document discovery. Selected-file access uses
`drive.file`; a document link alone does not grant access. Broad access requests
more extensive permissions. You choose the configuration and grant consent
through Google's browser authorization flow.

Source code and setup: <https://github.com/dm0/gdocs-scope-mcp>.
This is an independent open-source project, not a Google product.

Support: <mailto:gdocs-scope-mcp@googlegroups.com>.
Do not send credentials or private document content to the support group.

The published homepage will link to Privacy and Terms on the same domain.
Until public authorization is verified, the shared OAuth client may require
the project owner to add your account as a test user. A custom OAuth client
remains available through the documented configuration.

## Privacy policy draft

### Scope

This policy describes the gdocs-scope-mcp software distributed by the project.
You choose the machine running the server, the MCP host and any AI provider.
Those services have their own policies and may process the information that
the server returns to them. Installing this software does not establish their
retention, training or confidentiality practices.

### Information accessed and purposes

The software accesses Google Docs content, file identifiers and metadata,
document structure, comments, suggestions and related author metadata as
needed for the tools you invoke. It reads and changes this information to
perform document operations requested through your MCP host. Depending on
the configured mode, discovery covers application-accessible files or the
Google Docs available to your account. The authorization flow also checks a
Google account identifier to keep subsequent consent bound to the same account.

Document results, snippets, metadata and edit receipts are returned to the
MCP host. Your host may send them to an AI provider and retain conversations,
tool inputs, outputs or logs. Review that host's policies before connecting
sensitive documents. The package itself does not implement model training,
advertising or sale of document data.

### Credentials and storage

OAuth refresh credentials are stored in a token file on the machine running
the server. New files use owner-only permissions; they are not encrypted by
the application. Protect that machine, backups and any remote administrator
access. Google authorization exchanges use HTTPS. Local MCP communication
uses STDIO. Google-hosted authorization and file selection occur in a browser.

Document caching is disabled by default. If enabled, the cache can store full
native document snapshots in memory or in an unencrypted local SQLite file.
Expiry prevents reuse after the configured lifetime; it is not a secure-erasure
guarantee. Remove the cache after stopping the server if you need to discard
its stored contents. Application outcome logs omit tool arguments/results,
but error diagnostics and the MCP host can retain additional information.

Browser completion URLs contain short-lived authorization codes. If you send
one through a remote chat/MCP workflow, that host may retain the message or
tool arguments. Do not post those URLs publicly.

### Images and other network recipients

Opt-in local image uploads send selected local images to Google Drive and
temporarily make those files readable by anyone with the link so Google Docs
can insert them. The software attempts to delete the temporary source files
after insertion; failures are reported for follow-up. Deleting a temporary
source does not remove an image already inserted into a document. Image URL
insertion also causes Google to retrieve the supplied image URL.

The software exchanges authorized requests with Google's API services. It
does not route document contents through a project-operated application
backend. A user-chosen remote MCP host still receives those contents. The
project website is hosted by GitHub Pages, whose request processing and logs
are governed by GitHub's policies; website hosting does not handle the OAuth
code exchange or MCP document operations.

### Revocation, deletion and support

Revoke the application's access in your Google Account's third-party
connections settings. Remove its token files and optional cache from the
server machine. Changing access mode or deleting a local token alone does not
revoke Google's grants. These actions do not delete your Google Docs or copies
retained by your MCP/AI provider; manage those separately with each service.

Contact <mailto:gdocs-scope-mcp@googlegroups.com> for support and privacy
questions. Do not include tokens, browser completion URLs or document content.
Review the group's archive visibility before sharing identifying information.
Maintainers cannot directly erase files on machines they do not operate.

## Terms draft

gdocs-scope-mcp is independent open-source software provided under the
repository's MIT license, including its warranty disclaimer. Google services,
GitHub hosting and your chosen MCP/AI provider remain subject to their own
terms. Use only accounts, documents and local files you are authorized to
access, and review requested permissions before consenting.

Document tools can modify or delete content. Use your host's approval controls
and keep appropriate backups. Availability of Google's APIs and the shared
OAuth client may change. For support, contact
<mailto:gdocs-scope-mcp@googlegroups.com>.

Before publication, set the effective date, confirm the responsible project
operator's identity, review the Google Limited Use disclosure against the
permitted deployment, and finalize references to applicable third-party
policies. Do not publish this preparation note as part of the policy.
