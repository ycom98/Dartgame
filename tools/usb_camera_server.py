"""Share a USB webcam over the home Wi-Fi, like the IP Webcam phone app (no internet needed).

Run this on the laptop the webcam is plugged into (Mac, Windows or Linux with Python 3.10+ and OpenCV):

    python3 tools/usb_camera_server.py            # first camera, 1920x1080, port 8080
    python3 tools/usb_camera_server.py --camera 1 --width 1280 --height 720

Then on the Dart Room Mac use this laptop's Wi-Fi address as the camera, exactly like the phone:

    bash start-mac.command --camera LAPTOP_IP

It serves /video (MJPEG stream) and /shot.jpg (one picture). Press Ctrl-C to stop.
"""
import argparse
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_source import open_usb_camera  # noqa: E402

BOUNDARY = 'dartroomframe'


class Camera:
    """Reads the USB camera in one thread; every client gets the newest JPEG."""

    def __init__(self, index, width, height, quality, fps):
        self.index, self.width, self.height, self.quality, self.fps = index, width, height, quality, fps
        self.jpeg, self.seq, self.error = None, 0, None
        self.changed = threading.Condition()

    def run(self):
        while True:
            capture = open_usb_camera(self.index, self.width, self.height)
            if capture is None:
                self.error = f'USB camera {self.index} did not open (plugged in? camera permission for Terminal?)'
                print(self.error, flush=True); time.sleep(2); continue
            size = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            print(f'USB camera {self.index} open at {size[0]}x{size[1]}', flush=True)
            failures = 0
            while failures < 30:
                started = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    failures += 1; time.sleep(0.05); continue
                failures = 0; self.error = None
                data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])[1].tobytes()
                with self.changed:
                    self.jpeg, self.seq = data, self.seq + 1
                    self.changed.notify_all()
                time.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - started)))
            capture.release()
            print('Camera stopped sending pictures; reopening.', flush=True)


def handler_for(camera):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if self.path.startswith('/video'):
                    self.send_response(200)
                    self.send_header('Content-Type', f'multipart/x-mixed-replace;boundary={BOUNDARY}')
                    self.end_headers()
                    last = 0
                    while True:
                        with camera.changed:
                            camera.changed.wait_for(lambda: camera.seq != last, timeout=2.0)
                            seq, data = camera.seq, camera.jpeg
                        if seq == last or data is None:
                            continue
                        last = seq
                        head = f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n\r\n'
                        self.wfile.write(head.encode() + data + b'\r\n')
                        self.wfile.flush()
                elif self.path.startswith('/shot.jpg') and camera.jpeg is not None:
                    data = camera.jpeg
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404 if camera.jpeg is not None else 503)
            except OSError:
                pass  # the viewer went away

    return Handler


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('192.0.2.1', 9))
        address = s.getsockname()[0]; s.close(); return address
    except OSError:
        return '127.0.0.1'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--camera', type=int, default=0, help='USB camera number (0 = first)')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=float, default=15.0)
    parser.add_argument('--quality', type=int, default=85, help='JPEG quality 1-100')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    camera = Camera(args.camera, args.width, args.height, args.quality, args.fps)
    threading.Thread(target=camera.run, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0', args.port), handler_for(camera))
    server.daemon_threads = True
    print(f'Sharing USB camera {args.camera}. On the Dart Room Mac use:  --camera {lan_ip()}:{args.port}', flush=True)
    print('Keep this window open. Ctrl-C stops it.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
