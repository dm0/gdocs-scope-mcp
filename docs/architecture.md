# Package architecture

The package organizes responsibilities by domain. MCP adapters call application
operations; application operations compose native parsing, targeting, pure
conversion and Google API infrastructure. Shared utilities never import an
application operation merely to reuse one of its helpers.

## Responsibilities

| Module or package | Responsibility |
| --- | --- |
| `server.py`, `__main__.py` | Construct the server, capture startup identity, configure middleware, register tools and start STDIO. |
| `tools/` | Thin MCP contracts, descriptions, schemas, annotations and explicit registration functions. |
| `google_api/credentials.py` | Token precedence, legacy aliases, gog fallback and OAuth refresh. |
| `google_api/oauth.py` | Shared Desktop client configuration, PKCE sessions, callback validation, private session files, token exchange and the google-auth public-client refresh adapter. |
| `auth_setup.py` | Desktop authorization CLI, bounded loopback listener and headless session lifecycle. |
| `google_api/clients.py` | Construct discovery clients; cache Docs reads by default, with explicit uncached construction where required. |
| `google_api/files.py` | Document listing and creation workflows, independent of transport. |
| `cache/` | Immutable entries, shared revision-validation algorithm, memory/disk storage, lazy backend selection and service wrapping. |
| `contracts.py`, `errors.py` | Shared receipts, failure data, pagination and application exceptions, without MCP dependencies. |
| `documents/native_models.py`, `styles.py` | Validate and normalize native Google Docs payloads and native style values. |
| `documents/rendering.py` | Render native elements and retain recovered code/table presentation state. Native methods delegate here to preserve the rendering interface. |
| `documents/models.py`, `receipts.py` | Hierarchy/search/read models and document-edit receipts. |
| `documents/parsing.py`, `targeting.py` | Parse hierarchy and source runs; map Python text offsets to checked UTF-16 source ranges. |
| `documents/tabs.py`, `fetching.py` | Select tabs, scope native requests and fetch coherent native snapshots. |
| `documents/reading.py`, `editing.py` | Accepted-content reads and direct document-edit workflows. |
| `documents/snapshots.py` | Pure native-data normalization shared by revision guards and table snapshots. |
| `suggestions/` | Proposal models, indexing, accepted-content projection, reading and explicit proposal writes. |
| `comments.py`, `comment_models.py` | Native comment threads, anchored creation, persistence checks, pagination and receipts. |
| `tables/geometry.py`, `refs.py`, `references.py`, `tokens.py` | Traversal, span geometry, reference construction and portable token validation below readers and writers. |
| Other `tables/` modules | Native fetch/render support, table reads, snapshots, selected-state comparison and patch/format/structure/merge workflows. |
| `rich_text/` | Insertion representations, parsing, pure compilation, plans, staged execution and opt-in image uploads. |
| `revision_guards.py` | Revision preconditions, source dependencies, bounded replanning and confirmed-batch accounting. |
| `entities.py`, `entity_edit.py`, `image_layout.py` | Cohesive entity representations/edits and native image layout calculations. |
| `tool_inputs.py`, `settings.py` | Pure shared input validation and configuration. They do not depend on MCP registration. |
| `tool_errors.py`, `tool_logging.py`, `diagnostics.py` | Transport failure conversion, middleware/logging and source identity. |

Keep small cohesive modules intact. There is no module-size target, generic
dependency-injection framework or automatic registration scan. Package
`__init__.py` files remain lightweight and do not re-export feature inventories.

## Dependency rules

1. Only `server.py`, `tools/`, `tool_logging.py` and `tool_errors.py` depend on
   FastMCP or MCP protocol types. `__main__.py` is the startup bridge to server.
   Lower layers raise `errors.ToolFailureError` carrying `EditFailedResponse`;
   transport conversion stays at the boundary.
2. Count deferred imports when checking dependency direction. Moving an import
   inside a function does not make an architectural cycle acceptable. The disk
   cache's import in backend selection is deliberately lazy so disabled or
   memory-only caching never opens SQLite or creates a cache directory.
3. Shared parsing, targeting, native schemas and table reference utilities do
   not depend on document editing, table readers or feature write workflows.
   Suggestions may construct table references without importing table readers.
4. Pure rich-text modules (`models`, `validation`, `paragraphs`,
   `paragraph_requests`, `cells`, `parsing`, `plans`, `compiler`) do not import
   Google clients, revision orchestration, uploads or insertion execution.
5. Import shared behavior through its explicit function/type API. Do not import
   another module's underscore-prefixed helper. If two consumers need a helper,
   place it below both consumers and give the shared contract a meaningful name.
6. Keep representations distinct: native API models, hierarchy/source maps,
   insertion models, rendering state and tool receipts have separate owners.
   Preserve validators and normalization at the boundary that owns the data.

`tests/test_architecture.py` checks eager and deferred imports for cycles and
prohibited dependencies. Extend it when introducing a new boundary.

## Internal APIs

