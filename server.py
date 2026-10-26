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

class App:
    def __init__(self, token=None):
        self.token = token or secrets.token_urlsafe(24)
        self.display_token = secrets.token_urlsafe(24)
        self.game = None; self.lock = threading.RLock(); self.camera_game = False; self.revision = 0
    def state(self):
        return {'game':self.game.snapshot() if self.game else None, 'revision':self.revision,
                'presentation_path':'/play?t='+self.display_token,
                'vision':vision.state() if vision else {'fresh':False,'aligned':False,'verified':False,'phase':'unavailable','message':vision_error},
                'camera_game':self.camera_game}

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
        with app.lock:
            if path == '/api/state': return self.reply(app.state())
            if path in ('/api/image', '/api/calibration/image'):
                if vision is None or vision.frame is None: return self.reply({'error':'No phone image yet'},404)
                frame = vision.frame
                if path == '/api/calibration/image':
                    try: frame = vision.snapshot_frame(parse_qs(urlparse(self.path).query).get('id',[None])[0])
                    except ValueError as error: return self.reply({'error':str(error)},400)
                import cv2
                ok,data = cv2.imencode('.jpg',frame)
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
            with app.lock:
                if path == '/api/frame':
                    if vision is None: raise ValueError(vision_error)
                    vision.ingest(raw); return self.reply({'ok':True})
                body = json.loads(raw)
                if not isinstance(body,dict): raise ValueError('Expected a JSON object')
                if path in ('/api/throw','/api/next','/api/undo') and 'expected_revision' in body:
                    expected = body['expected_revision']
                    if type(expected) is not int: raise ValueError('expected_revision must be an integer')
                    if expected != app.revision:
                        return self.reply({**app.state(), 'error':'Match changed on another controller. Review the current turn.'},409)
                if path == '/api/game':
                    camera = body.get('camera', True)
                    if type(camera) is not bool: raise ValueError('camera must be boolean')
                    candidate = Game(body.get('names'),body.get('start',301),body.get('double_out',False))
                    if camera:
                        if vision is None or not vision.verified():
                            raise ValueError('Complete calibration and verify the live overlay before starting')
                        vision.align(preserve_verification=True)
                        if not vision.verified():
                            raise ValueError('Board position changed. Check the live overlay and verify it, then start again.')
                    app.game = candidate
                    app.camera_game = camera
                elif path == '/api/camera/reset':
                    if vision is None: raise ValueError(vision_error)
                    vision.reset_camera()
                elif path == '/api/calibration/start':
                    if vision is None: raise ValueError(vision_error)
                    snapshot = vision.begin_calibration()
                    return self.reply({**app.state(), 'snapshot':snapshot})
                elif path == '/api/calibration/cancel':
                    if vision is None: raise ValueError(vision_error)
                    vision.cancel_calibration()
                elif path == '/api/calibrate':
                    if vision is None: raise ValueError(vision_error)
                    if not isinstance(body.get('snapshot_id'),str):
                        raise ValueError('Select Set four points to capture a calibration image first')
                    vision.calibrate(body.get('points'),body['snapshot_id'])
                elif path == '/api/verify':
                    if vision is None: raise ValueError(vision_error)
                    vision.verify(body.get('version'))
                elif path == '/api/align':
                    if vision is None: raise ValueError(vision_error)
                    vision.align()
                elif path == '/api/baseline':
                    if vision is None: raise ValueError(vision_error)
                    vision.reset_base()
                elif path == '/api/throw':
                    if app.game is None: raise ValueError('Start a game first')
                    if body.get('proposal'):
                        if app.camera_game and (vision is None or not vision.verified()):
                            raise ValueError('Verify the current live overlay before confirming a camera score')
                        if vision is None or not vision.fresh() or not vision.aligned or vision.proposal is None:
                            raise ValueError('No fresh calibrated proposal available')
                        candidate = vision.proposal.copy()
                        app.game.throw(candidate['value'],candidate['multiplier']); vision.reset_base()
                    else:
                        app.game.throw(body.get('value'),body.get('multiplier',1))
                        if vision and vision.aligned and vision.fresh(): vision.reset_base()
                elif path == '/api/next':
                    if app.game is None: raise ValueError('Start a game first')
                    if app.camera_game and (vision is None or not vision.verified()):
                        raise ValueError('Reconnect camera, align board and verify the overlay before next turn')
                    app.game.next_turn()
                    if vision and vision.aligned and vision.fresh(): vision.reset_base()
                elif path == '/api/undo':
                    if app.game is None: raise ValueError('Start a game first')
                    app.game.undo()
                    if vision and vision.aligned and vision.fresh(): vision.reset_base()
                else: return self.reply({'error':'Not found'},404)
                if path in ('/api/game','/api/throw','/api/next','/api/undo'): app.revision += 1
                self.reply(app.state())
        except (ValueError,TypeError,KeyError,OverflowError) as error:
            self.reply({'error':str(error)},400)
        except Exception:
            self.reply({'error':'Request failed. Check camera connection and calibration.'},500)

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
