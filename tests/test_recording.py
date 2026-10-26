"""M1-14: record a camera session, derive labels, replay it, draw the contact sheet.

A 3-turn camera game is played against tests/fake_ipwebcam.py (sim/ scenes, one more dart each time),
with one camera dart corrected by the host. The recording must replay to the identical detection sequence.
"""
import http.client
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402
from fake_ipwebcam import FakeIPWebcam  # noqa: E402

TOKEN = 'recording-token'
# (sector, radius mm): nine darts the sim detector reads correctly as they build up on the board.
PLAN = [(20, 60), (6, 103), (3, 135), (11, 135), (19, 103), (15, 60), (1, 135), (17, 60), (13, 103)]


def wait_for(predicate, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class RecordedSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from core import SECTORS
        from sim import camera_for_mount
        from sim.scene import Dart, calibration_points, render_clean
        camera = camera_for_mount('left', 1280, 720)
        darts = []
        for sector, radius in PLAN:
            angle = math.radians(SECTORS.index(sector) * 18)
            darts.append(Dart(x=radius * math.sin(angle), y=-radius * math.cos(angle), tilt=11.0))
        scenes = [render_clean(camera, darts[:k]) for k in range(10)]
        cls.folder = tempfile.TemporaryDirectory()
        cls.server = server
        cls.previous = (server.app, server.vision, server.RECORDINGS_ROOT)
        server.RECORDINGS_ROOT = Path(cls.folder.name)
        from vision import Vision
        server.app = server.App(TOKEN)
        server.vision = Vision()
        cls.fake = FakeIPWebcam([scenes[0]], fps=15).start()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        try:
            cls.play_session(scenes, calibration_points(camera).tolist())
        finally:
            server.set_camera_source(None)
            cls.fake.stop()
        cls.directory = Path(server.recorder.directory)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        cls.server.app, cls.server.vision, cls.server.RECORDINGS_ROOT = cls.previous
        cls.server.recorder = None
        cls.folder.cleanup()

    @classmethod
    def request(cls, path, body=None):
        port = cls.httpd.server_address[1]
        if body is not None:
            body = with_revision(port, TOKEN, path, body)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        if status != 200:
            raise AssertionError(f'{path}: {status} {data.get("error")}')
        return data

    @classmethod
    def play_session(cls, scenes, points):
        cls.request('/api/camera/source', {'uri': cls.fake.url + '/video'})
        assert wait_for(lambda: cls.request('/api/state')['vision']['fresh'], 5)
        cls.request('/api/record', {'enabled': True, 'notes': {'mount': 'sim left', 'lighting': 'sim'}})
        cls.request('/api/record/notes', {'notes': {'phone': 'fake IP Webcam 1280x720 15 fps'}})
        started = cls.request('/api/calibration/start', {})
        calibrated = cls.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'], 'points': points})
        cls.request('/api/verify', {'version': calibrated['vision']['version']})
        cls.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        cls.request('/api/camera/auto_commit', {'paused': True})
        for k in range(1, 10):
            cls.fake.set_frames([scenes[k]])
            pending = wait_for(lambda: cls.request('/api/state')['camera']['pending'], 5, step=0.03)
            assert pending, f'dart {k} not detected'
            if k == 5:  # the host corrects this one
                cls.request('/api/throw', {'value': 3, 'multiplier': 1, 'replaces_proposal_id': pending['id']})
            else:
                cls.request('/api/throw', {'proposal_id': pending['id']})
            if k % 3 == 0:
                cls.request('/api/next', {})
        time.sleep(0.5)
        cls.status = cls.request('/api/state')['recording']
        cls.request('/api/record', {'enabled': False})

    def test_recording_files_and_status(self):
        self.assertTrue(self.status['active'])
        self.assertGreater(self.status['frames'], 50)
        self.assertGreater(self.status['free_bytes'], 0)
        self.assertEqual(self.status['skipped_frames'], 0)
        session = json.loads((self.directory / 'session.json').read_text())
        self.assertEqual(session['notes']['mount'], 'sim left')
        self.assertIn('phone', session['notes'])
        self.assertEqual(session['source']['kind'], 'mjpeg')
        jpegs = sorted((self.directory / 'frames').glob('*.jpg'))
        self.assertEqual(len(jpegs), session['frames'])
        self.assertEqual(jpegs[0].read_bytes()[:2], b'\xff\xd8')  # stored as received
        self.assertFalse(self.request('/api/state')['recording']['active'])
        self.assertGreater(self.request('/api/record/disk')['free_bytes'], 0)

    def test_labels_have_nine_darts_with_exactly_one_corrected(self):
        from tools.make_labels import main as make_labels
        labels = make_labels([str(self.directory)])
        self.assertEqual(len(labels), 9)
        self.assertEqual([label['source'] for label in labels].count('corrected'), 1)
        self.assertEqual([label['source'] for label in labels].count('accepted'), 8)
        corrected = next(label for label in labels if label['source'] == 'corrected')
        self.assertEqual((corrected['truth_label'], corrected['detection_label']), ('S3', 'T19'))
        self.assertEqual([(label['turn'], label['dart']) for label in labels][:4], [(1, 1), (1, 2), (1, 3), (2, 1)])
        self.assertTrue(all(label['frame_seq_before'] is not None and label['frame_seq_after'] > label['frame_seq_before']
                            for label in labels))
        self.assertTrue((self.directory / 'labels.jsonl').exists())

    def test_replay_reproduces_the_identical_detection_sequence(self):
        from tools.replay_recording import main as replay
        report = replay([str(self.directory), '--out', str(self.directory / 'replay.json')])
        self.assertTrue(report['replay']['identical'], report['replay'])
        self.assertGreater(report['replay']['frames_processed'], 50)
        self.assertEqual(report['detection']['with_detection'], 9)
        self.assertAlmostEqual(report['detection']['exact_score_accuracy'], 8 / 9, places=3)

    def test_contact_sheet_has_nine_panels(self):
        from tools.contact_sheet import main as contact_sheet
        import cv2
        out = self.directory / 'sheet.png'
        self.assertEqual(contact_sheet([str(self.directory), '--out', str(out)]), 9)
        image = cv2.imread(str(out))
        self.assertIsNotNone(image)
        self.assertGreater(image.shape[0], 3 * 240)


class MidSessionRecording(RecordedSession):
    """Recording switched on from the setup page after calibration and after a first dart."""

    @classmethod
    def play_session(cls, scenes, points):
        cls.request('/api/camera/source', {'uri': cls.fake.url + '/video'})
        assert wait_for(lambda: cls.request('/api/state')['vision']['fresh'], 5)
        started = cls.request('/api/calibration/start', {})
        calibrated = cls.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'], 'points': points})
        cls.request('/api/verify', {'version': calibrated['vision']['version']})
        cls.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        cls.request('/api/camera/auto_commit', {'paused': True})
        for k in range(1, 4):
            if k == 2:
                cls.request('/api/record', {'enabled': True})
            cls.fake.set_frames([scenes[k]])
            pending = wait_for(lambda: cls.request('/api/state')['camera']['pending'], 5, step=0.03)
            assert pending, f'dart {k} not detected'
            cls.request('/api/throw', {'proposal_id': pending['id']})
        time.sleep(0.5)
        cls.status = cls.request('/api/state')['recording']
        cls.request('/api/record', {'enabled': False})

    def test_recording_files_and_status(self):
        self.assertTrue((self.directory / 'start' / 'reference.png').exists())

    def test_labels_have_nine_darts_with_exactly_one_corrected(self):
        from tools.make_labels import make_labels
        labels = make_labels(self.directory)
        self.assertEqual([label['truth_label'] for label in labels], ['T6', 'S3'])

    def test_replay_reproduces_the_identical_detection_sequence(self):
        from tools.replay_recording import replay
        result = replay(self.directory)
        self.assertTrue(result['started_from_saved_calibration'])
        self.assertTrue(result['identical'], result)

    def test_contact_sheet_has_nine_panels(self):
        from tools.contact_sheet import make_sheet
        self.assertEqual(make_sheet(self.directory)[1], 2)


class DiskGuard(unittest.TestCase):
    def test_refuses_to_start_and_stops_when_disk_is_low(self):
        from recorder import Recorder
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'GB free'):
                Recorder(Path(folder) / 'a', lambda: None, min_free_bytes=10 ** 18).start()
            recorder = Recorder(Path(folder) / 'b', lambda: None, min_free_bytes=1).start()
            recorder.min_free_bytes = 10 ** 18  # the disk "fills up"
            self.assertTrue(wait_for(lambda: not recorder.active, 4))
            self.assertIn('GB free', recorder.status()['error'])


if __name__ == '__main__':
    unittest.main()
