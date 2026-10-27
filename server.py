#!/usr/bin/env python3
"""Dart Room server: a private home-LAN app. No cloud services or image retention."""
import argparse
import json
import os
import ipaddress
import shutil
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from core import Game

ROOT = Path(__file__).resolve().parent
# Where --https keeps its local CA and certificate (.local/). Tests point this at a temporary folder.
HTTPS_ROOT = ROOT
try:
    from vision import Vision
    vision = Vision()
    vision_error = None
except ImportError:
    vision = None
    vision_error = 'Camera vision unavailable: install requirements.txt. Manual game still works.'
from vision_worker import ACTION_TIMEOUT_SECONDS, VisionWorker, WorkerBusy
from camera_flow import DEFAULT_AUTO_COMMIT_SECONDS, CameraFlow, Conflict, EventLog
try:
    import camera_source
    import recorder as recording
except ImportError:  # OpenCV missing: manual games still work
    camera_source = recording = None
# Session recordings (M1-14) stay on this Mac, under a gitignored folder unless --record names another.
RECORDINGS_ROOT = ROOT / 'recordings'
recorder = None

# All Vision work runs on this one thread (M1-06). It looks up the module-level `vision` each time.
worker = VisionWorker(lambda: vision)
# After every published vision state, update the pending camera dart of the current app (M1-12).
worker.after_publish = lambda v: app.flow.observe(v)
worker.after_ingest = lambda v, seq: recorder.on_ingest(v, seq) if recorder is not None else None
AUTO_COMMIT_SECONDS = DEFAULT_AUTO_COMMIT_SECONDS

# Lock order (M1-06): app.game_lock protects only the game, revision and camera_game. vision.lock may be
# held while taking app.game_lock (camera-proposal commit); app.game_lock is never held while taking
# vision.lock or waiting for the vision worker.
GAME_PATHS = ('/api/game', '/api/throw', '/api/next', '/api/undo')

def vision_state():
    """Latest vision state without waiting for the vision lock."""
    if vision is None:
        return {'fresh':False,'aligned':False,'verified':False,'phase':'unavailable','message':vision_error}
    return {**vision.current_state(), 'source':worker.source_status()}

source_switch_lock = threading.Lock()  # one source switch at a time (QA D8)

def set_camera_source(uri):
    """Pull frames from uri (see camera_source.py), or stop pulling when uri is None. Raises ValueError."""
    with source_switch_lock:
        return switch_camera_source(uri)

def switch_camera_source(uri):
    if uri is None:
        worker.set_source(None); return None
    if vision is None or camera_source is None: raise ValueError(vision_error)
    source = camera_source.make_source(uri)
    def source_changed(v):
        # A new source may be a different camera or view: keep the calibration, require a fresh alignment check.
        if v.aligned or v.verified_version is not None:
            v.invalidate('Camera source changed. Check / realign board, then verify the overlay.')
        else:
            v.message = 'Connecting to ' + source.description
    worker.call(source_changed)
    worker.set_source(source)
    return source

CALIBRATION_DIR = None  # where the calibration is saved (M1-16); main() sets it next to the match file

def save_calibration():
    if CALIBRATION_DIR is None or vision is None: return
    import persistence
    try: worker.call(lambda v: persistence.save_calibration(v, CALIBRATION_DIR))
    except (OSError, ValueError, WorkerBusy) as error: print('Could not save the calibration: '+str(error), flush=True)

