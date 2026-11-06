"""Frozen resource-bounded Study 1 corpus: five pilot and twenty main cases.

Requests deliberately mix Russian and English. Gold trajectories are examples,
not exclusive solutions: grading compares resulting native state and protected
content, accepting equivalent operations. Pilot and main scenario families are
disjoint. No scenario contains real user content.
"""

from copy import deepcopy

# Natural-language corpus entries retain complete phrases for review.
# ruff: noqa: E501


def heading(text, identifier, level='HEADING_1'):
    """Describe a native body heading with a stable synthetic ID."""
    return {'text': text, 'heading_id': identifier, 'level': level}


def tab(identifier, title, *paragraphs):
    """Create an independently indexed tab with explicit paragraph boundaries."""
    return {'id': identifier, 'title': title,
            'paragraphs': [({'text': p} if isinstance(p, str) else p)
                           for p in paragraphs]}


def operation(tool, **arguments):
    """Make one baseline trajectory action for native-state reference grading."""
    return {'tool': tool, 'arguments': {'doc_id': 'study_fixture', **arguments}}


def scenario(identifier, stratum, family, language, request, tabs, oracle, *,  # noqa: PLR0917
             comments=(), clarification=None, decision='action', answer=None,
             ordered=False):
    """Keep input state, user intent, scripted clarification and gold separate."""
    return {
        'id': identifier, 'stratum': stratum, 'family': family,
        'language': language, 'request': request,
        'fixture': {'document_id': 'study_fixture', 'title': family,
                    'tabs': tabs, 'comments': list(comments)},
        'oracle': oracle, 'clarification': clarification,
        'expected_decision': decision, 'answer_contains': answer,
        'ordered': ordered,
    }


PILOT = [
    scenario('p1', 'insertion', 'single-tab-meeting-literal', 'ru',
             'Добавь в конец документа буквальный текст **Meeting closed**. '
             'Звёздочки должны остаться видимыми.',
             [tab('t.main', 'Minutes', 'Opening', 'Decisions')],
             [operation('docs_append', text='**Meeting closed**', rich=False)]),
    scenario('p2', 'status', 'single-thread-terminology', 'en',
             'Resolve the terminology review thread. Do not add any reply text.',
             [tab('t.main', 'Glossary', 'Terminology notes')],
             [operation('docs_resolve_comment', comment_id='c.term')],
             comments=[{'id': 'c.term', 'text': 'Terminology review',
                        'resolved': False}]),
    scenario('p3', 'multi_step', 'handover-before-and-close', 'ru',
             'Сначала вставь отдельный абзац Ready before handover перед '
             'абзацем Handover checkpoint. Затем закрой комментарий '
             'Handover review без текста ответа.',
             [tab('t.main', 'Handover', 'Handover checkpoint', 'Protected tail')],
             [operation('docs_insert_before', anchor='Handover checkpoint',
                        text='Ready before handover'),
              operation('docs_resolve_comment', comment_id='c.handover')],
             comments=[{'id': 'c.handover', 'text': 'Handover review',
                        'resolved': False}], ordered=True),
    scenario('p4', 'ambiguity', 'ambiguous-wording-threads', 'en',
             'Resolve the wording review comment. Ask which one if ambiguous.',
             [tab('t.main', 'Review', 'Summary text', 'Appendix text')],
             [operation('docs_resolve_comment', comment_id='c.appendix')],
             comments=[{'id': 'c.summary', 'text': 'Wording review: summary',
                        'resolved': False},
                       {'id': 'c.appendix', 'text': 'Wording review: appendix',
                        'resolved': False}],
             clarification='I mean the appendix wording review.',
             decision='clarify'),
    scenario('p5', 'control', 'unique-unscoped-label-replacement', 'en',
             'Replace the word Draft with Final in the document. '
             'Keep all other content unchanged.',
             [tab('t.main', 'Status', 'Release label: Draft', 'Protected text')],
             [operation('docs_search_replace', find='Draft', replace='Final')]),
]


