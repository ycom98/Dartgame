"""M1-07: pull-based camera sources (IP Webcam / DroidCam MJPEG, snapshots, video file, image folder).

Uses tests/fake_ipwebcam.py, a stdlib stand-in for the phone app serving sim/ frames with the frame
sequence number drawn into each image. Timings printed here are from this machine and localhost.
"""
import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_ipwebcam import FakeIPWebcam, embed_seq, read_seq, sim_frames  # noqa: E402

import camera_source  # noqa: E402
import server  # noqa: E402
from camera_source import (ImageFolderSource, MjpegSource, SnapshotSource, VideoFileSource,  # noqa: E402
                           fit_frame, iter_mjpeg_parts, make_source, redact_url)
from vision import Vision  # noqa: E402
from vision_worker import VisionWorker  # noqa: E402

TOKEN = 'camera-source-token'


def wait_for(predicate, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class ParsingAndUris(unittest.TestCase):
    def jpeg(self, value):
        return cv2.imencode('.jpg', np.full((240, 320, 3), value, np.uint8))[1].tobytes()

    def test_multipart_with_content_length(self):
        parts = [self.jpeg(10), self.jpeg(200)]
        body = b''.join(b'--abc\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n' % len(p) + p + b'\r\n'
                        for p in parts)
        self.assertEqual(list(iter_mjpeg_parts(io.BytesIO(body), 'abc')), parts)

    def test_multipart_without_content_length_uses_the_boundary(self):
        parts = [self.jpeg(10) + b'\n\r\n--ab', self.jpeg(200)]  # binary that looks like line ends
        body = b''.join(b'--abc\r\nContent-Type: image/jpeg\r\n\r\n' + p + b'\r\n' for p in parts) + b'--abc--\r\n'
        self.assertEqual(list(iter_mjpeg_parts(io.BytesIO(body), 'abc')), parts)

    def test_boundary_with_or_without_leading_dashes(self):
        part = self.jpeg(10)
        for header, line in (('--abc', b'--abc'), ('--abc', b'----abc'), ('abc', b'----abc')):
            with self.subTest(header=header, line=line):
                body = line + b'\r\nContent-Type: image/jpeg\r\n\r\n' + part + b'\r\n' + line + b'--\r\n'
                self.assertEqual(list(iter_mjpeg_parts(io.BytesIO(body), header)), [part])

    def test_stream_without_parts_is_an_error_not_silence(self):
        with self.assertRaisesRegex(ValueError, 'no image parts'):
            list(iter_mjpeg_parts(io.BytesIO(b'x' * 100 + b'\n' * 13_000_000), 'abc'))

    def test_uri_forms(self):
        self.assertIsInstance(make_source('http://10.0.0.5:8080/video'), MjpegSource)
        self.assertEqual(make_source('10.0.0.5').url, 'http://10.0.0.5:8080/video')
        self.assertEqual(make_source('10.0.0.5:4747').url, 'http://10.0.0.5:4747/video')
        snapshot = make_source('snapshot:http://10.0.0.5:8080/shot.jpg?fps=2')
        self.assertIsInstance(snapshot, SnapshotSource)
        self.assertEqual((snapshot.url, snapshot.fps), ('http://10.0.0.5:8080/shot.jpg', 2.0))
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(os.path.join(folder, 'a.png'), np.zeros((300, 300, 3), np.uint8))
            source = make_source(f'dir:{folder}?fps=5&realtime=0&loop=1')
            self.assertIsInstance(source, ImageFolderSource)
            self.assertEqual((source.fps, source.realtime, source.loop), (5.0, False, True))
        for bad in ('', 'ftp://x/y', 'two words', 'dir:/no/such/folder', 'file:/no/such.avi', 'http:///video'):
            with self.subTest(uri=bad), self.assertRaises(ValueError):
                make_source(bad)

    def test_login_is_sent_but_never_reported(self):
        source = make_source('http://kapil:secret@10.0.0.5:8080/video')
        self.assertEqual(source.url, 'http://10.0.0.5:8080/video')
        self.assertTrue(source.headers['Authorization'].startswith('Basic '))
        self.assertNotIn('secret', json.dumps(source.status()))
        self.assertEqual(redact_url('http://kapil:secret@10.0.0.5:8080/video'), 'http://kapil:***@10.0.0.5:8080/video')
        self.assertEqual(redact_url('http://kapil:secret@[fe80::1]:8080/video'), 'http://kapil:***@[fe80::1]:8080/video')
        import base64
        encoded = make_source('http://kapil:p%40ss%2Fx@10.0.0.5:8080/video').headers['Authorization']
        self.assertEqual(base64.b64decode(encoded.split()[1]), b'kapil:p@ss/x')

    def test_large_frames_are_downscaled_not_rejected(self):
        self.assertEqual(fit_frame(np.zeros((1440, 2560, 3), np.uint8)).shape, (1080, 1920, 3))
        self.assertEqual(fit_frame(np.zeros((720, 1280, 3), np.uint8)).shape, (720, 1280, 3))

    def test_embedded_sequence_survives_jpeg(self):
        frame = embed_seq(np.full((720, 1280, 3), 90, np.uint8), 4321)
        decoded = cv2.imdecode(cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], cv2.IMREAD_COLOR)
        self.assertEqual(read_seq(decoded), 4321)


class NetworkSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera, cls.frames = sim_frames('left', 1280, 720)

    def test_droidcam_style_stream_and_snapshots(self):
        fake = FakeIPWebcam(self.frames, fps=15, style='droidcam').start()
        sources = []
        try:
            stream = MjpegSource(fake.url + '/video').start(); sources.append(stream)
            shots = SnapshotSource(fake.url + '/shot.jpg', fps=5).start(); sources.append(shots)
            self.assertTrue(wait_for(lambda: stream.seq >= 10 and shots.seq >= 3, 5), (stream.status(), shots.status()))
            frame, _, _ = stream.latest()
            self.assertEqual(frame.shape, (720, 1280, 3))
            self.assertLessEqual(fake.seq - read_seq(frame), 2)
            self.assertEqual(shots.latest()[0].shape, (720, 1280, 3))
        finally:
            for source in sources: source.stop()
            fake.stop()

    def test_connected_stream_without_images_reports_an_error(self):
        import camera_source as module
        from http.server import BaseHTTPRequestHandler

        class Silent(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace;boundary=zzz')
                self.end_headers()
                for _ in range(40):  # keeps sending something that is not a part
                    try:
                        self.wfile.write(b'keepalive\r\n'); self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.1)

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Silent)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        previous = module.NO_FRAME_SECONDS
        module.NO_FRAME_SECONDS = 1.0
        source = MjpegSource(f'http://127.0.0.1:{httpd.server_address[1]}/video').start()
        try:
            self.assertTrue(wait_for(lambda: source.status()['error'], 4), source.status())
            self.assertIn('no images arrived', source.status()['error'])
        finally:
            module.NO_FRAME_SECONDS = previous
            source.stop(); httpd.shutdown(); httpd.server_close()

    def test_bad_address_reports_an_error_and_keeps_retrying(self):
        fake = FakeIPWebcam(self.frames, fps=15).start()
        port = fake.port
        fake.stop()
        source = MjpegSource(f'http://127.0.0.1:{port}/video').start()
        try:
            self.assertTrue(wait_for(lambda: source.error, 3))
            self.assertIn('refused', source.error)
            self.assertFalse(source.status()['connected'])
        finally:
            source.stop()


