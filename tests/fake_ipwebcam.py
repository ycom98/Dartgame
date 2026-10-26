"""A stand-in for the Android "IP Webcam" app, for tests and phone-free rehearsal (M1-07).

Serves, like IP Webcam:
  /video     multipart/x-mixed-replace MJPEG with a Content-Length per part
  /shot.jpg  the current frame as one JPEG
Test control (not part of IP Webcam): /scene?n=K switches to scene K of --scenes (or set_scene(K) in Python).
With style='droidcam' the /video parts have no Content-Length (some DroidCam versions).

Each frame carries its sequence number as a row of 16 black/white blocks in the top-left
corner (embed_seq / read_seq), so a test can tell which frame vision processed.

Command line (serves sim frames, or a folder of images):
  .venv/bin/python tests/fake_ipwebcam.py --port 8080 --mount left
  .venv/bin/python tests/fake_ipwebcam.py --port 8080 --folder path/to/frames
"""
import argparse
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

BOUNDARY = 'Ba4oTvQMY8ew04N8dcnM'  # IP Webcam's own boundary string
SEQ_BITS = 16
SEQ_BLOCK = 12


def embed_seq(frame, seq):
    """Draw seq as SEQ_BITS black/white blocks along the top-left edge (survives JPEG)."""
    frame = frame.copy()
    for bit in range(SEQ_BITS):
        value = 255 if (seq >> bit) & 1 else 0
        x = bit * SEQ_BLOCK
        frame[0:SEQ_BLOCK, x:x + SEQ_BLOCK] = value
    return frame


def read_seq(frame):
    seq = 0
    for bit in range(SEQ_BITS):
        x = bit * SEQ_BLOCK + SEQ_BLOCK // 2
        if frame[SEQ_BLOCK // 2, x].mean() > 127:
            seq |= 1 << bit
    return seq


class FakeIPWebcam:
    """frames: a list of BGR frames, cycled. Serves at fps on 127.0.0.1:port (0 = any free port)."""

    def __init__(self, frames, fps=15.0, port=0, style='ipwebcam', quality=85, host='127.0.0.1'):
        self.frames = list(frames)
        self.fps = fps
        self.port = port
        self.host = host
        self.style = style
        self.quality = quality
        self.seq = 0                  # sequence number of the newest frame
        self.sent_seq = 0             # newest seq written to any /video client
        self.jpeg = None
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.running = False
        self.httpd = None
        self.clock = None
        self.connections = set()
        self.scenes = []
        self.scene_changed_at = None

    @property
    def url(self):
        return f'http://{self.host}:{self.port}'

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.connections.add(self.connection)
                try:
                    if self.path.startswith('/video'):
                        owner.stream(self)
                    elif self.path.startswith('/scene') and owner.scenes:
                        index = int(self.path.partition('n=')[2] or 0)
                        owner.set_frames([owner.scenes[index]])
                        self.send_response(200)
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                    elif self.path.startswith('/shot.jpg'):
                        with owner.lock:
                            data = owner.jpeg
                        self.send_response(200)
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        self.send_error(404)
                except OSError:
                    pass
                finally:
                    owner.connections.discard(self.connection)

        self.running = True
        self.encode_next()
        server_class = type('Server', (ThreadingHTTPServer,), {'allow_reuse_address': True, 'daemon_threads': True})
        self.httpd = server_class((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.clock = threading.Thread(target=self.tick, daemon=True)
        self.clock.start()
        return self

    def stop(self):
        """Simulate the phone app stopping: close the listener and every open stream."""
        self.running = False
        with self.changed:
            self.changed.notify_all()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        for connection in list(self.connections):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.clock is not None:
            self.clock.join(2)

    def set_frames(self, frames):
        """Serve these frames from now on (cycled), e.g. the board with one more dart."""
        self.frames = list(frames)
        self.scene_changed_at = time.monotonic()

    def encode_next(self):
        frame = embed_seq(self.frames[self.seq % len(self.frames)], self.seq + 1)
        ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        with self.changed:
            self.seq += 1
            self.jpeg = data.tobytes()
            self.changed.notify_all()

    def tick(self):
        started = time.monotonic()
        produced = 1
        while self.running:
            delay = started + produced / self.fps - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if not self.running:
                break
            self.encode_next()
            produced += 1

    def stream(self, handler):
        handler.send_response(200)
        handler.send_header('Content-Type', f'multipart/x-mixed-replace;boundary={BOUNDARY}')
        handler.end_headers()
        last = 0
        while self.running:
            with self.changed:
                self.changed.wait_for(lambda: self.seq != last or not self.running, timeout=1.0)
                if not self.running:
                    return
                seq, data = self.seq, self.jpeg
            if seq == last:
                continue
            last = seq
            head = f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n'
            if self.style == 'ipwebcam':
                head += f'Content-Length: {len(data)}\r\n'
            handler.wfile.write(head.encode() + b'\r\n' + data + b'\r\n')
            handler.wfile.flush()
            self.sent_seq = max(self.sent_seq, seq)


def sim_frames(mount='left', width=1280, height=720, darts=0, seed=1):
    """An empty board (and optionally darts) rendered by sim/ for the given mount."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from sim import camera_for_mount
    from sim.scene import random_dart, render_clean
    camera = camera_for_mount(mount, width, height)
    rng = np.random.default_rng(seed)
    scene = [random_dart(rng) for _ in range(darts)]
    return camera, [render_clean(camera, scene)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--fps', type=float, default=15.0)
    parser.add_argument('--mount', default='left')
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--folder', help='serve these images (sorted, cycled) instead of a sim render')
    parser.add_argument('--scenes', help='folder of scene images; GET /scene?n=K switches between them (tests)')
    parser.add_argument('--style', choices=('ipwebcam', 'droidcam'), default='ipwebcam')
    args = parser.parse_args()
    scenes = []
    if args.scenes:
        scene_paths = sorted(p for p in Path(args.scenes).iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp'))
        scenes = [cv2.imread(str(p)) for p in scene_paths]
    if scenes:
        frames = scenes[:1]
    elif args.folder:
        paths = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp'))
        frames = [cv2.imread(str(p)) for p in paths]
    else:
        _, frames = sim_frames(args.mount, args.width, args.height)
    fake = FakeIPWebcam(frames, args.fps, args.port, args.style, host=args.host)
    fake.scenes = scenes
    fake.start()
    print(f'Fake IP Webcam: {fake.url}/video and {fake.url}/shot.jpg (Ctrl-C stops)', flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        fake.stop()


if __name__ == '__main__':
    main()