def restore_calibration():
    """Load the saved calibration, then check the board position once the camera sends frames (M1-16).
    A match gives the overlay-review phase: one tap on Verify and the camera is ready again."""
    import persistence
    try: data = worker.call(lambda v: persistence.load_calibration(v, CALIBRATION_DIR))
    except (OSError, ValueError, KeyError) as error:
        print('Saved calibration not used: '+str(error), flush=True); return
    if data is None: return
    print('Saved calibration loaded; the board position is checked when the camera connects.', flush=True)
    def check_when_camera_ready():
        while not vision.current_state()['fresh']: time.sleep(0.2)
        time.sleep(0.5)  # a few frames, so the image has settled
        def realign(v):
            if v.frame.shape[:2] != v.reference.shape[:2]:
                v.message = 'Camera resolution changed since the saved calibration. Set four points again.'
                return False
            try: v.align()
            except ValueError as error:
                v.message = 'Saved calibration does not match the board (moved?): set four points again. ' + str(error)
                return False
            v.message = 'Board position matches the saved calibration. Check the live overlay, then verify.'
            return True
        try:
            ok = worker.call(realign)
            print('Board position check after restart: '+('matches the saved calibration' if ok else 'failed'), flush=True)
        except Exception as error:
            print('Board position check after restart failed: '+str(error), flush=True)
    threading.Thread(target=check_when_camera_ready, name='calibration-recheck', daemon=True).start()

def recording_state():
    """Recording status for /api/state. Free disk space is included only while recording, so an idle state
    does not change on its own (the setup page reads it from /api/record/disk)."""
    if recorder is not None and recorder.active: return recorder.status()
    last = recorder.status() if recorder is not None else {}
    return {'active':False, 'directory':last.get('directory'), 'error':last.get('error'), 'root':str(RECORDINGS_ROOT)}

def free_disk_bytes():
    try: return shutil.disk_usage(RECORDINGS_ROOT if RECORDINGS_ROOT.exists() else ROOT).free
    except OSError: return None

def start_recording(directory=None, notes=None):
    """Start recording the stream and event log (M1-14). Raises ValueError."""
    global recorder
    if vision is None or recording is None: raise ValueError(vision_error)
    if recorder is not None and recorder.active: return recorder
    directory = Path(directory) if directory else RECORDINGS_ROOT / time.strftime('%Y%m%d-%H%M%S')
    candidate = recording.Recorder(directory, lambda: worker.source)
    worker.call(lambda v: candidate.start(v, notes))  # instruments vision under its lock
    app.events.listeners.append(candidate.match_event)
    recorder = candidate
    return recorder

def stop_recording(reason=None):
    if recorder is None or not recorder.active: return
    worker.call(lambda v: recorder.stop(reason))
    if recorder.match_event in app.events.listeners: app.events.listeners.remove(recorder.match_event)

class App:
    def __init__(self, token=None):
        self.token = token or secrets.token_urlsafe(24)
        self.display_token = secrets.token_urlsafe(24)
        self.game = None; self.game_lock = threading.RLock(); self.camera_game = False; self.revision = 0
        self.flow = CameraFlow(AUTO_COMMIT_SECONDS)  # pending camera dart and auto-commit (M1-12)
        self.events = EventLog()
        self.store = None  # persistence.MatchStore when the match is saved to disk (M1-16; main() sets it)
    def bump(self):
        """The match changed: new revision, saved to disk. Call with game_lock held."""
        self.revision += 1
        if self.store is not None: self.store.save(self)
    def game_state(self):
        with self.game_lock:
            return {'game':self.game.snapshot() if self.game else None, 'revision':self.revision,
                    'camera_game':self.camera_game, 'display':self.game.hints() if self.game else None}
    def state(self):
        game = self.game_state()
        return {'game':game['game'], 'revision':game['revision'],
                'presentation_path':'/play?t='+self.display_token,
                'display':game['display'],  # the game mode's layout hints for /play and /control (M1-15)
                'vision':vision_state(), 'camera_game':game['camera_game'], 'camera':self.flow.view(),
                'recording':recording_state()}