class ServerWithStream(unittest.TestCase):
    """The plan's acceptance checks against the fake phone at 15 fps, through the HTTP API."""

    def setUp(self):
        self.camera, frames = sim_frames('left', 1280, 720)
        self.fake = FakeIPWebcam(frames, fps=15).start()
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = Vision()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        server.set_camera_source(None)
        self.fake.stop()
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join()
        server.app, server.vision = self.previous

    def request(self, path, body=None, token=TOKEN):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=15)
        payload = json.dumps(body).encode() if body is not None else None
        connection.request('POST' if payload is not None else 'GET', path, payload, {'Authorization': 'Bearer ' + token})
        response = connection.getresponse()
        data, status = response.read(), response.status
        connection.close()
        return status, json.loads(data)

    def state(self):
        return self.request('/api/state')[1]

    def connect(self):
        status, body = self.request('/api/camera/source', {'uri': self.fake.url + '/video', 'expected_revision': 0})
        self.assertEqual(status, 200, body)

    def calibrate(self):
        from sim.scene import calibration_points
        self.assertTrue(wait_for(lambda: self.state()['vision']['fresh'], 5))
        status, started = self.request('/api/calibration/start', {})
        self.assertEqual(status, 200, started)
        status, calibrated = self.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                             'points': calibration_points(self.camera).tolist()})
        self.assertEqual(status, 200, calibrated)
        status, verified = self.request('/api/verify', {'version': calibrated['vision']['version']})
        self.assertEqual(status, 200, verified)
        self.assertEqual(verified['vision']['phase'], 'ready')

    def test_connected_rate_and_frame_age(self):
        self.connect()
        time.sleep(2.5)
        samples = [self.state()['vision']['source'] for _ in range(5) if not time.sleep(0.2)]
        for source in samples:
            self.assertTrue(source['connected'], source)
            self.assertGreaterEqual(source['fps'], 12, source)
            self.assertLess(source['last_frame_age'], 0.5, source)
        self.assertEqual(samples[-1]['kind'], 'mjpeg')
        self.assertEqual((samples[-1]['width'], samples[-1]['height']), (1280, 720))
        self.assertGreaterEqual(samples[-1]['processed_fps'], 12, samples[-1])
        print(f"\nM1-07 15 fps stub: received {samples[-1]['fps']} fps, processed {samples[-1]['processed_fps']} fps, "
              f"frame age {max(s['last_frame_age'] for s in samples) * 1000:.0f} ms max")

    def test_processing_lags_the_stub_by_at_most_one_frame(self):
        self.connect()
        self.calibrate()  # aligned frames run the full warp + segmentation path
        lags = []
        vision = server.vision
        original = vision.ingest

        def measured(frame):
            lags.append(self.fake.seq - read_seq(frame))
            return original(frame)

        vision.ingest = measured
        try:
            time.sleep(4)
        finally:
            del vision.ingest
        self.assertGreater(len(lags), 40)
        print(f'\nM1-07 lag (stub newest seq - processed seq) over {len(lags)} frames: '
              f'{ {lag: lags.count(lag) for lag in sorted(set(lags))} }')
        self.assertLessEqual(max(lags), 1)

    def test_drop_and_recovery_keep_calibration(self):
        self.connect()
        self.calibrate()
        stopped = time.monotonic()
        self.fake.stop()
        self.assertTrue(wait_for(lambda: not self.state()['vision']['source']['connected'], 5))
        detected = time.monotonic() - stopped
        # Stay down past the 5 s freshness window, like a Wi-Fi drop.
        self.assertTrue(wait_for(lambda: self.state()['vision']['phase'] == 'camera_disconnected', 6))
        self.fake = FakeIPWebcam(self.fake.frames, fps=15, port=self.fake.port).start()
        restarted = time.monotonic()
        self.assertTrue(wait_for(lambda: self.state()['vision']['fresh'], 6))
        resumed = time.monotonic() - restarted
        state = self.state()['vision']
        self.assertEqual(state['phase'], 'needs_alignment')
        self.assertGreaterEqual(state['source']['reconnects'], 1)
        status, aligned = self.request('/api/align', {})
        self.assertEqual(status, 200, aligned)
        self.assertEqual(aligned['vision']['phase'], 'review_overlay')
        print(f'\nM1-07 drop: disconnected shown after {detected:.2f} s; frames resumed {resumed:.2f} s after restart; '
              'alignment check passed without recalibration')
        self.assertLess(detected, 5)
        self.assertLess(resumed, 6)

    def test_source_endpoint_validation(self):
        self.assertEqual(self.request('/api/camera/source', {'uri': self.fake.url + '/video', 'expected_revision': 0},
                                      token='wrong')[0], 401)
        self.assertEqual(self.request('/api/camera/source', {'uri': self.fake.url + '/video'})[0], 400)
        self.assertEqual(self.request('/api/camera/source', {'uri': 'ftp://nope', 'expected_revision': 0})[0], 400)
        self.assertEqual(self.request('/api/camera/source', {'uri': 5, 'expected_revision': 0})[0], 400)
        status, body = self.request('/api/camera/source', {'uri': self.fake.url + '/video', 'expected_revision': 7})
        self.assertEqual(status, 409)
        self.assertIsNone(body['vision']['source'])
        self.assertEqual(self.request('/api/camera/source', {'expected_revision': 0})[0], 400)  # no implicit disconnect
        self.connect()
        self.assertTrue(wait_for(lambda: self.state()['vision']['source']['connected'], 3))
        revision = self.state()['revision']
        self.assertEqual(revision, 1, 'a source switch bumps the revision')
        self.assertEqual(self.request('/api/camera/source', {'uri': None, 'expected_revision': 0})[0], 409)
        status, body = self.request('/api/camera/source', {'uri': None, 'expected_revision': revision})
        self.assertEqual(status, 200)
        self.assertIsNone(body['vision']['source'])
        self.assertEqual(body['revision'], 2)

    def test_switching_source_requires_a_new_alignment_check(self):
        self.connect()
        self.calibrate()
        status, body = self.request('/api/camera/source', {'uri': 'snapshot:' + self.fake.url + '/shot.jpg?fps=8',
                                                           'expected_revision': self.state()['revision']})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['vision']['source']['kind'], 'snapshot')
        self.assertFalse(body['vision']['verified'])
        self.assertTrue(wait_for(lambda: self.state()['vision']['phase'] == 'needs_alignment', 3))
        self.assertEqual(self.request('/api/align', {})[0], 200)


