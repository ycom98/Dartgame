"""Pull-based camera frame sources (M1-07).

The Mac pulls frames from the phone instead of the phone browser pushing them:

  http://PHONE:8080/video              IP Webcam MJPEG stream (Android app "IP Webcam")
  http://PHONE:4747/video              DroidCam MJPEG stream (fallback)
  snapshot:http://PHONE:8080/shot.jpg  poll single JPEGs (IP Webcam), ?fps=N (default 5)
  PHONE or PHONE:PORT                  shorthand for IP Webcam http://PHONE:8080/video
  file:path/to/video.avi               a video file, paced in real time
  dir:path/to/frames/                  an image folder (sorted by name), ?fps=N (default 15)

file: and dir: accept ?realtime=0 (lockstep replay: every frame is handed to the vision worker,
none dropped) and ?loop=1 (start again at the end).

Every source keeps the newest frame only. A reader that falls behind skips frames; it never queues
them, so processing never lags the camera by more than about one frame. Network sources reconnect
on their own with a 1 → 2 → 4 → 5 s backoff. Frames over 1920 px on the long side are downscaled.
Only the standard library, NumPy and OpenCV are used.
"""
import base64
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import cv2
import numpy as np

MAX_LONG_SIDE = 1920
# A network read that waits longer than this counts as a dropped connection.
READ_TIMEOUT_SECONDS = 3.0
# The source reports disconnected when the newest frame is older than this.
STALE_SECONDS = 3.0
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 5.0)
MAX_PART_BYTES = 12_000_000
IP_WEBCAM_PORT = 8080
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp')


def rate(times, now, window=2.0):
    """Events per second from monotonic times in the last window seconds (spans shorter windows correctly)."""
    recent = [t for t in times if now - t <= window]
    if len(recent) < 2:
        return 0.0
    return round((len(recent) - 1) / max(now - recent[0], 1e-6), 1)


def fit_frame(frame):
    """Downscale a frame whose long side exceeds MAX_LONG_SIDE (instead of rejecting it)."""
    height, width = frame.shape[:2]
    long_side = max(height, width)
    if long_side <= MAX_LONG_SIDE:
        return frame
    scale = MAX_LONG_SIDE / long_side
    return cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)


def decode_jpeg(data):
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('Camera sent an image that could not be decoded')
    return fit_frame(frame)


def redact_url(url):
    """The URL without its password (IP Webcam can require a login)."""
    parts = urlsplit(url)
    if parts.password is None and parts.username is None:
        return url
    host = parts.hostname or ''
    if parts.port:
        host += f':{parts.port}'
    user = (parts.username or '') + (':***' if parts.password is not None else '')
    return urlunsplit((parts.scheme, f'{user}@{host}', parts.path, parts.query, parts.fragment))