app = App()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # Never log pairing tokens or images.
    def reply(self, value, status=200):
        data = json.dumps(value, allow_nan=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def authenticated(self, display=False):
        supplied = self.headers.get('Authorization','').removeprefix('Bearer ')
        return supplied.isascii() and (secrets.compare_digest(supplied, app.token) or
                (display and secrets.compare_digest(supplied, app.display_token)))
    def do_GET(self):
        path = urlparse(self.path).path
        public = {'/play':'presentation.html', '/control':'control.html', '/showcase':'showcase.html',
                  **{'/static/'+name:name for name in ('presentation.css','presentation.js','control.js','showcase.js',
                                                       'setup.css','setup.js','board.js')},
                  '/':'index.html', '/phone':'index.html'}  # /phone: old links open the setup page
        if path in public:
            content = (ROOT/'static'/public[path]).read_bytes()
            mime = 'text/css' if path.endswith('.css') else 'text/javascript' if path.endswith('.js') else 'text/html'
            self.send_response(200); self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(content)))
            self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers(); self.wfile.write(content); return
        if not self.authenticated(display=path == '/api/state'): return self.reply({'error':'Open the complete pairing link printed in Terminal'},401)
        if path == '/api/state': return self.reply(app.state())
        if path == '/api/modes':
            import modes
            return self.reply({'modes':modes.catalog()})
        if path == '/api/record/disk':
            return self.reply({'free_bytes':free_disk_bytes(), 'min_free_bytes':recording.MIN_FREE_BYTES if recording else None})
        if path == '/api/events':
            try: since = int(parse_qs(urlparse(self.path).query).get('since',['0'])[0])
            except ValueError: return self.reply({'error':'since must be an integer'},400)
            return self.reply({'events':app.events.since(since)})
        if path in ('/api/image', '/api/calibration/image'):
            if vision is None or vision.frame is None: return self.reply({'error':'No phone image yet'},404)
            frame = vision.frame  # ingest replaces the array, never edits it, so this reference is safe to encode
            if path == '/api/calibration/image':
                snapshot_id = parse_qs(urlparse(self.path).query).get('id',[None])[0]
                try: frame = worker.call(lambda v: v.snapshot_frame(snapshot_id))  # 10 s limit, 503 (QA D7)
                except ValueError as error: return self.reply({'error':str(error)},400)
                except WorkerBusy as error: return self.reply({'error':str(error)},503)
            import cv2
            ok,data = cv2.imencode('.jpg',frame)  # outside both locks
            if not ok: return self.reply({'error':'Camera image could not be encoded'},500)
            payload = data.tobytes()
            self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        self.reply({'error':'Not found'},404)
    def do_POST(self):
        if not self.authenticated(): return self.reply({'error':'Unauthorized'},401)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 2_000_000: return self.reply({'error':'Request must be under 2 MB'},413)
            raw = self.rfile.read(length)
            path = urlparse(self.path).path
            if path == '/api/frame':  # push path, kept for tests only; no revision
                if vision is None: raise ValueError(vision_error)
                worker.call(lambda v: v.ingest(raw)); return self.reply({'ok':True})
            body = json.loads(raw)
            if not isinstance(body,dict): raise ValueError('Expected a JSON object')
            # M1-10: every write names the revision it was based on.
            if 'expected_revision' not in body or type(body['expected_revision']) is not int:
                raise ValueError('expected_revision (an integer) is required')
            with app.game_lock:
                if body['expected_revision'] != app.revision:
                    raise Conflict('Match changed on another controller. Review the current turn.')
            result = self.route_post(path, body)
            if result is NOT_FOUND: return self.reply({'error':'Not found'},404)
            self.reply({**app.state(), **(result or {})})
        except Conflict as error:
            self.reply({**app.state(), 'error':str(error)},409)
        except WorkerBusy as error:
            self.reply({'error':str(error)},503)
        except (ValueError,TypeError,KeyError,OverflowError) as error:
            self.reply({'error':str(error)},400)
        except Exception:
            self.reply({'error':'Request failed. Check camera connection and calibration.'},500)
    def route_post(self, path, body):
        """Handle one write. Returns extra reply fields, None, or NOT_FOUND."""
        if path in GAME_PATHS or path in ('/api/correct', '/api/turn/fill_misses'):
            return game_write(path, body)
        if path == '/api/camera/source':
            # Disconnecting needs an explicit "uri": null; a missing field is an error (QA D5).
            if 'uri' not in body: raise ValueError('uri is required (null disconnects the camera)')
            uri = body['uri']
            if uri is not None and not isinstance(uri,str): raise ValueError('uri must be a string or null')
            set_camera_source(uri)
            with app.game_lock: app.bump()  # other controllers see the change (QA N2)
            return None
        if path == '/api/camera/test': return {'test':test_camera_source(body.get('uri'))}
        if path == '/api/record':
            enabled = body.get('enabled')
            if type(enabled) is not bool: raise ValueError('enabled must be true or false')
            if enabled: start_recording(notes=clean_notes(body.get('notes', {})))
            else: stop_recording()
            return None
        if path == '/api/record/notes':
            notes = clean_notes(body.get('notes'))
            if recorder is None: raise ValueError('Start a recording first')
            recorder.set_notes(notes)
            return None
        if path == '/api/camera/auto_commit':
            paused, seconds = body.get('paused', app.flow.paused), body.get('seconds', app.flow.delay)
            if type(paused) is not bool: raise ValueError('paused must be true or false')
            if type(seconds) not in (int, float) or not 0 <= seconds <= 30: raise ValueError('seconds must be 0-30')
            with app.game_lock:
                app.flow.paused, app.flow.delay = paused, float(seconds)
                app.bump()
            app.events.add('auto_commit', paused=paused, seconds=float(seconds))
            return None
        if path == '/api/camera/mount_side':
            if vision is None: raise ValueError(vision_error)
            side = body.get('mount_side')
            worker.call(lambda v: v.set_mount_side(side))
            save_calibration()
            return None
        actions = {
            '/api/camera/reset': lambda v: v.reset_camera(),
            '/api/calibration/start': lambda v: v.begin_calibration(),
            '/api/calibration/cancel': lambda v: v.cancel_calibration(),
            '/api/calibrate': lambda v: v.calibrate(body.get('points'),body['snapshot_id']),
            '/api/verify': lambda v: v.verify(body.get('version')),
            '/api/align': lambda v: v.align(),
            '/api/baseline': lambda v: v.reset_base(),
        }
        if path not in actions: return NOT_FOUND
        if vision is None: raise ValueError(vision_error)
        if path == '/api/calibrate' and not isinstance(body.get('snapshot_id'),str):
            raise ValueError('Select Set four points to capture a calibration image first')
        result = worker.call(actions[path])
        if path in ('/api/calibrate', '/api/align', '/api/verify'): save_calibration()
        return {'snapshot':result} if path == '/api/calibration/start' else None