class ReplayMatchesDirectFeeding(unittest.TestCase):
    """dir: and file: sources give the same proposals as calling Vision.ingest on the same frames."""

    @classmethod
    def setUpClass(cls):
        from sim import camera_for_mount
        from sim.scene import Dart, calibration_points, render_clean
        cls.camera = camera_for_mount('left', 1280, 720)
        cls.points = calibration_points(cls.camera).tolist()
        empty = render_clean(cls.camera, [])
        first = render_clean(cls.camera, [Dart(x=40.0, y=-60.0, tilt=12.0)])
        second = render_clean(cls.camera, [Dart(x=-70.0, y=95.0, tilt=10.0)])
        cls.empty = empty
        cls.sequence = [empty] * 4 + [first] * 5 + [empty] * 4 + [second] * 5
        cls.folder = tempfile.TemporaryDirectory()
        for index, frame in enumerate(cls.sequence):
            cv2.imwrite(os.path.join(cls.folder.name, f'{index:06d}.png'), frame)
        cls.video = os.path.join(cls.folder.name, 'replay.avi')
        writer = cv2.VideoWriter(cls.video, cv2.VideoWriter_fourcc(*'MJPG'), 15, (1280, 720))
        for frame in cls.sequence:
            writer.write(frame)
        writer.release()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def calibrated_vision(self, empty):
        vision = Vision()
        vision.ingest(empty)
        vision.calibrate(self.points)
        return vision

    @staticmethod
    def outcome(vision):
        proposal = vision.proposal
        return None if proposal is None else (proposal['label'], round(proposal['x'], 3), round(proposal['y'], 3))

    def direct(self, frames, empty):
        vision = self.calibrated_vision(empty)
        results = []
        for frame in frames:
            vision.ingest(frame)
            results.append(self.outcome(vision))
        return results

    def replay(self, uri, empty):
        vision = self.calibrated_vision(empty)
        worker = VisionWorker(lambda: vision, max_fps=0)
        results = []
        worker.on_ingest = lambda frame, seq: results.append(self.outcome(vision))
        source = make_source(uri)
        worker.set_source(source)
        try:
            self.assertTrue(wait_for(lambda: len(results) >= len(self.sequence), 30), (len(results), source.status()))
            time.sleep(0.2)
            self.assertTrue(source.status()['ended'])
        finally:
            worker.stop()
        return results

    def test_folder_replay(self):
        expected = self.direct([Path(p).read_bytes() for p in sorted(Path(self.folder.name).glob('*.png'))], self.empty)
        self.assertEqual({item[0] for item in expected if item}, {'S18', 'S7'}, expected)
        self.assertEqual(self.replay(f'dir:{self.folder.name}?realtime=0', self.empty), expected)

    def test_video_file_replay(self):
        capture = cv2.VideoCapture(self.video)
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        capture.release()
        self.assertEqual(len(frames), len(self.sequence))
        # Calibrate on the video's own (compressed) empty frame, as a live session would.
        expected = self.direct(frames, frames[0])
        self.assertEqual({item[0] for item in expected if item}, {'S18', 'S7'}, expected)
        self.assertEqual(self.replay(f'file:{self.video}?realtime=0', frames[0]), expected)

    def test_realtime_folder_paces_frames(self):
        source = ImageFolderSource(self.folder.name, fps=30).start()
        try:
            started = time.monotonic()
            self.assertTrue(wait_for(lambda: source.ended, 5))
            elapsed = time.monotonic() - started
        finally:
            source.stop()
        self.assertEqual(source.seq, len(self.sequence))
        self.assertGreater(elapsed, (len(self.sequence) - 1) / 30 * 0.8)

    def test_looped_single_image_keeps_its_frame_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(os.path.join(folder, 'board.png'), self.empty)
            source = ImageFolderSource(folder, fps=10, loop=True).start()
            try:
                time.sleep(1.5)
                fps = source.status()['fps']
            finally:
                source.stop()
        self.assertGreater(fps, 8)
        self.assertLess(fps, 12)

    def test_oversized_folder_frames_are_downscaled(self):
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(os.path.join(folder, 'big.png'), cv2.resize(self.empty, (2560, 1440)))
            source = ImageFolderSource(folder, realtime=False).start()
            try:
                self.assertTrue(wait_for(lambda: source.latest()[0] is not None, 5))
                self.assertEqual(source.latest()[0].shape, (1080, 1920, 3))
            finally:
                source.stop()


