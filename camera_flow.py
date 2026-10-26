"""Camera darts on the controller (M1-12): proposal identity, the pending dart, auto-commit and the event log.

Proposal identity. Vision recomputes its proposal on every stable frame. The same dart against the same
empty-board base keeps one id (key: base generation + label), so the host commits exactly what they
saw: a commit names the id, and the server refuses it (409) if the current proposal has another id.

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
        self.ids = {}                     # (generation, label) -> proposal id
        self.closed = set()               # ids committed or replaced: never pending again
        self.pending = None               # {id, value, multiplier, label, ..., seen_at}

    def observe(self, vision):
        """Update the pending dart from vision's current proposal. Call with vision.lock held."""
        with self.lock:
            if vision.base is not self.base:
                self.base = vision.base
                self.generation += 1
                self.ids.clear()
            proposal = vision.proposal if vision.aligned and vision.fresh() else None
            if proposal is None:
                self.pending = None
                return None
            key = (self.generation, proposal.get('label') or (proposal.get('value'), proposal.get('multiplier')))
            proposal_id = self.ids.setdefault(key, secrets.token_hex(6))
            if proposal_id in self.closed:
                self.pending = None
                return None
            fields = {name: proposal.get(name) for name in PROPOSAL_FIELDS}
            if self.pending is None or self.pending['id'] != proposal_id:
                self.pending = {'id': proposal_id, **fields, 'seen_at': time.monotonic()}
            else:
                self.pending.update(fields)
            return self.pending

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

    def view(self):
        """Pending dart and auto-commit settings for /api/state."""
        with self.lock:
            pending = None
            if self.pending is not None:
                pending = {key: value for key, value in self.pending.items() if key != 'seen_at'}
                if self.auto_commit_enabled():
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
            listener(event)
        return event

    def since(self, seq=0):
        with self.lock:
            return [event for event in self.events if event['seq'] > seq]