NOT_FOUND = object()

def clean_notes(notes):
    """Session notes from the setup page: a few short text fields."""
    if not isinstance(notes, dict) or len(notes) > 10: raise ValueError('notes must be an object with up to 10 fields')
    for key, value in notes.items():
        if not isinstance(value, str) or len(key) > 40 or len(value) > 500:
            raise ValueError('each note must be text up to 500 characters')
    return notes

def game_write(path, body):
    """Game writes. Lock order: vision.lock (camera commits only), then app.game_lock; never the reverse."""
    if path == '/api/game':
        camera = body.get('camera', True)
        if type(camera) is not bool: raise ValueError('camera must be boolean')
        # {mode, options} (M1-15); the legacy top-level start / double_out still make an x01 game.
        mode = body.get('mode', 'x01')
        if not isinstance(mode, str): raise ValueError('mode must be a string')
        candidate = Game(body.get('names'), body.get('start',301), body.get('double_out',False),
                         mode=mode, options=body.get('options'))
        if camera:
            if vision is None: raise ValueError('Complete calibration and verify the live overlay before starting')
            worker.call(recheck_before_camera_game)
        with app.game_lock:
            check_revision(body)
            app.game = candidate; app.camera_game = camera; app.bump()
            app.events.add('game', names=candidate.data['names'], mode=candidate.mode.id,
                           options=candidate.options, camera=camera)
        if vision is not None: worker.submit(reset_base_if_ready)
        return None
    if path == '/api/throw' and 'proposal' in body:
        raise ValueError('Confirm a camera dart with its proposal_id')
    if path == '/api/throw' and ('proposal_id' in body or 'replaces_proposal_id' in body):
        accept = 'proposal_id' in body
        proposal_id = body['proposal_id'] if accept else body['replaces_proposal_id']
        if not isinstance(proposal_id,str): raise ValueError('proposal id must be a string')
        replacement = None if accept else (body.get('value'), body.get('multiplier',1))
        commit_camera_dart(proposal_id, 'accepted' if accept else 'corrected', replacement, body['expected_revision'])
        return None
    with app.game_lock:
        check_revision(body)
        if app.game is None: raise ValueError('Start a game first')
        g = app.game
        before = g.snapshot()
        if path == '/api/throw':
            g.throw(body.get('value'),body.get('multiplier',1))
            app.events.add('commit', source='manual', dart=last_dart(g), proposal=None, **turn_info(before))
        elif path == '/api/next':
            # The published state, as /api/state shows it: no refusal while the UI says Ready (QA D3).
            if app.camera_game and (vision is None or not vision.current_state()['verified']):
                raise ValueError('Reconnect camera, align board and verify the overlay before next turn')
            g.next_turn()
            app.events.add('next', **turn_info(before))
        elif path == '/api/undo':
            g.undo()
            app.events.add('undo', after={'turn':g.data['turn'], 'player':g.data['player'], 'darts':g.data['darts']},
                           **turn_info(before))
        elif path == '/api/correct':
            index = body.get('dart_index')
            dropped = g.correct(index, body.get('value'), body.get('multiplier',1))
            app.events.add('correct', before=before['darts'][index], after=g.data['darts'][index],
                           dropped_later_darts=dropped, **turn_info(before, index))
        else:
            count = g.fill_misses()
            app.events.add('fill_misses', count=count, **turn_info(before))
        app.bump()
    # The new empty-board image is taken on the worker; the reply does not wait for it.
    if vision is not None and path in ('/api/throw', '/api/next', '/api/undo'): worker.submit(reset_base_if_ready)
    return None

