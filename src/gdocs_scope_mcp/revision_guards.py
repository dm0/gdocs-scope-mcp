"""Execute optimistic edits with dependencies and bounded replanning."""

import json
import logging
import time
from contextlib import ExitStack, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import wraps
from http.client import HTTPException

from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from .models import EditFailedResponse
from .settings import get_settings
from .tool_errors import ToolFailureError

MAX_ATTEMPTS = 3
_active = ContextVar('document_edit', default=None)
log = logging.getLogger(__name__)


class RevisionRaceError(Exception):
    """Signal a confirmed rejection before the pending batch was applied."""


def fail(code, description, committed=0):
    """Keep actionable failures distinct from ordinary API/input errors."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description, committed_batches=committed,
        suggested_action=(
            'Read the document and inspect the target and any completed '
            'stages before issuing a new edit. Do not blindly repeat a write '
            'whose outcome is unknown.'
        ),
    ))


def _normalized(value):
    """Remove absolute indices without dropping native text or style data."""
    if isinstance(value, dict):
        return {k: _normalized(v) for k, v in value.items()
                if k not in {'startIndex', 'endIndex'}}
    if isinstance(value, list):
        return [_normalized(v) for v in value]
    return value


def _dependencies(document, item):
    """Include only referenced object/list/definition metadata."""
    references = []

    def collect(value):
        """Find the reference fields whose metadata affects this unit."""
        if isinstance(value, dict):
            for key, child in value.items():
                collection = {'listId': 'lists',
                              'inlineObjectId': 'inlineObjects',
                              'dropdownDefinitionId': 'dropdownDefinitions',
                              }.get(key)
                if collection:
                    metadata = document.get(collection, {}).get(child)
                    references.append((collection, child, metadata))
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(item)
    return references


def _units(document):
    """Retain paragraph identity, heading ancestry and conservative tables."""
    result = []
    headings = []
    for item in document.get('body', {}).get('content', []):
        style = item.get('paragraph', {}).get('paragraphStyle', {})
        kind = style.get('namedStyleType', '')
        if kind.startswith('HEADING_'):
            level = int(kind.removeprefix('HEADING_'))
            headings = [(n, h) for n, h in headings if n < level]
            headings.append((level, style.get('headingId')))
        if 'paragraph' not in item and 'table' not in item:
            continue
        token = json.dumps([_normalized(item), headings,
                            _dependencies(document, item)], sort_keys=True)
        result.append((item['startIndex'], item['endIndex'], token))
    return result


@dataclass
class Edit:
    """Keep one call's baseline across retries, never across MCP processes."""

    stack: ExitStack
    append: bool = False
    snapshot: dict | None = None
    baseline: dict | None = None
    targets: list = field(default_factory=list)
    checked: int = 0
    attempt: int = 0
    committed: int = 0
    prepared: object = None
    prepared_index: int = 0
    prepared_requests: object = None
    expected_revision: str | None = None
    revision_mode: str = 'required'


def remember_snapshot(document):
    """Record the initial read for each planning attempt, not later lookups."""
    edit = _active.get()
    if edit is not None and edit.snapshot is None:
        if (edit.expected_revision is not None
                and document.get('revisionId') != edit.expected_revision):
            fail('EDIT_CONFLICT', 'The caller-provided document revision '
                 'is no longer current.')
        edit.snapshot = deepcopy(document)
        if edit.baseline is None:
            edit.baseline = deepcopy(document)
        elif edit.attempt:
            for token, _, _ in edit.targets:
                _check_identity(edit, _units(document), token)
    return document


def depend_on(document, start, end):
    """Cover each native unit touched by an operation's original target."""
    units = [(a, b) for a, b, _ in _units(document)
             if a < end and start < b]
    if not units:
        units = [(start, end)]
    for a, b in units:
        _depend_on_unit(document, max(a, start), min(b, end))


def _check_identity(edit, units, old_token):
    """Fail before a fresh query can replace a vanished original target."""
    old_tokens = [t for _, _, t in _units(edit.baseline)]
    new_tokens = [t for _, _, t in units]
    if old_token not in new_tokens:
        old_index = old_tokens.index(old_token)
        deleted = any(tag == 'delete' and i <= old_index < j
                      for tag, i, j, _, _ in SequenceMatcher(
                          a=old_tokens, b=new_tokens, autojunk=False,
                      ).get_opcodes())
        fail('TARGET_DELETED' if deleted else 'EDIT_CONFLICT',
             'The original target was deleted or its content/style changed.')
    if old_tokens.count(old_token) != 1 or new_tokens.count(old_token) != 1:
        fail('TARGET_AMBIGUOUS', 'Duplicate units prevent safe rebasing.')


