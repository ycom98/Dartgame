"""Camera darts on the controller (M1-12, M4-01): proposal identity, the pending darts, auto-commit and the event log.

Pending darts (M4-01). Vision can hold up to three pending darts of a turn (vision.pending, oldest first). They
are committed in throw order: a commit, an Accept or a correcting tap always applies to the oldest one (the
head). Each later dart's countdown starts when it becomes the head, so the host gets a full look at it.

Proposal identity. Darts that vision tracks carry their own id. An untracked proposal (set directly, as older
callers and tests do) is matched by tip position (within SAME_DART_MM), so a near-wire dart whose label flips
(S20 <-> S1) stays one dart. The label updates in place, and the countdown restarts once, on the first change,
so the host gets a full look at the new value (QA Q4). A commit names the id (and, from a tap, the label the
host saw); the server refuses it (409) if the head differs.

Auto-commit (owner decision #1). The head is committed after `delay` seconds unless the host corrects it,
accepts it sooner, or auto-commit is paused/off. The server does the commit, so it works with any number of
controllers open.

No OpenCV here: the server imports this module even when camera vision is unavailable.
"""
import secrets
import threading
import time
from collections import deque

DEFAULT_AUTO_COMMIT_SECONDS = 3.0
MAX_EVENTS = 5000
SAME_DART_MM = 5.0
PROPOSAL_FIELDS = ('value', 'multiplier', 'label', 'score', 'x', 'y', 'near_wire', 'confidence', 'check', 'together')


class Conflict(Exception):
    """The request is based on a state that has changed (HTTP 409)."""


class CameraFlow:
    def __init__(self, delay=DEFAULT_AUTO_COMMIT_SECONDS):
        self.lock = threading.Lock()
        self.delay = delay                # seconds; 0 turns auto-commit off
        self.paused = False
        self.base = None                  # the vision turn reference the ids belong to
        self.generation = 0
        self.ids = {}                     # (generation, label) -> id, for proposals without a position
        self.tracks = []                  # [(id, x, y)] untracked darts seen against the current base
        self.closed = set()               # ids committed or replaced: never pending again
        self.pending_darts = []           # [{id, value, multiplier, label, ..., seen_at}], oldest (head) first

    @property
    def pending(self):
        """The head: the pending dart a commit or a correcting tap applies to, or None."""
        return self.pending_darts[0] if self.pending_darts else None

    def observe(self, vision):
        """Update the pending darts from vision's. Call with vision.lock held. Returns the head (or None)."""
        with self.lock:
            turn = getattr(vision, 'turn_base', None)
            turn = vision.base if turn is None else turn
            if turn is not self.base:
                self.base = turn
                self.generation += 1
                self.ids.clear()
                self.tracks.clear()
                self.closed.clear()  # ids are per turn reference: nothing from an older one can come back
            proposals = getattr(vision, 'pending', None)
            if proposals is None:  # a vision object with a single proposal only
                proposals = [vision.proposal] if vision.proposal is not None else []
            proposals = list(proposals) if vision.aligned and vision.fresh() else []
            head = self.pending['id'] if self.pending else None
            known = {dart['id']: dart for dart in self.pending_darts}
            darts = []
            for proposal in proposals:
                proposal_id = proposal.get('id') or self.identify(proposal)
                if proposal_id in self.closed or any(dart['id'] == proposal_id for dart in darts):
                    continue
                fields = {name: proposal.get(name) for name in PROPOSAL_FIELDS}
                dart = known.get(proposal_id)
                if dart is None:
                    dart = {'id': proposal_id, **fields, 'seen_at': time.monotonic(), 'label_changes': 0}
                else:
                    if fields['label'] != dart['label']:
                        dart['label_changes'] += 1
                        if dart['label_changes'] == 1:
                            dart['seen_at'] = time.monotonic()  # one fresh countdown for the new value
                    dart.update(fields)
                darts.append(dart)
            self.pending_darts = darts
            self.promote(head)
            return self.pending

    def promote(self, previous_head):
        """A new head gets a full countdown from now. Call with self.lock held."""
        if self.pending_darts and self.pending_darts[0]['id'] != previous_head:
            self.pending_darts[0]['seen_at'] = time.monotonic()

    def identify(self, proposal):
        """The id of an untracked dart: the nearest earlier tip within SAME_DART_MM, or a new one."""
        x, y = proposal.get('x'), proposal.get('y')
        if x is None or y is None:
            key = (self.generation, proposal.get('label') or (proposal.get('value'), proposal.get('multiplier')))
            return self.ids.setdefault(key, secrets.token_hex(6))
        for index, (track_id, tx, ty) in enumerate(self.tracks):
            if (x - tx) ** 2 + (y - ty) ** 2 <= SAME_DART_MM ** 2:
                self.tracks[index] = (track_id, x, y)
                return track_id
        track_id = secrets.token_hex(6)
        self.tracks.append((track_id, x, y))
        return track_id

    def close(self, proposal_id):
        """A pending dart was committed or replaced by the host's tap."""
        with self.lock:
            self.closed.add(proposal_id)
            head = self.pending['id'] if self.pending else None
            self.pending_darts = [dart for dart in self.pending_darts if dart['id'] != proposal_id]
            self.promote(head)

    def auto_commit_enabled(self):
        return self.delay > 0 and not self.paused

    def due(self):
        """The head if its auto-commit time has come, else None."""
        with self.lock:
            pending = self.pending
            if pending is None or not self.auto_commit_enabled():
                return None
            return dict(pending) if time.monotonic() - pending['seen_at'] >= self.delay else None

    def view(self, turn_over=False):
        """Pending darts and auto-commit settings for /api/state. pending is the head (kept for older
        controllers); pending_darts lists every pending dart, head first. After a bust, win or third dart the
        head cannot be committed: it shows turn_over instead of a countdown."""
        with self.lock:
            darts = []
            for position, dart in enumerate(self.pending_darts):
                shown = {key: value for key, value in dart.items() if key != 'seen_at'}
                shown['turn_over'] = turn_over
                shown['queued'] = position > 0  # waits for the darts before it
                if turn_over or position > 0 or not self.auto_commit_enabled():
                    shown['commit_in'] = None
                else:
                    shown['commit_in'] = round(max(0.0, self.delay - (time.monotonic() - dart['seen_at'])), 2)
                darts.append(shown)
            return {'pending': darts[0] if darts else None, 'pending_darts': darts,
                    'auto_commit': {'seconds': self.delay, 'paused': self.paused, 'enabled': self.delay > 0}}


class EventLog:
    """In-memory match event log (corrections become labels; the recorder writes it to disk, M1-14)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque(maxlen=MAX_EVENTS)
        self.seq = 0
        self.listeners = []

    def add(self, kind, **fields):
        with self.lock:
            self.seq += 1
            event = {'seq': self.seq, 'ts': round(time.time(), 3), 'type': kind, **fields}
            self.events.append(event)
            listeners = list(self.listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception as error:  # a listener (the recorder) must never break a game write (QA Q2)
                print(f'Event listener failed and was skipped: {type(error).__name__}: {error}', flush=True)
        return event

    def since(self, seq=0):
        with self.lock:
            return [event for event in self.events if event['seq'] > seq]