def check_revision(body):
    """Call with app.game_lock held; internal callers (auto-commit) pass no revision."""
    if body.get('expected_revision') is not None and body['expected_revision'] != app.revision:
        raise Conflict('Match changed on another controller. Review the current turn.')

def turn_info(snapshot, dart_index=None):
    return {'player':snapshot['player'], 'turn':snapshot['turn'],
            'dart_index':len(snapshot['darts']) if dart_index is None else dart_index}

def last_dart(game):
    return dict(game.data['darts'][-1]) if game.data['darts'] else None

def commit_camera_dart(proposal_id, source, replacement=None, expected_revision=None):
    """Commit the pending camera dart `proposal_id` (accepted / auto), or the host's tapped value in its
    place (corrected). Raises Conflict if that dart is no longer the pending one."""
    if vision is None: raise ValueError('No fresh calibrated proposal available')
    if not vision.lock.acquire(timeout=ACTION_TIMEOUT_SECONDS):  # same limit as worker actions (QA D7)
        raise WorkerBusy('Camera processing is busy; nothing was recorded. Try again.')
    try:
        pending = app.flow.observe(vision)
        with app.game_lock:
            check_revision({'expected_revision':expected_revision})
            if app.game is None: raise ValueError('Start a game first')
            if pending is None or pending['id'] != proposal_id:
                raise Conflict('Proposal changed. Check the board and the current camera dart.')
            if source != 'corrected' and app.camera_game and not vision.verified():
                raise ValueError('Verify the current live overlay before confirming a camera score')
            g = app.game
            before = g.snapshot()
            value, multiplier = replacement or (pending['value'], pending['multiplier'])
            g.throw(value, multiplier)
            app.bump()
            proposal = {key:val for key,val in pending.items() if key != 'seen_at'}
            app.events.add('commit', source=source, dart=last_dart(g), proposal=proposal,
                           frame_seq=worker.last_source_seq, **turn_info(before))
        app.flow.close(proposal_id)
        reset_base_if_ready(vision)
    finally:
        vision.publish(); app.flow.observe(vision)
        vision.lock.release()

def auto_commit_once():
    """Commit the pending camera dart if its time has come (decision #1). Returns True if it committed."""
    flow = app.flow
    pending = flow.due()
    if pending is None: return False
    with app.game_lock:
        g = app.game
        if g is None or not app.camera_game or g.turn_over():
            return False
    try:
        commit_camera_dart(pending['id'], 'auto')
        return True
    except (Conflict, ValueError, WorkerBusy):
        return False