def _depend_on_unit(document, start, end):
    """Validate the same selected native unit and relative target on retry."""
    edit = _active.get()
    if edit is None or edit.append:
        return
    units = _units(document)
    selected = [(a, b, t) for a, b, t in units if a <= start and end <= b]
    if len(selected) != 1:
        fail('TARGET_AMBIGUOUS', 'The edit target crosses native units.')
    a, _, token = selected[0]
    target = (token, start - a, end - a)
    index = edit.checked
    edit.checked += 1
    if edit.attempt == 0:
        edit.targets.append(target)
        return
    if index >= len(edit.targets):
        fail('EDIT_CONFLICT', 'The selected target set changed.')
    original = edit.targets[index]
    _check_identity(edit, units, original[0])
    if target != original:
        fail('EDIT_CONFLICT', 'Replanning selected a different target or '
             'occurrence; the edit was not retargeted.')
    # Effective named styles/list definitions can change without local runs.
    for key in ('namedStyles', 'documentStyle'):
        if document.get(key) != edit.baseline.get(key):
            fail('EDIT_CONFLICT', 'A formatting/entity dependency changed.')


def _revision_rejection(error):
    """Recognize explicit revision rejection, not arbitrary HTTP 400s."""
    if not isinstance(error, HttpError) or error.resp.status != 400:  # noqa: PLR2004
        return False
    try:
        message = json.loads(error.content)['error']['message'].lower()
    except (ValueError, KeyError, TypeError):
        return False
    return 'revision' in message and any(word in message for word in (
        'does not match', 'not the latest', 'not current', 'not valid',
        'too old', 'too far behind', 'expired', 'not found',
    ))


def uses_target_revision():
    """Respect a strict caller precondition over the configured merge mode."""
    edit = _active.get()
    return (edit is not None and edit.revision_mode == 'target'
            and edit.expected_revision is None)


def submit(service, doc_id, requests, revision=None, *, native=False,
           force_required=False):
    """Send one guarded atomic batch; classify uncertainty without replay."""
    edit = _active.get()
    if native and edit is not None and edit.expected_revision is not None:
        fail('INVALID_ARGUMENT', 'Native replace-all uses execution-time '
             'matching and does not accept expected_revision_id.')
    if edit is not None:
        if not edit.append and edit.checked != len(edit.targets):
            fail('EDIT_CONFLICT', 'The selected target set changed.')
        revision = revision or (edit.snapshot or {}).get('revisionId')
    if not native and (not isinstance(revision, str) or not revision):
        fail('REVISION_UNAVAILABLE', 'The read has no usable revision.')
    body = {'requests': requests}
    target = not native and uses_target_revision() and not force_required
    if not native:
        key = 'targetRevisionId' if target else 'requiredRevisionId'
        body['writeControl'] = {key: revision}
    try:
        result = service.documents().batchUpdate(
            documentId=doc_id, body=body,
        ).execute()
    except HttpError as error:
        if _revision_rejection(error):
            if target:
                fail('TARGET_REVISION_REJECTED', 'Google rejected the target '
                     'revision. No automatic rebase or resubmission was '
                     'performed.', edit.committed if edit else 0)
            if edit is not None and edit.committed:
                fail('PARTIAL_WRITE', 'Earlier stages committed; a later '
                     'stage lost its revision precondition.', edit.committed)
            raise RevisionRaceError from None
        if error.resp.status >= 500:  # noqa: PLR2004
            fail('WRITE_OUTCOME_UNKNOWN', 'Google did not confirm the write '
                 'outcome.', edit.committed if edit else 0)
        raise
    except (OSError, HTTPException, HttpLib2Error):
        fail('WRITE_OUTCOME_UNKNOWN', 'The write connection failed; the '
             'request may have committed.', edit.committed if edit else 0)
    if edit is not None:
        edit.committed += 1
    return result