class FrameSource:
    """Base class: start(), stop(), latest() -> (frame, timestamp, seq), status().

    seq increases by one for every frame received. timestamp is time.time() at arrival.
    on_frame, if set, is called (from the source thread) after each new frame.
    """
    kind = 'source'

    def __init__(self, description):
        self.description = description
        self.on_frame = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self.seq = 0
        self.timestamp = 0.0
        self.encoded = None          # newest JPEG bytes (network sources); decoded lazily
        self.frame = None            # newest decoded frame
        self.frame_seq = 0           # seq that self.frame belongs to
        self.arrivals = []           # monotonic arrival times over the last 2 s, for fps
        self.connected = False
        self.ended = False
        self.reconnects = 0
        self.error = None
        self.size = None
        self.consumed = threading.Event()   # lockstep replay: the newest frame was taken
        self.consumed.set()

    # ---- lifecycle ---------------------------------------------------------------------
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run_safely, name=f'{self.kind}-source', daemon=True)
            self.thread.start()
        return self

    def stop(self, timeout=2.0):
        self.stopping.set()
        self.consumed.set()
        self.close()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)

    def close(self):
        """Interrupt a blocking read (network sources)."""

    def run_safely(self):
        try:
            self.run()
        except Exception as error:  # a source thread must never die silently
            self.connected = False
            self.error = f'{type(error).__name__}: {error}'

    def run(self):
        raise NotImplementedError

    def sleep(self, seconds):
        """Interruptible sleep; returns True when the source is stopping."""
        return self.stopping.wait(seconds)

    # ---- frames ------------------------------------------------------------------------
    def put_encoded(self, data):
        with self.lock:
            self.encoded = data
            self.mark_arrival()
        self.notify()

    def put_frame(self, frame):
        frame = fit_frame(frame)
        with self.lock:
            self.encoded = None
            self.frame = frame
            self.mark_arrival()
            self.frame_seq = self.seq
            self.size = (int(frame.shape[1]), int(frame.shape[0]))
        self.notify()

    def mark_arrival(self):
        self.seq += 1
        self.timestamp = time.time()
        now = time.monotonic()
        self.arrivals = [t for t in self.arrivals if now - t <= 2.0] + [now]
        self.connected = True
        self.error = None
        self.consumed.clear()

    def notify(self):
        callback = self.on_frame
        if callback is not None:
            callback()

    def latest(self):
        """(frame, timestamp, seq) of the newest frame, or (None, 0, 0) before the first one."""
        with self.lock:
            if self.encoded is not None and self.frame_seq != self.seq:
                data, seq = self.encoded, self.seq
            else:
                data = None
            frame, timestamp, seq_out = self.frame, self.timestamp, self.frame_seq
        if data is not None:
            try:
                decoded = decode_jpeg(data)
            except ValueError as error:
                self.error = str(error)
                return frame, timestamp, seq_out
            with self.lock:
                if self.frame_seq < seq:
                    self.frame, self.frame_seq = decoded, seq
                    self.size = (int(decoded.shape[1]), int(decoded.shape[0]))
                frame, timestamp, seq_out = self.frame, self.timestamp, self.frame_seq
        if frame is not None and seq_out == self.seq:
            self.consumed.set()
        return frame, timestamp, seq_out

    def latest_encoded(self):
        """(JPEG bytes or None, timestamp, seq) of the newest frame as received (for recording)."""
        with self.lock:
            return self.encoded, self.timestamp, self.seq

    def wait_consumed(self):
        """Lockstep replay: block until the newest frame has been taken. True when stopping."""
        while not self.consumed.wait(0.2):
            if self.stopping.is_set():
                return True
        return self.stopping.is_set()

    def status(self):
        age = time.time() - self.timestamp if self.timestamp else None
        connected = self.connected and age is not None and age < STALE_SECONDS
        return {'kind': self.kind, 'url_redacted': self.description, 'connected': connected,
                'fps': rate(self.arrivals, time.monotonic()), 'last_frame_age': round(age, 2) if age is not None else None,
                'reconnects': self.reconnects, 'frames': self.seq, 'ended': self.ended,
                'width': self.size[0] if self.size else None, 'height': self.size[1] if self.size else None,
                'error': self.error}


class NetworkSource(FrameSource):
    """Shared connect / backoff / basic-auth handling for HTTP sources."""

    def __init__(self, url):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise ValueError('Camera URL must start with http:// and name the phone address')
        super().__init__(redact_url(url))
        self.headers = {'User-Agent': 'DartRoom/1'}
        if parts.username is not None:
            credentials = f'{parts.username}:{parts.password or ""}'.encode()
            self.headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode()
            host = parts.hostname + (f':{parts.port}' if parts.port else '')
            url = urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
        self.url = url
        self.response = None

    def open(self):
        request = urllib.request.Request(self.url, headers=self.headers)
        return urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS)

    def close(self):
        response = self.response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def run(self):
        attempt = 0
        while not self.stopping.is_set():
            received_before = self.seq
            try:
                self.read_session()
                if not self.stopping.is_set():
                    raise ConnectionError('Camera closed the stream')
            except Exception as error:
                if self.stopping.is_set():
                    break
                self.connected = False
                self.error = describe_network_error(error)
            finally:
                self.close()
                self.response = None
            if self.seq > received_before:
                attempt = 0  # it worked for a while: start the backoff again from 1 s
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            attempt += 1
            if self.sleep(delay):
                break
            self.reconnects += 1

    def read_session(self):
        raise NotImplementedError