def auto_commit_loop():
    while True:
        time.sleep(0.1)
        try: auto_commit_once()
        except Exception: pass  # keep the loop alive; the next tick retries

auto_commit_thread = threading.Thread(target=auto_commit_loop, name='auto-commit', daemon=True)
auto_commit_thread.start()

def test_camera_source(uri, timeout=5.0):
    """Try a camera address without switching to it: wait for one frame. Returns a JSON-ready dict."""
    if camera_source is None: return {'ok':False, 'error':vision_error}
    try: source = camera_source.make_source(uri)
    except ValueError as error: return {'ok':False, 'error':str(error)}
    started = time.monotonic(); source.start()
    try:
        while time.monotonic() - started < timeout:
            frame, _, _ = source.latest()
            if frame is not None:
                return {'ok':True, 'kind':source.kind, 'url_redacted':source.description,
                        'width':int(frame.shape[1]), 'height':int(frame.shape[0]),
                        'first_frame_ms':round((time.monotonic()-started)*1000)}
            time.sleep(0.05)
        return {'ok':False, 'kind':source.kind, 'url_redacted':source.description,
                'error':source.error or f'No image within {timeout:.0f} s'}
    finally:
        source.stop()

def recheck_before_camera_game(v):
    if not v.verified(): raise ValueError('Complete calibration and verify the live overlay before starting')
    v.align(preserve_verification=True)
    if not v.verified(): raise ValueError('Board position changed. Check the live overlay and verify it, then start again.')

def reset_base_if_ready(v):
    if v.aligned and v.fresh(): v.reset_base()

def setup_persistence(state_file, fresh=False):
    """Load the saved match (unless fresh) and calibration; save every later change. Returns a message."""
    global CALIBRATION_DIR
    import persistence
    store = persistence.MatchStore(state_file)
    message = None
    if fresh and state_file.exists():
        kept = state_file.with_name(f'match.previous-{time.strftime("%Y%m%d-%H%M%S")}.json')
        os.replace(state_file, kept)
        message = f'Starting with no match (--fresh); the saved one is kept as {kept}.'
    elif not fresh:
        with app.game_lock: message = store.load(app)
    app.store = store
    CALIBRATION_DIR = state_file.parent
    if vision is not None: restore_calibration()
    return message