- `google_api.clients.get_service(api='docs', version='v1', cached=True)` is
  the API client seam. Tests usually replace `clients.build` and
  `credentials.load_credentials`; tests for a specific workflow may replace
  `clients.get_service`. Do not patch helpers in document-edit orchestration.
- `documents.fetching.get_document(service, doc_id, tab_id=...)` obtains native
  inline-suggestion coordinates, selects the pinned/explicit tab and remembers
  the revision snapshot. `documents.tabs.select`, `discover`, `scope_requests`
  and `require_matching_tab` own tab identity and request scoping.
- `documents.parsing.parse_document_tree`, `extract_paragraphs` and
  `paragraph_text_map` expose hierarchy and original source runs. Rendering is
  display data; it must never become an edit-coordinate map.
- `documents.targeting.build_full_text_map`, `full_text_pos_to_doc_index` and
  `full_text_range_to_doc_indices` preserve UTF-16 width and reject matches
  crossing omitted native structure.
- `documents.rendering` escapes literal text separately from generated markup,
  including Markdown syntax and HTML attributes. Character references belong
  only to display output; source maps retain original native characters.
- `tables.geometry.walk_tables` and `cell_geometry` describe native paths and
  conservative span geometry. `tables.refs.Layout` and
  `tables.references.reference_map` construct checked references independently
  of table-reading operations. `tables.fetching.fetch_native` enforces revision
  availability; `tables.rendering.native_model` renders a copied snapshot.
- `suggestions.reading.fetch` pairs native and accepted-content views at one
  revision. Its `table_references` utility checks projection safety before
  exposing references. Proposal preview indices never drive writes.
- `rich_text.paragraphs.parse_html` is the shared paragraph/cell primitive.
  Structural table dispatch is an explicit callback from
  `rich_text.parsing.html_to_gpars`; cell conversion uses the primitive without
  table dispatch. `paragraph_requests.compile_paragraphs` and `paragraph_text`
  compile and describe pure paragraph requests.
- `rich_text.cells.convert_table` validates rectangular inline cell content and
  uses those same paragraph primitives. Existing-table patching shares it and
  does not depend on insertion execution.
- `rich_text.compiler.markdown_to_requests` and `gpars_to_requests` compose
  ordinary requests or a pure `plans.TableInsertionPlan`. Plans can group,
  rebase and preview requests without network access. They own no execution
  counters and have no `execute` method.
- `rich_text.execution.TableInsertionExecution(plan)` owns mutable batch
  progress, native table creation/readback and strict revision chaining.
  `rich_text.insertion.insert_content` owns the complete insertion workflow.
  `rich_insertion_requests` prepares ordinary content independently of uploads;
  `image_uploads.staged_local_images` loads/stages opt-in local sources and
  attempts cleanup on every exit. Validation precedes public uploads.

## Extension recipes

### Add an MCP tool

Implement the application operation and its feature-owned request/response
models first. Add a thin adapter to the appropriate `tools/` module, with
explicit schema, action annotations and complete caller-facing documentation.
Register it explicitly from the feature registration function. Keep the
intentional feature registration sequence in `server.py`; do not register via
import side effects. Add behavior, failure and schema tests through the MCP
client, and review deliberate changes to the frozen transport contract.

### Add a document feature

Use the shared client, native fetch, tab and source-targeting APIs. Define
whether the operation consumes native or accepted-content coordinates. Keep
revision checks and retry dependencies explicit. Put native traversal below
both readers and writers, and keep feature receipts near their owner. Verify
UTF-16, omitted structure, tab isolation, partial writes and native readback
where relevant. Never make a reader or utility import document editing to
obtain authentication or parsing.

### Add a conversion feature

Define insertion-only data in `rich_text.models`, parse and validate it without
network calls, and compile native requests through shared primitives. Add new
structural dispatch at the parsing composition boundary. Keep upload staging,
API execution, readback and revision chaining in their existing execution
owners. Exercise cell and body conversion independently when both support the
feature. Unsupported input must fail before uploads or document mutations.

## Compatibility and validation

Preserve the MCP initialization instructions, registration order, names,
descriptions, annotations, input/output schemas and structured failures.
`tests/test_refactor_contracts.py` freezes the complete serialized catalog and
initialization text from revision `096c27e`. Behavior tests retain native
request, rendered-content, receipt and failure assertions at API-client seams.
Do not update these contracts simply to make a structural change pass.

Preserve both console entry points, `python -m gdocs_scope_mcp`, configuration
and legacy token aliases. Old flat private module paths are implementation
details; do not add blanket compatibility re-export layers. Recursive source
fingerprinting and setuptools package discovery must include every subpackage.

Run affected tests after each extraction and the complete offline suite before
delivery. Run global Ruff and `git diff --check`. Verify isolated STDIO
discovery and worktree identity, then existing opt-in live regressions only
against the explicitly authorized development document. Respect each fixture's
retention/restoration contract, disable optional manual UI waits, inspect stderr
and verify upload/subprocess cleanup. Keep logs outside tracked source. Build
wheel and sdist, inspect package inclusion and verify both installed entry
points plus installed-wheel MCP discovery in an isolated environment.