def describe_network_error(error):
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 401:
            return 'Camera needs a login: use http://USER:PASSWORD@PHONE:8080/video'
        return f'Camera answered HTTP {error.code}'
    if isinstance(error, urllib.error.URLError):
        error = error.reason
    if isinstance(error, TimeoutError) or 'timed out' in str(error):
        return 'No data from the camera (timed out). Check the phone is awake and on the same Wi-Fi.'
    if isinstance(error, ConnectionRefusedError):
        return 'Connection refused. Is the IP Webcam server started on the phone?'
    return f'{type(error).__name__}: {error}'


class MjpegSource(NetworkSource):
    """multipart/x-mixed-replace JPEG stream (IP Webcam /video, DroidCam /video)."""
    kind = 'mjpeg'

    def read_session(self):
        self.response = response = self.open()
        content_type = response.headers.get('Content-Type', '')
        if content_type.startswith('image/jpeg'):
            raise ValueError('That address gives single images. Use snapshot:' + self.description)
        boundary = None
        for parameter in content_type.split(';')[1:]:
            key, _, value = parameter.strip().partition('=')
            if key.lower() == 'boundary':
                boundary = value.strip().strip('"')
        for part in iter_mjpeg_parts(response, boundary):
            if self.stopping.is_set():
                return
            self.put_encoded(part)


def iter_mjpeg_parts(stream, boundary=None):
    """Yield the JPEG bytes of each part of a multipart MJPEG stream.

    Uses each part's Content-Length when present (IP Webcam). Without one (some DroidCam
    versions), the part runs until the next boundary line.
    """
    marker = ('--' + boundary.removeprefix('--')).encode() if boundary else None
    line = stream.readline(65536)
    while line:
        stripped = line.strip()
        is_boundary = stripped.startswith(marker) if marker else stripped.startswith(b'--')
        if not is_boundary:
            line = stream.readline(65536)
            continue
        if marker and stripped == marker + b'--':
            return
        headers = {}
        while True:
            line = stream.readline(65536)
            if not line:
                return
            if not line.strip():
                break
            key, _, value = line.decode('latin-1').partition(':')
            headers[key.strip().lower()] = value.strip()
        length = headers.get('content-length')
        if length is not None and length.isdigit():
            size = int(length)
            if size > MAX_PART_BYTES:
                raise ValueError('Camera frame is too large')
            data = read_exact(stream, size)
            if data is None:
                return
            yield data
            line = stream.readline(65536)
            continue
        if marker is None:
            raise ValueError('Stream parts have no Content-Length and no boundary')
        chunks, total = [], 0
        while True:
            line = stream.readline(65536)
            if not line:
                return
            if line.strip().startswith(marker):
                break
            chunks.append(line)
            total += len(line)
            if total > MAX_PART_BYTES:
                raise ValueError('Camera frame is too large')
        data = b''.join(chunks)
        if data.endswith(b'\r\n'):
            data = data[:-2]
        elif data.endswith(b'\n'):
            data = data[:-1]
        yield data
        # line already holds the next boundary


def read_exact(stream, size):
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


class SnapshotSource(NetworkSource):
    """Poll single JPEGs (IP Webcam /shot.jpg) at a fixed rate."""
    kind = 'snapshot'

    def __init__(self, url, fps=5.0):
        super().__init__(url)
        if not 0 < fps <= 30:
            raise ValueError('Snapshot fps must be between 0 and 30')
        self.fps = fps

    def read_session(self):
        while not self.stopping.is_set():
            started = time.monotonic()
            self.response = response = self.open()
            data = response.read(MAX_PART_BYTES + 1)
            response.close()
            if len(data) > MAX_PART_BYTES:
                raise ValueError('Camera frame is too large')
            self.put_encoded(data)
            if self.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - started))):
                return


class ReplaySource(FrameSource):
    """Shared pacing for local replay: real time at a frame rate, or lockstep with the consumer."""

    def __init__(self, description, fps, realtime=True, loop=False):
        super().__init__(description)
        self.fps = fps
        self.realtime = realtime
        self.loop = loop

    def frames(self):
        raise NotImplementedError

    def run(self):
        started = time.monotonic()
        produced = 0  # counts across loops, so a looped folder keeps its frame rate
        while not self.stopping.is_set():
            produced_this_pass = produced
            for frame in self.frames():
                if self.stopping.is_set():
                    return
                if not self.realtime and self.wait_consumed():
                    return
                if self.realtime:
                    due = started + produced / self.fps
                    if self.sleep(max(0.0, due - time.monotonic())):
                        return
                self.put_frame(frame)
                produced += 1
            if produced == produced_this_pass:
                raise ValueError(f'No readable frames in {self.description}')
            if not self.loop:
                break
        self.ended = True