def revision_changed():
    """Allow entity preflight to reject a stale plan before image staging."""
    if _active.get() is not None and not uses_target_revision():
        raise RevisionRaceError


def insertion_context(context, index):
    """Stage images once per call and translate the plan after safe retries."""
    edit = _active.get()
    if edit is None:
        return context
    if edit.prepared is None:
        edit.prepared = edit.stack.enter_context(context)
        edit.prepared_index = index
        edit.prepared_requests = deepcopy(edit.prepared.requests)
    requests = deepcopy(edit.prepared_requests)
    offset = index - edit.prepared_index

    def shift(value):
        """Translate document indices, retaining row/column/style values."""
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'index', 'startIndex', 'endIndex'}:
                    value[key] += offset
                else:
                    shift(child)
        elif isinstance(value, list):
            for child in value:
                shift(child)

    if isinstance(requests, list):
        shift(requests)
    else:
        requests.start = index
    edit.prepared.requests = requests
    return nullcontext(edit.prepared)


def guarded_edit(function=None, *, append=False):
    """Rerun only an uncommitted plan after a confirmed revision rejection."""
    if function is None:
        return lambda function: guarded_edit(function, append=append)

    @wraps(function)
    def execute(*args, **kwargs):
        """Own call-scoped dependencies and cleanup across bounded attempts."""
        with ExitStack() as stack:
            edit = Edit(stack=stack, append=append,
                        revision_mode=get_settings().write_revision_mode,
                        expected_revision=kwargs.pop(
                            'expected_revision_id', None,
                        ))
            token = _active.set(edit)
            try:
                for attempt in range(MAX_ATTEMPTS):
                    edit.attempt = attempt
                    edit.checked, edit.snapshot = 0, None
                    try:
                        result = function(*args, **kwargs)
                        if attempt and isinstance(result, EditFailedResponse):
                            fail('TARGET_DELETED', 'The original target or '
                                 'heading is no longer resolvable.')
                        break
                    except RevisionRaceError:
                        if edit.committed:
                            fail('PARTIAL_WRITE', 'Earlier stages committed; '
                                 'automatic replay is unsafe.', edit.committed)
                        if edit.expected_revision is not None:
                            fail('EDIT_CONFLICT', 'The caller-provided '
                                 'revision lost its write precondition.')
                        if attempt + 1 == MAX_ATTEMPTS:
                            fail('REVISION_RETRY_EXHAUSTED', 'The document '
                                 'continued changing after three attempts.')
                        log.info('edit=%s status=revision_retry attempt=%s',
                                 function.__name__, attempt + 1)
                        time.sleep(0.05 * (2 ** attempt))
                    except ToolFailureError as error:
                        if edit.committed and error.failure.code not in {
                            'PARTIAL_WRITE', 'WRITE_OUTCOME_UNKNOWN',
                        }:
                            fail('PARTIAL_WRITE', 'Earlier Docs batches '
                                 'committed before a later operation failed.',
                                 edit.committed)
                        if attempt and error.failure.code in {
                            'TEXT_NOT_FOUND', 'HEADING_NOT_FOUND',
                            'OCCURRENCE_NOT_FOUND',
                        }:
                            fail('TARGET_DELETED', 'The original target is '
                                 'no longer resolvable.')
                        raise
                    except (OSError, HTTPException, HttpLib2Error):
                        if edit.committed:
                            fail('WRITE_OUTCOME_UNKNOWN', 'A later external '
                                 'side effect may have committed.',
                                 edit.committed)
                        raise
                    except HttpError as error:
                        if edit.committed:
                            unknown = error.resp.status >= 500  # noqa: PLR2004
                            fail('WRITE_OUTCOME_UNKNOWN' if unknown else
                                 'PARTIAL_WRITE', 'A later API operation '
                                 'failed after completed Docs batches.',
                                 edit.committed)
                        raise
                    except Exception:
                        if edit.committed:
                            fail('PARTIAL_WRITE', 'Earlier stages committed '
                                 'but the operation did not complete.',
                                 edit.committed)
                        raise
            finally:
                _active.reset(token)
        # Image cleanup runs after all attempts; retain its final receipt.
        if edit.prepared is not None and hasattr(
            result, 'temporary_image_cleanup_pending',
        ):
            result.temporary_image_cleanup_pending = (
                edit.prepared.cleanup_pending
            )
        return result
    return execute