def local_ip():
    # Resolve LAN address without contacting an Internet service.
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('192.0.2.1',9))
        address=s.getsockname()[0]; s.close(); return address
    except OSError: return '127.0.0.1'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='0.0.0.0',help='address to listen on (default 0.0.0.0: every network, so phones and the TV can connect)')
    parser.add_argument('--port',type=int,help='default 8000 (HTTP) or 8443 (--https)')
    parser.add_argument('--https',action='store_true',
                        help='optional: serve HTTPS with the local certificate authority (needs OpenSSL; see README)')
    parser.add_argument('--http',action='store_true',help=argparse.SUPPRESS)  # plain HTTP is now the default; kept for old scripts
    parser.add_argument('--lan-ip',help='Override LAN IP printed and included in local certificate')
    parser.add_argument('--camera',metavar='URI',
                        help='pull frames from a camera: http://PHONE:8080/video (IP Webcam), http://PHONE:4747/video '
                             '(DroidCam), snapshot:http://PHONE:8080/shot.jpg, file:VIDEO, dir:FOLDER, or just the phone IP')
    parser.add_argument('--camera-fps',type=float,default=15.0,help='maximum frames per second processed (default 15)')
    parser.add_argument('--state-file',metavar='PATH',
                        default=os.environ.get('DART_STATE_FILE') or str(ROOT/'.local'/'state'/'match.json'),
                        help='where the match is saved after every change (default .local/state/match.json); '
                             'the calibration is kept in the same folder')
    parser.add_argument('--fresh',action='store_true',help='start with no match (the saved one is kept as match.previous-*.json)')
    parser.add_argument('--record',metavar='DIR',
                        help='record the camera stream and event log into DIR from the start (stays on this Mac)')
    parser.add_argument('--auto-commit',type=float,default=DEFAULT_AUTO_COMMIT_SECONDS,metavar='SECONDS',
                        help='commit a camera dart after this many seconds unless corrected (default 3; 0 = always tap Accept)')
    parser.add_argument('--camera-hfov',type=float,default=70.0,
                        help='assumed horizontal FOV (degrees) when the camera focal length cannot be solved from calibration')
    args=parser.parse_args(); ip=args.lan_ip or local_ip()
    if args.https and args.http: parser.error('choose --https or plain HTTP, not both')
    port = args.port if args.port is not None else 8443 if args.https else 8000
    if not 1 <= port <= 65535: parser.error('--port must be between 1 and 65535')
    if not 20 <= args.camera_hfov <= 150: parser.error('--camera-hfov must be between 20 and 150 degrees')
    if vision is not None: vision.camera_hfov = args.camera_hfov
    if not 0 < args.camera_fps <= 60: parser.error('--camera-fps must be between 0 and 60')
    worker.max_fps = args.camera_fps
    if not 0 <= args.auto_commit <= 30: parser.error('--auto-commit must be between 0 and 30 seconds')
    app.flow.delay = args.auto_commit
    try: ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError: parser.error('--lan-ip must be the Mac Wi-Fi IPv4 address')
    if args.https and not shutil.which('openssl'):
        parser.exit(1,'OpenSSL was not found. Install it or restore the macOS /usr/bin tools, or run without --https.\n')
    restore_message = setup_persistence(Path(args.state_file), args.fresh)
    if args.camera:
        try: set_camera_source(args.camera)
        except ValueError as error: parser.error(f'--camera: {error}')
    server = None
    try:
        server=ThreadingHTTPServer((args.host,port),Handler)
        if args.https:
            from local_https import activate
            cert,key,certificate_info=activate(HTTPS_ROOT,ip)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert,key); server.socket=context.wrap_socket(server.socket,server_side=True)
    except (OSError, RuntimeError) as error:
        if server is not None: server.server_close()
        worker.stop()
        parser.exit(1,f'Could not start Dart Room: {error}\nIf port {port} is busy, stop the other instance or use --port {port+1}.\n')
    scheme='https' if args.https else 'http'
    print(f'Computer: Dart Room is listening on {args.host}:{port} ({scheme.upper()})',flush=True)
    print(f'Setup:        {scheme}://localhost:{port}/?t={app.token}',flush=True)
    print(f'Controller:   {scheme}://{ip}:{port}/control?t={app.token}',flush=True)
    print(f'Presentation: {scheme}://{ip}:{port}/play?t={app.display_token}',flush=True)
    print(f'Showcase:     {scheme}://{ip}:{port}/showcase',flush=True)
    if ip == '127.0.0.1':
        print('Other devices need the Mac Wi-Fi address. Restart with --lan-ip YOUR_WIFI_IPV4.',flush=True)
    print('Private home-LAN app. Keep the links private: anyone on your Wi-Fi with a link can control the match.',flush=True)
    print('Ctrl-C stops it. Images and game state stay in memory.',flush=True)
    if args.https:
        print('Local CA: '+certificate_info['ca_subject'],flush=True)
        print('CA SHA-256: '+certificate_info['sha256_fingerprint'],flush=True)
        print('Device trust setup: see README. Public CA helper: .venv/bin/python local_https.py serve --lan-ip '+ip,flush=True)
    if restore_message: print(restore_message,flush=True)
    if args.record:
        try: start_recording(args.record); print('Recording to: '+str(recorder.directory),flush=True)
        except ValueError as error: print('Recording not started: '+str(error),flush=True)
    if worker.source is not None: print('Camera source: '+worker.source.description,flush=True)
    else: print('Camera source: none yet. Open the Setup link and enter the phone\'s IP Webcam address.',flush=True)
    if vision_error: print(vision_error,flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        stop_recording('server stopped'); worker.stop(); server.server_close()

if __name__=='__main__': main()