class VideoFileSource(ReplaySource):
    kind = 'file'

    def __init__(self, path, realtime=True, loop=False, fps=None):
        if not Path(path).is_file():
            raise ValueError(f'Video file not found: {path}')
        capture = cv2.VideoCapture(str(path))
        native = capture.get(cv2.CAP_PROP_FPS) if capture.isOpened() else 0
        capture.release()
        super().__init__(f'file:{path}', fps or (native if 0 < native <= 120 else 15.0), realtime, loop)
        self.path = str(path)

    def frames(self):
        capture = cv2.VideoCapture(self.path)
        try:
            while not self.stopping.is_set():
                ok, frame = capture.read()
                if not ok:
                    return
                yield frame
        finally:
            capture.release()


class ImageFolderSource(ReplaySource):
    kind = 'dir'

    def __init__(self, directory, fps=15.0, realtime=True, loop=False):
        directory = Path(directory)
        if not directory.is_dir():
            raise ValueError(f'Image folder not found: {directory}')
        self.paths = sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not self.paths:
            raise ValueError(f'No .jpg/.png/.bmp images in {directory}')
        if not 0 < fps <= 120:
            raise ValueError('Folder fps must be between 0 and 120')
        super().__init__(f'dir:{directory}', fps, realtime, loop)

    def frames(self):
        for path in self.paths:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                self.error = f'Skipped unreadable image {path.name}'
                continue
            yield frame


def parse_options(text):
    path, _, query = text.partition('?')
    options = {key: values[-1] for key, values in parse_qs(query).items()}
    return path, options


def flag(options, key, default):
    value = options.get(key)
    if value is None:
        return default
    if value.lower() in ('1', 'true', 'yes', 'on'):
        return True
    if value.lower() in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f'{key} must be 1 or 0')


def number(options, key, default):
    try:
        return float(options[key]) if key in options else default
    except ValueError:
        raise ValueError(f'{key} must be a number') from None


def normalise_uri(uri):
    """Strip the URI and expand the bare-address shorthand (PHONE or PHONE:PORT) to IP Webcam /video."""
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError('Enter the camera address, for example http://192.168.1.23:8080/video')
    uri = uri.strip()
    if len(uri) > 2048:
        raise ValueError('Camera address is too long')
    if '://' in uri or uri.startswith(('file:', 'dir:', 'snapshot:')):
        return uri
    host = uri.rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9.-]+(:[0-9]{1,5})?', host):
        raise ValueError('Camera address must be http://…, snapshot:http://…, file:…, dir:… or the phone IP')
    if ':' not in host:
        host += f':{IP_WEBCAM_PORT}'
    return f'http://{host}/video'


def make_source(uri):
    """Build (not start) a frame source from a --camera URI. Raises ValueError for a bad URI."""
    uri = normalise_uri(uri)
    if uri.startswith('snapshot:'):
        parts = urlsplit(uri[len('snapshot:'):])
        query = parse_qs(parts.query, keep_blank_values=True)
        fps = number({key: values[-1] for key, values in query.items()}, 'fps', 5.0)
        # fps is ours; any other query parameters belong to the camera URL.
        camera_query = urlencode([(key, value) for key, values in query.items() if key != 'fps' for value in values])
        return SnapshotSource(urlunsplit(parts._replace(query=camera_query)), fps)
    if uri.startswith(('http://', 'https://')):
        return MjpegSource(uri)
    if uri.startswith('file:'):
        path, options = parse_options(uri[len('file:'):])
        fps = number(options, 'fps', 0.0) or None
        return VideoFileSource(os.path.expanduser(path), flag(options, 'realtime', True), flag(options, 'loop', False), fps)
    if uri.startswith('dir:'):
        path, options = parse_options(uri[len('dir:'):])
        return ImageFolderSource(os.path.expanduser(path), number(options, 'fps', 15.0),
                                 flag(options, 'realtime', True), flag(options, 'loop', False))
    raise ValueError('Camera address must be http://…, snapshot:http://…, file:…, dir:… or the phone IP')
