"""Columns, states and transitions of the work list (design: two TSV files, six states).

WORK.tsv holds one row per item with its current state. WORK-events.tsv is append-only: every change, with the time it was
decided (`decided_at`) kept apart from the time it was written down (`ts`).
"""

WORK_COLUMNS = (
    'id', 'title', 'owner', 'priority', 'stage', 'status',
    'start_plan', 'end_plan', 'start_actual', 'end_actual',
    'after', 'wait_for', 'replaced_by', 'locked',
    'evidence', 'decision', 'decided_at', 'decided_by', 'source',
)

EVENT_COLUMNS = (
    'ts', 'decided_at', 'decided_by', 'id', 'event', 'field', 'from', 'to', 'why', 'decision', 'by',
)

STATUSES = ('open', 'doing', 'done', 'hold', 'cancelled', 'replaced')

# allowed next states; done, cancelled and replaced are final
TRANSITIONS = {
    'open': ('doing', 'hold', 'cancelled', 'replaced'),
    'doing': ('done', 'hold', 'cancelled', 'replaced'),
    'hold': ('open', 'doing', 'cancelled', 'replaced'),
    'done': (),
    'cancelled': (),
    'replaced': (),
}

EVENTS = ('add', 'start', 'done', 'change', 'hold', 'resume', 'cancel', 'replace', 'lock', 'decide')

# the eight-column list in use before this tool (WORKLIST.tsv)
LEGACY_COLUMNS = ('id', 'source', 'priority', 'due', 'owner', 'evidence', 'status', 'what')

# legacy column -> new column; every legacy column has exactly one place
LEGACY_TO_WORK = {
    'id': 'id', 'source': 'source', 'priority': 'priority', 'due': 'end_plan',
    'owner': 'owner', 'evidence': 'evidence', 'status': 'status', 'what': 'title',
}

LEGACY_STATUS = {'open': 'open', 'done': 'done', 'dropped': 'cancelled'}
