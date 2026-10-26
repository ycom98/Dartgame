#!/usr/bin/env python3
"""Private LAN prototype. No cloud services or image retention."""
import argparse
import json
import ipaddress
import shutil
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from core import Game

ROOT = Path(__file__).resolve().parent
try:
    from vision import Vision
    vision = Vision()
    vision_error = None
except ImportError:
    vision = None
    vision_error = 'Camera vision unavailable: install requirements.txt. Manual game still works.'
from vision_worker import VisionWorker, WorkerBusy

# All Vision work runs on this one thread (M1-06). It looks up the module-level `vision` each time.
worker = VisionWorker(lambda: vision)

# Lock order (M1-06): app.game_lock protects only the game, revision and camera_game. vision.lock may be
# held while taking app.game_lock (camera-proposal commit); app.game_lock is never held while taking
# vision.lock or waiting for the vision worker.
GAME_PATHS = ('/api/game', '/api/throw', '/api/next', '/api/undo')

def vision_state():
    """Latest vision state without waiting for the vision lock."""
    if vision is None:
        return {'fresh':False,'aligned':False,'verified':False,'phase':'unavailable','message':vision_error}
    return vision.current_state()

class App:
    def __init__(self, token=None):
        self.token = token or secrets.token_urlsafe(24)
        self.display_token = secrets.token_urlsafe(24)
        self.game = None; self.game_lock = threading.RLock(); self.camera_game = False; self.revision = 0
    def game_state(self):
        with self.game_lock:
            return {'game':self.game.snapshot() if self.game else None, 'revision':self.revision,
                    'camera_game':self.camera_game}
    def state(self):
        game = self.game_state()
        return {'game':game['game'], 'revision':game['revision'],
                'presentation_path':'/play?t='+self.display_token,
                'vision':vision_state(), 'camera_game':game['camera_game']}

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
                  **{'/static/'+name:name for name in ('presentation.css','presentation.js','control.js','showcase.js')}}
        if path in public:
            content = (ROOT/'static'/public[path]).read_bytes()
            mime = 'text/css' if path.endswith('.css') else 'text/javascript' if path.endswith('.js') else 'text/html'
            self.send_response(200); self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(content)))
            self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers(); self.wfile.write(content); return
        if path in ('/','/phone'):
            content = (ROOT/'static'/'index.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(content)))
            self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers(); self.wfile.write(content); return
        if not self.authenticated(display=path == '/api/state'): return self.reply({'error':'Open the complete pairing link printed in Terminal'},401)
        if path == '/api/state': return self.reply(app.state())
        if path in ('/api/image', '/api/calibration/image'):
            if vision is None or vision.frame is None: return self.reply({'error':'No phone image yet'},404)
            frame = vision.frame  # ingest replaces the array, never edits it, so this reference is safe to encode
            if path == '/api/calibration/image':
                with vision.lock:
                    try: frame = vision.snapshot_frame(parse_qs(urlparse(self.path).query).get('id',[None])[0])
                    except ValueError as error: return self.reply({'error':str(error)},400)
                    finally: vision.publish()
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
            if path == '/api/frame':
                if vision is None: raise ValueError(vision_error)
                worker.call(lambda v: v.ingest(raw)); return self.reply({'ok':True})
            body = json.loads(raw)
            if not isinstance(body,dict): raise ValueError('Expected a JSON object')
            if path in GAME_PATHS: return self.game_action(path, body)
            if path == '/api/calibrate' and not isinstance(body.get('snapshot_id'),str):
                if vision is None: raise ValueError(vision_error)
                raise ValueError('Select Set four points to capture a calibration image first')
            actions = {
                '/api/camera/reset': lambda v: v.reset_camera(),
                '/api/calibration/start': lambda v: v.begin_calibration(),
                '/api/calibration/cancel': lambda v: v.cancel_calibration(),
                '/api/calibrate': lambda v: v.calibrate(body.get('points'),body['snapshot_id']),
                '/api/verify': lambda v: v.verify(body.get('version')),
                '/api/align': lambda v: v.align(),
                '/api/baseline': lambda v: v.reset_base(),
            }
            if path not in actions: return self.reply({'error':'Not found'},404)
            if vision is None: raise ValueError(vision_error)
            result = worker.call(actions[path])
            if path == '/api/calibration/start': return self.reply({**app.state(), 'snapshot':result})
            self.reply(app.state())
        except WorkerBusy as error:
            self.reply({'error':str(error)},503)
        except (ValueError,TypeError,KeyError,OverflowError) as error:
            self.reply({'error':str(error)},400)
        except Exception:
            self.reply({'error':'Request failed. Check camera connection and calibration.'},500)
    def game_action(self, path, body):
        """Game writes take app.game_lock only. A camera-proposal commit takes vision.lock first."""
        if path == '/api/game':
            camera = body.get('camera', True)
            if type(camera) is not bool: raise ValueError('camera must be boolean')
            candidate = Game(body.get('names'),body.get('start',301),body.get('double_out',False))
            if camera:
                if vision is None: raise ValueError('Complete calibration and verify the live overlay before starting')
                worker.call(recheck_before_camera_game)
            with app.game_lock:
                app.game = candidate; app.camera_game = camera; app.revision += 1
            return self.reply(app.state())
        if path == '/api/throw' and body.get('proposal') and vision is not None:
            with vision.lock:
                try:
                    with app.game_lock: conflict = self.write_game(path, body)
                    if conflict is None: vision.reset_base()
                finally:
                    vision.publish()
        else:
            with app.game_lock: conflict = self.write_game(path, body)
            # The new empty-board image is taken on the worker; the reply does not wait for it.
            if conflict is None and vision is not None: worker.submit(reset_base_if_ready)
        if conflict is not None: return self.reply(conflict,409)
        self.reply(app.state())
    def write_game(self, path, body):
        """throw / next / undo. Call with app.game_lock held (and vision.lock first for a proposal).

        Returns the 409 body for a stale expected_revision, otherwise None after the write."""
        if 'expected_revision' in body:
            expected = body['expected_revision']
            if type(expected) is not int: raise ValueError('expected_revision must be an integer')
            if expected != app.revision:
                return {**app.state(), 'error':'Match changed on another controller. Review the current turn.'}
        if app.game is None: raise ValueError('Start a game first')
        if path == '/api/throw' and body.get('proposal'):
            if app.camera_game and (vision is None or not vision.verified()):
                raise ValueError('Verify the current live overlay before confirming a camera score')
            if vision is None or not vision.fresh() or not vision.aligned or vision.proposal is None:
                raise ValueError('No fresh calibrated proposal available')
            candidate = vision.proposal.copy()
            app.game.throw(candidate['value'],candidate['multiplier'])
        elif path == '/api/throw':
            app.game.throw(body.get('value'),body.get('multiplier',1))
        elif path == '/api/next':
            if app.camera_game and (vision is None or not vision.verified()):
                raise ValueError('Reconnect camera, align board and verify the overlay before next turn')
            app.game.next_turn()
        else:
            app.game.undo()
        app.revision += 1
        return None

def recheck_before_camera_game(v):
    if not v.verified(): raise ValueError('Complete calibration and verify the live overlay before starting')
    v.align(preserve_verification=True)
    if not v.verified(): raise ValueError('Board position changed. Check the live overlay and verify it, then start again.')

def reset_base_if_ready(v):
    if v.aligned and v.fresh(): v.reset_base()

def local_ip():
    # Resolve LAN address without contacting an Internet service.
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('192.0.2.1',9))
        address=s.getsockname()[0]; s.close(); return address
    except OSError: return '127.0.0.1'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='0.0.0.0'); parser.add_argument('--port',type=int,default=8443)
    parser.add_argument('--http',action='store_true',help='localhost/manual testing only; phone camera requires HTTPS')
    parser.add_argument('--lan-ip',help='Override LAN IP printed and included in local certificate')
    parser.add_argument('--camera-hfov',type=float,default=70.0,
                        help='assumed horizontal FOV (degrees) when the camera focal length cannot be solved from calibration')
    args=parser.parse_args(); ip=args.lan_ip or local_ip()
    if not 1 <= args.port <= 65535: parser.error('--port must be between 1 and 65535')
    if not 20 <= args.camera_hfov <= 150: parser.error('--camera-hfov must be between 20 and 150 degrees')
    if vision is not None: vision.camera_hfov = args.camera_hfov
    try: ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError: parser.error('--lan-ip must be the Mac Wi-Fi IPv4 address')
    if args.http and args.host not in ('127.0.0.1','localhost','::1'):
        parser.error('--http requires --host 127.0.0.1 (or localhost/::1)')
    if not args.http and not shutil.which('openssl'):
        parser.exit(1,'OpenSSL was not found. Install it or restore the macOS /usr/bin tools, then retry.\n')
    server = None
    try:
        server=ThreadingHTTPServer((args.host,args.port),Handler)
        if not args.http:
            from local_https import activate
            cert,key,certificate_info=activate(ROOT,ip)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert,key); server.socket=context.wrap_socket(server.socket,server_side=True)
    except (OSError, RuntimeError) as error:
        if server is not None: server.server_close()
        parser.exit(1,f'Could not start Dart Room: {error}\nIf port {args.port} is busy, stop the other instance or use --port 8444.\n')
    scheme='http' if args.http else 'https'
    print(f'Computer: {scheme}://localhost:{args.port}/?t={app.token}',flush=True)
    print(f'Controller: {scheme}://localhost:{args.port}/control?t={app.token}',flush=True)
    print(f'Presentation: {scheme}://localhost:{args.port}/play?t={app.display_token}',flush=True)
    print(f'Showcase: {scheme}://localhost:{args.port}/showcase',flush=True)
    print(f'Phone:    {scheme}://{ip}:{args.port}/phone?t={app.token}',flush=True)
    if ip == '127.0.0.1':
        print('Phone pairing needs the Mac Wi-Fi address. Restart with --lan-ip YOUR_WIFI_IPV4.',flush=True)
    print('Private LAN prototype. Keep links private. Ctrl-C stops it. Images and game state stay in memory.',flush=True)
    if not args.http:
        print('Local CA: '+certificate_info['ca_subject'],flush=True)
        print('CA SHA-256: '+certificate_info['sha256_fingerprint'],flush=True)
        print('Phone trust setup: see README. Public CA helper: .venv/bin/python local_https.py serve --lan-ip '+ip,flush=True)
    if vision_error: print(vision_error,flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