class CommandLine(unittest.TestCase):
    def test_server_starts_with_camera_and_without_openssl(self):
        from sim.scene import render_clean
        from sim import camera_for_mount
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as empty_path:
            cv2.imwrite(os.path.join(folder, 'board.png'), render_clean(camera_for_mount('left', 1280, 720), []))
            with __import__('socket').socket() as probe:
                probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
            environment = {**os.environ, 'PATH': empty_path}  # no openssl on PATH
            process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'server.py'), '--http', '--host', '127.0.0.1',
                                        '--port', str(port), '--camera', f'dir:{folder}?loop=1&fps=10'],
                                       cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                lines = []
                while not any(line.startswith('Controller:') for line in lines):
                    line = process.stdout.readline()
                    self.assertTrue(line, ''.join(lines))
                    lines.append(line)
                token = next(l for l in lines if l.startswith('Controller:')).split('t=')[1].strip()

                def source():
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                    connection.request('GET', '/api/state', headers={'Authorization': 'Bearer ' + token})
                    state = json.loads(connection.getresponse().read())
                    connection.close()
                    return state['vision']['source']

                self.assertTrue(wait_for(lambda: source()['connected'], 5))
                self.assertEqual(source()['kind'], 'dir')
            finally:
                process.terminate(); process.wait(5); process.stdout.close()


if __name__ == '__main__':
    unittest.main()
