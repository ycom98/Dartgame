"""Session recording for the board trial (M1-14). Everything stays on this Mac (owner decision #8).

A recording folder holds:
  frames/000123.jpg   every received camera frame, the JPEG bytes exactly as the phone sent them
                      (.png for local file/folder sources, which arrive decoded)
  frames.jsonl        {seq, ts, file} per written frame
  processed.jsonl     {seq, proposal} per frame vision processed (the detection sequence)
  events.jsonl        match events (commits with their source, corrections, filled misses, undo, next, ...)
                      and every top-level vision action (calibrate, align, verify, base resets, ...), each with
                      after_seq: the last frame vision had processed when it happened
  session.json        notes entered on the setup page (mount, lighting, phone settings) and the start state
  start/              the vision calibration at the moment recording started (if it was already calibrated)

tools/make_labels.py turns events.jsonl into labels; tools/replay_recording.py replays processed frames and
vision actions through Vision and checks the detections; tools/contact_sheet.py draws per-throw crops.
Recording stops by itself when the disk has less than MIN_FREE_BYTES free.
"""
import json
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from vision import TARGETS

MIN_FREE_BYTES = 5 * 1024 ** 3
# Vision methods whose top-level calls are logged, so a replay can repeat them in order.
# Calls made inside these are part of them (ingest invalidates on a stale or resized frame) and are not logged.
SILENT_CALLS = ('ingest',)
VISION_ACTIONS = ('begin_calibration', 'cancel_calibration', 'calibrate', 'align', 'verify', 'reset_base',
                  'reset_camera', 'set_mount_side', 'invalidate')


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class Recorder:
    def __init__(self, directory, get_source, min_free_bytes=MIN_FREE_BYTES):
        self.directory = Path(directory)
        self.get_source = get_source
        self.min_free_bytes = min_free_bytes
        self.lock = threading.Lock()          # files and counters
        self.active = False
        self.error = None
        self.started_at = None
        self.stopped_at = None
        self.frames_written = 0
        self.frames_skipped = 0               # fell more than HISTORY_FRAMES behind
        self.bytes_written = 0
        self.last_written_seq = 0
        self.last_processed_seq = None        # the newest frame vision processed
        self.vision = None
        self.depth = 0                        # nesting of instrumented vision calls
        self.thread = None
        self.stop_event = threading.Event()
        self.notes = {}
        self.order = 0
        self.files = {}
        self.on_stop = None                   # called once when recording ends for any reason (server unhooks)

    # ---- lifecycle ---------------------------------------------------------------------
    def start(self, vision=None, notes=None):
        if self.active:
            return self
        free = self.free_bytes()
        if free is not None and free < self.min_free_bytes:
            raise ValueError(f'Not recording: only {free / 1024 ** 3:.1f} GB free (needs 5 GB)')
        try:
            (self.directory / 'frames').mkdir(parents=True, exist_ok=True)
            self.files = {name: open(self.directory / name, 'a', encoding='utf-8')
                          for name in ('frames.jsonl', 'processed.jsonl', 'events.jsonl')}
        except OSError as error:
            self.close_files()
            raise ValueError(f'Cannot record to {self.directory}: {error}') from error
        self.active = True
        self.started_at = time.time()
        self.notes = dict(notes or {})
        source = self.get_source()
        # Include the newest frame already received: vision may be about to process it.
        self.last_written_seq = max(source.seq - 1, 0) if source is not None else 0
        try:
            if vision is not None:
                self.save_start_state(vision)
            self.write_session()
        except OSError as error:
            self.active = False
            self.close_files()
            raise ValueError(f'Cannot record to {self.directory}: {error}') from error
        if vision is not None:
            self.instrument(vision)
        self.event('recording_started', directory=str(self.directory))
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name='recorder', daemon=True)
        self.thread.start()
        return self

    def stop(self, reason=None):
        """Stop recording. Safe to call more than once and from any thread; never raises (QA Q2)."""
        with self.lock:
            if not self.active:
                return
            self.active = False
            try:
                self.order += 1
                stopped = {'order': self.order, 'ts': round(time.time(), 3), 'type': 'recording_stopped',
                           'after_seq': self.last_processed_seq, 'reason': reason}
                self.files['events.jsonl'].write(json.dumps(json_safe(stopped)) + '\n')
            except (OSError, ValueError):
                pass
            self.close_files()
        self.finish(reason)

    def fail(self, reason):
        """A write failed (disk full, drive unplugged...): stop at once and report why. Never raises."""
        with self.lock:
            if not self.active:
                return
            self.active = False
            self.close_files()
        print('Recording stopped: ' + reason, flush=True)
        self.finish(reason)

    def close_files(self):
        for handle in self.files.values():
            try:
                handle.close()
            except OSError:
                pass

    def finish(self, reason):
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(5)
        self.uninstrument()
        self.stopped_at = time.time()
        if reason:
            self.error = reason
        try:
            self.write_session()
        except Exception:  # best effort: the recording has already stopped
            pass
        callback, self.on_stop = self.on_stop, None
        if callback is not None:
            try:
                callback(self)
            except Exception:
                pass

    def free_bytes(self):
        path = self.directory
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def status(self):
        end = self.stopped_at or time.time()
        return {'active': self.active, 'directory': str(self.directory), 'frames': self.frames_written,
                'skipped_frames': self.frames_skipped, 'bytes': self.bytes_written,
                'seconds': round(end - self.started_at, 1) if self.started_at else 0,
                'free_bytes': self.free_bytes(), 'min_free_bytes': self.min_free_bytes, 'error': self.error,
                'notes': self.notes}

    # ---- files -------------------------------------------------------------------------
    def append(self, name, record):
        """Write one line. A write error stops the recording; it never reaches the caller (QA Q2)."""
        failure = None
        with self.lock:
            if not self.active:
                return
            handle = self.files.get(name)
            if handle is None or handle.closed:
                return
            try:
                if name == 'events.jsonl':
                    self.order += 1
                    record = {'order': self.order, **record}
                handle.write(json.dumps(json_safe(record), allow_nan=False) + '\n')
                handle.flush()
            except (OSError, ValueError, TypeError) as error:
                failure = f'Recording stopped: could not write {name} ({error})'
        if failure:
            self.fail(failure)

    def event(self, kind, **fields):
        self.append('events.jsonl', {'ts': round(time.time(), 3), 'type': kind,
                                     'after_seq': self.last_processed_seq, **fields})

    def match_event(self, event):
        """EventLog listener: commits, corrections, misses, undo, next, game..."""
        if self.active:
            self.append('events.jsonl', {**event, 'type': event['type'], 'match_seq': event['seq'],
                                         'after_seq': self.last_processed_seq})

    def write_session(self):
        session = {'started_at': self.started_at, 'stopped_at': self.stopped_at, 'notes': self.notes,
                   'frames': self.frames_written, 'skipped_frames': self.frames_skipped,
                   'bytes': self.bytes_written, 'error': self.error}
        source = self.get_source()
        if source is not None:
            session['source'] = {'kind': source.kind, 'url_redacted': source.description,
                                 'width': source.size[0] if source.size else None,
                                 'height': source.size[1] if source.size else None}
        (self.directory / 'session.json').write_text(json.dumps(json_safe(session), indent=2) + '\n')

    def set_notes(self, notes):
        self.notes = {**self.notes, **notes}
        if self.started_at is not None:
            self.write_session()
            self.event('session_notes', notes=notes)

    def save_start_state(self, vision):
        """Recording may start mid-session: keep what a replay needs to begin from the same state."""
        start = self.directory / 'start'
        if vision.frame is not None:
            start.mkdir(exist_ok=True)
            cv2.imwrite(str(start / 'frame.png'), vision.frame)  # the frame vision holds now
        if vision.reference is None or vision.H is None:
            return
        start.mkdir(exist_ok=True)
        cv2.imwrite(str(start / 'reference.png'), vision.reference)
        if vision.base is not None:
            cv2.imwrite(str(start / 'base.png'), vision.base)
        reference_points = cv2.perspectiveTransform(TARGETS.reshape(1, -1, 2), np.linalg.inv(vision.reference_H))[0]
        state = {'H': vision.H, 'reference_H': vision.reference_H, 'reference_points': reference_points,
                 'aligned': vision.aligned, 'verified': vision.verified(), 'mount_side': vision.mount_side,
                 'camera_hfov': vision.camera_hfov, 'stable': vision.stable, 'version': vision.version,
                 'frame_size': list(vision.frame.shape[:2])
                 if vision.frame is not None else None, 'has_base': vision.base is not None}
        (start / 'vision.json').write_text(json.dumps(json_safe(state), indent=2) + '\n')

    # ---- vision ------------------------------------------------------------------------
    def instrument(self, vision):
        """Log every top-level call of VISION_ACTIONS on this Vision object (instance attributes only)."""
        self.vision = vision
        for name in VISION_ACTIONS + SILENT_CALLS:
            original = getattr(type(vision), name)
            setattr(vision, name, self.wrap(vision, name, original, logged=name in VISION_ACTIONS))

    def uninstrument(self):
        vision, self.vision = self.vision, None
        if vision is not None:
            for name in VISION_ACTIONS + SILENT_CALLS:
                vision.__dict__.pop(name, None)

    def wrap(self, vision, name, original, logged=True):
        def call(*args, **kwargs):
            self.depth += 1
            top = self.depth == 1 and logged
            try:
                result = original(vision, *args, **kwargs)
            except Exception as error:
                if top:
                    self.vision_event(vision, name, args, kwargs, ok=False, error=str(error))
                raise
            finally:
                self.depth -= 1
            if top:
                self.vision_event(vision, name, args, kwargs, ok=True, result=result)
            return result
        return call

    def vision_event(self, vision, name, args, kwargs, ok, error=None, result=None):
        overlay = vision.overlay()
        self.event('vision', action=name, args=list(args), kwargs=kwargs, ok=ok, error=error, result=result,
                   overlay=overlay, version=vision.version, aligned=vision.aligned)

    def on_ingest(self, vision, seq):
        """Worker hook after each processed source frame (vision.lock held)."""
        if not self.active:
            return
        self.last_processed_seq = seq
        proposal = vision.proposal
        self.append('processed.jsonl', {'seq': seq, 'proposal': None if proposal is None else {
            'label': proposal.get('label'), 'x': round(float(proposal['x']), 3), 'y': round(float(proposal['y']), 3)}
            if 'x' in proposal else {'label': proposal.get('label')}})

    # ---- frame writer ------------------------------------------------------------------
    def run(self):
        try:
            self.write_frames_until_stopped()
        except Exception as error:  # the writer must not die silently (QA Q3)
            threading.Thread(target=self.fail, args=(f'Recording stopped: frame writer failed ({error})',),
                             daemon=True).start()

    def write_frames_until_stopped(self):
        last_disk_check = 0.0
        while not self.stop_event.wait(0.02):
            source = self.get_source()
            if source is not None:
                self.write_new_frames(source)
            if time.monotonic() - last_disk_check > 1.0:
                last_disk_check = time.monotonic()
                free = self.free_bytes()
                if free is not None and free < self.min_free_bytes:
                    threading.Thread(target=self.fail, args=(
                        f'Recording stopped: less than {self.min_free_bytes / 1024 ** 3:.0f} GB free on the disk',),
                        daemon=True).start()
                    return
                if self.frames_written and self.frames_written % 150 == 0:
                    self.write_session()

    def write_new_frames(self, source):
        frames = source.frames_after(self.last_written_seq)
        if not frames:
            return
        if frames[0][0] > self.last_written_seq + 1 and self.last_written_seq:
            self.frames_skipped += frames[0][0] - self.last_written_seq - 1
        for seq, timestamp, data, frame in frames:
            if data is not None:
                name = f'{seq:06d}.jpg'
            else:
                name = f'{seq:06d}.png'
                ok, encoded = cv2.imencode('.png', frame)
                data = encoded.tobytes() if ok else b''
            (self.directory / 'frames' / name).write_bytes(data)
            self.frames_written += 1
            self.bytes_written += len(data)
            self.last_written_seq = seq
            self.append('frames.jsonl', {'seq': seq, 'ts': round(timestamp, 3), 'file': 'frames/' + name})