MAIN = [
    scenario('m01', 'insertion', 'onboarding-other-tab-literal', 'ru',
             'В конец вкладки Checklist добавь буквальный текст [done](local). '
             'Это обычный текст, а не ссылка. Вкладку Welcome не меняй.',
             [tab('t.main', 'Welcome', 'Protected welcome'),
              tab('t.check', 'Checklist', 'Account ready', 'Access checked')],
             [operation('docs_append', tab_id='t.check',
                        text='[done](local)', rich=False)]),
    scenario('m02', 'insertion', 'shipment-nested-repeated-anchor', 'en',
             'In the International subsection, insert a paragraph Customs '
             'cleared before its Checkpoint paragraph. Leave Domestic alone.',
             [tab('t.main', 'Shipping',
                  heading('Domestic', 'h.domestic'), 'Checkpoint',
                  heading('International', 'h.international'),
                  heading('Air freight', 'h.air', 'HEADING_2'),
                  'Checkpoint', 'Cargo 😀 ready')],
             [operation('docs_insert_before', heading_id='h.international',
                        anchor='Checkpoint', text='Customs cleared')]),
    scenario('m03', 'insertion', 'lab-emoji-after-paragraph', 'ru',
             'Сразу после абзаца Sample 🧪 accepted добавь отдельный абзац '
             'Proceed to analysis. Исходный абзац сохрани.',
             [tab('t.main', 'Lab', 'Intake', 'Sample 🧪 accepted', 'Queue')],
             [operation('docs_insert_after', anchor='Sample 🧪 accepted',
                        text='Proceed to analysis')]),
    scenario('m04', 'insertion', 'launch-bold-end-of-tab', 'en',
             'At the end of the Launch tab add a paragraph Ready for launch '
             'with the entire paragraph text in bold. Preserve Archive.',
             [tab('t.main', 'Archive', 'Protected archived notes'),
              tab('t.launch', 'Launch', heading('Go live', 'h.live'),
                  'Final checks complete')],
             [operation('docs_append', tab_id='t.launch',
                        text='**Ready for launch**')]),
    scenario('m05', 'insertion', 'training-subtree-boundary', 'ru',
             'После всего раздела Exercises, включая вложенный раздел Answers, '
             'но перед разделом Reading добавь абзац Practice complete.',
             [tab('t.main', 'Training', heading('Exercises', 'h.exercises'),
                  'Problem statement', heading('Answers', 'h.answers',
                                                'HEADING_2'),
                  'Solution', heading('Reading', 'h.reading'), 'Book list')],
             [operation('docs_insert_at_heading', heading_id='h.exercises',
                        position='after_subtree', text='Practice complete')]),
    scenario('m06', 'insertion', 'incident-scoped-before-literal', 'en',
             'Before the Evidence marker paragraph in Incident B insert the '
             'literal paragraph # Not a heading. Do not modify Incident A.',
             [tab('t.main', 'Incidents', heading('Incident A', 'h.a'),
                  'Evidence marker', heading('Incident B', 'h.b'),
                  'Evidence marker', 'End')],
             [operation('docs_insert_before', heading_id='h.b',
                        anchor='Evidence marker', text='# Not a heading',
                        rich=False)]),
    scenario('m07', 'status', 'design-similar-thread-disambiguation', 'en',
             'Resolve only the button contrast review. Leave the link contrast '
             'review open. Do not add closing text.',
             [tab('t.main', 'Design', 'Button and link samples')],
             [operation('docs_resolve_comment', comment_id='c.button')],
             comments=[{'id': 'c.button', 'text': 'Button contrast review',
                        'resolved': False},
                       {'id': 'c.link', 'text': 'Link contrast review',
                        'resolved': False}]),
    scenario('m08', 'status', 'contract-reopen-with-action-text', 'ru',
             'Открой заново закрытое обсуждение Payment terms и добавь к '
             'действию открытия текст Need legal review. Остальные не меняй.',
             [tab('t.main', 'Contract', 'Payment terms', 'Delivery terms')],
             [operation('docs_reopen_comment', comment_id='c.payment',
                        reply='Need legal review')],
             comments=[{'id': 'c.payment', 'text': 'Payment terms',
                        'resolved': True},
                       {'id': 'c.delivery', 'text': 'Delivery terms',
                        'resolved': True}]),
    scenario('m09', 'status', 'manuscript-close-with-resolution-note', 'en',
             'Close the Citation source discussion with closing text '
             'Verified against the original. Do not post a separate reply.',
             [tab('t.main', 'Manuscript', 'Citation [1]')],
             [operation('docs_resolve_comment', comment_id='c.citation',
                        reply='Verified against the original')],
             comments=[{'id': 'c.citation', 'text': 'Citation source',
                        'resolved': False}]),
    scenario('m10', 'status', 'budget-already-closed-noop', 'ru',
             'Закрой обсуждение Budget approved, только если оно ещё открыто. '
             'Если уже закрыто, ничего не записывай и сообщи об этом.',
             [tab('t.main', 'Budget', 'Approved total')], [],
             comments=[{'id': 'c.budget', 'text': 'Budget approved',
                        'resolved': True}], decision='noop'),
    scenario('m11', 'multi_step', 'runbook-insert-after-and-reopen', 'en',
             'First add a paragraph Rollback tested after the Recovery trigger '
             'paragraph in Operations. Then reopen Rollback review without '
             'additional reply text. Leave Reference unchanged.',
             [tab('t.main', 'Reference', 'Protected reference'),
              tab('t.ops', 'Operations', heading('Recovery', 'h.recovery'),
                  'Recovery trigger', 'Emergency contacts')],
             [operation('docs_insert_after', tab_id='t.ops',
                        anchor='Recovery trigger', text='Rollback tested'),
              operation('docs_reopen_comment', comment_id='c.rollback')],
             comments=[{'id': 'c.rollback', 'text': 'Rollback review',
                        'resolved': True}], ordered=True),
    scenario('m12', 'multi_step', 'procurement-close-before-append', 'ru',
             'Сначала закрой обсуждение Supplier confirmed без ответа. Затем '
             'в конец вкладки Orders добавь абзац Purchase released.',
             [tab('t.main', 'Orders', 'Order 42', 'Supplier confirmation')],
             [operation('docs_resolve_comment', comment_id='c.supplier'),
              operation('docs_append', text='Purchase released')],
             comments=[{'id': 'c.supplier', 'text': 'Supplier confirmed',
                        'resolved': False}], ordered=True),
    scenario('m13', 'multi_step', 'release-replace-and-annotated-close', 'en',
             'Change Release status: Pending to Release status: Accepted. '
             'Then resolve Acceptance review with closing text QA approved.',
             [tab('t.main', 'Release', 'Release status: Pending', 'Build 37')],
             [operation('docs_search_replace', find='Release status: Pending',
                        replace='Release status: Accepted'),
              operation('docs_resolve_comment', comment_id='c.acceptance',
                        reply='QA approved')],
             comments=[{'id': 'c.acceptance', 'text': 'Acceptance review',
                        'resolved': False}], ordered=True),
    scenario('m14', 'multi_step', 'audit-conditional-insert-and-close', 'ru',
             'Если в разделе Findings ещё нет текста Audit ready, добавь '
             'отдельный абзац Audit ready после абзаца Findings summary. '
             'Затем закрой обсуждение Findings sign-off без ответа.',
             [tab('t.main', 'Audit', heading('Findings', 'h.findings'),
                  'Findings summary', heading('Appendix', 'h.appendix'),
                  'Audit ready')],
             [operation('docs_insert_after', heading_id='h.findings',
                        anchor='Findings summary', text='Audit ready'),
              operation('docs_resolve_comment', comment_id='c.findings')],
             comments=[{'id': 'c.findings', 'text': 'Findings sign-off',
                        'resolved': False}], ordered=True),
    scenario('m15', 'ambiguity', 'duplicate-status-paragraphs', 'en',
             'Insert a paragraph Approved before Status pending. If there is '
             'more than one possible target, ask me which section.',
             [tab('t.main', 'Workstreams', heading('Alpha', 'h.alpha'),
                  'Status pending', heading('Beta', 'h.beta'),
                  'Status pending')],
             [operation('docs_insert_before', heading_id='h.beta',
                        anchor='Status pending', text='Approved')],
             clarification='Use the Beta section.', decision='clarify'),
    scenario('m16', 'ambiguity', 'heading-versus-body-boundary', 'ru',
             'Добавь абзац Review complete после Reviews. Если неочевидно, '
             'имеется в виду раздел или обычный абзац, сначала уточни.',
             [tab('t.main', 'Review notes', heading('Reviews', 'h.reviews'),
                  'Primary findings', heading('Details', 'h.details', 'HEADING_2'),
                  'Supplement', heading('Notes', 'h.notes'), 'Reviews')],
             [operation('docs_insert_at_heading', heading_id='h.reviews',
                        position='after_subtree', text='Review complete')],
             clarification='После всего раздела Reviews вместе с вложенным Details.',
             decision='clarify'),
    scenario('m17', 'ambiguity', 'absent-optional-archive-target', 'en',
             'If there is an Archived heading, insert Archive verified after '
             'its complete subtree. If it is absent, leave everything unchanged '
             'and tell me it was not found.',
             [tab('t.main', 'Retention', heading('Active', 'h.active'),
                  'Current records', heading('Planned', 'h.planned'),
                  'Future records')], [], decision='noop'),
    scenario('m18', 'control', 'bounded-delivery-read', 'ru',
             'Прочитай только раздел Delivery и верни его строку с номером '
             'партии дословно. Документ не изменяй.',
             [tab('t.main', 'Warehouse', heading('Storage', 'h.storage'),
                  'Protected stock list', heading('Delivery', 'h.delivery'),
                  'Batch: WH-7294-Z')], [], decision='noop',
             answer='Batch: WH-7294-Z'),
    scenario('m19', 'control', 'scoped-repeated-literal-replacement', 'en',
             'In the South section replace only its first Pending with Ready. '
             'Keep North and the second Pending in South unchanged.',
             [tab('t.main', 'Regions', heading('North', 'h.north'),
                  'Pending', heading('South', 'h.south'),
                  'Pending', 'Pending')],
             [operation('docs_search_replace', find='Pending', replace='Ready',
                        occurrence=1, heading_id='h.south')]),
    scenario('m20', 'control', 'matched-text-blue-color-only', 'ru',
             'Во вкладке Signals сделай текст Stable signal синим цветом '
             'Google blue. Остальной текст и фон оставь без изменений.',
             [tab('t.main', 'Overview', 'Protected overview'),
              tab('t.signals', 'Signals', 'Stable signal', 'Protected signal')],
             [operation('docs_format_text', tab_id='t.signals',
                        anchor_text='Stable signal', foreground_color='blue')]),
]


def corpus(stage):
    """Return fresh corpus values so preparation cannot modify frozen cases."""
    if stage not in {'pilot', 'main'}:
        raise ValueError('Unknown study stage')
    return deepcopy(PILOT if stage == 'pilot' else MAIN)
