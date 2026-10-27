"""Camera darts on the controller (M1-12): proposal identity, the pending dart, auto-commit and the event log.

Proposal identity. Vision recomputes its proposal on every stable frame. The same dart against the same
empty-board base keeps one id: it is matched by tip position (within SAME_DART_MM), so a near-wire dart whose
label flips (S20 <-> S1) stays one dart. The label updates in place, and the countdown restarts once, on the
first change, so the host gets a full look at the new value (QA Q4). A commit names the id (and, from a
tap, the label the host saw); the server refuses it (409) if the current proposal differs.

Auto-commit (owner decision #1). A pending camera dart is committed after `delay` seconds unless the
host corrects it, accepts it sooner, or auto-commit is paused/off. The server does the commit, so it
works with any number of controllers open.

No OpenCV here: the server imports this module even when camera vision is unavailable.
"""
import secrets
import threading
import time
from collections import deque

DEFAULT_AUTO_COMMIT_SECONDS = 3.0
MAX_EVENTS = 5000
SAME_DART_MM = 5.0
PROPOSAL_FIELDS = ('value', 'multiplier', 'label', 'score', 'x', 'y', 'near_wire', 'confidence')


class Conflict(Exception):
    """The request is based on a state that has changed (HTTP 409)."""


class CameraFlow:
    def __init__(self, delay=DEFAULT_AUTO_COMMIT_SECONDS):
        self.lock = threading.Lock()
        self.delay = delay                # seconds; 0 turns auto-commit off
        self.paused = False
        self.base = None                  # the vision base image the ids belong to
        self.generation = 0
        self.ids = {}                     # (generation, label) -> id, for proposals without a position
        self.tracks = []                  # [(id, x, y)] darts seen against the current base
        self.closed = set()               # ids committed or replaced: never pending again
        self.pending = None               # {id, value, multiplier, label, ..., seen_at}

    def observe(self, vision):
        """Update the pending dart from vision's current proposal. Call with vision.lock held."""
        with self.lock:
            if vision.base is not self.base:
                self.base = vision.base
                self.generation += 1
                self.ids.clear()
                self.tracks.clear()
                self.closed.clear()  # ids are per base: nothing from an older base can come back
            proposal = vision.proposal if vision.aligned and vision.fresh() else None
            if proposal is None:
                self.pending = None
                return None
            proposal_id = self.identify(proposal)
            if proposal_id in self.closed:
                self.pending = None
                return None
            fields = {name: proposal.get(name) for name in PROPOSAL_FIELDS}
            if self.pending is None or self.pending['id'] != proposal_id:
                self.pending = {'id': proposal_id, **fields, 'seen_at': time.monotonic(), 'label_changes': 0}
            else:
                if fields['label'] != self.pending['label']:
                    self.pending['label_changes'] += 1
                    if self.pending['label_changes'] == 1:
                        self.pending['seen_at'] = time.monotonic()  # one fresh countdown for the new value
                self.pending.update(fields)
            return self.pending

    def identify(self, proposal):
        """The id of this detected dart: the nearest earlier tip within SAME_DART_MM, or a new one."""
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
            if self.pending is not None and self.pending['id'] == proposal_id:
                self.pending = None

    def auto_commit_enabled(self):
        return self.delay > 0 and not self.paused

    def due(self):
        """The pending dart if its auto-commit time has come, else None."""
        with self.lock:
            pending = self.pending
            if pending is None or not self.auto_commit_enabled():
                return None
            return dict(pending) if time.monotonic() - pending['seen_at'] >= self.delay else None

    def view(self, turn_over=False):
        """Pending dart and auto-commit settings for /api/state. After a bust, win or third dart the pending
        dart cannot be committed: it shows turn_over instead of a countdown."""
        with self.lock:
            pending = None
            if self.pending is not None:
                pending = {key: value for key, value in self.pending.items() if key != 'seen_at'}
                pending['turn_over'] = turn_over
                if turn_over:
                    pending['commit_in'] = None
                elif self.auto_commit_enabled():
                    pending['commit_in'] = round(max(0.0, self.delay - (time.monotonic() - self.pending['seen_at'])), 2)
                else:
                    pending['commit_in'] = None
            return {'pending': pending, 'auto_commit': {'seconds': self.delay, 'paused': self.paused,
                                                         'enabled': self.delay > 0}}


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
