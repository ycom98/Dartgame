"""M1-12: camera darts through the whole server, from a (fake) IP Webcam stream to committed darts.

The fake phone serves sim/ scenes (empty board, then one more dart each time); the test switches
scenes like darts landing. Owner decisions: #1 auto-commit after ~3 s unless corrected (pausable),
#6 one tap fixes a pending dart. Timings are printed; they are localhost and sim numbers.
"""
import http.client
import json
import os
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402
from fake_ipwebcam import FakeIPWebcam  # noqa: E402

TOKEN = 'camera-flow-token'
DART_SPOTS = [(40.0, -60.0, 'S18'), (-70.0, 95.0, 'S7'), (98.0, 31.8, 'T10')]


def wait_for(predicate, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class CameraFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import camera_for_mount
        from sim.scene import Dart, calibration_points, render_clean
        cls.camera = camera_for_mount('left', 1280, 720)
        cls.points = calibration_points(cls.camera).tolist()
        darts = [Dart(x=x, y=y, tilt=12.0) for x, y, _ in DART_SPOTS]
        cls.scenes = [render_clean(cls.camera, darts[:k]) for k in range(4)]

    def setUp(self):
        import server
        from vision import Vision
        self.server = server
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = Vision()
        self.fake = FakeIPWebcam([self.scenes[0]], fps=15).start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.connect_and_calibrate()

    def tearDown(self):
        self.server.set_camera_source(None)
        self.fake.stop()
        self.httpd.shutdown(); self.httpd.server_close()
        self.server.app, self.server.vision = self.previous

    def request(self, path, body=None, raw_revision=False):
        port = self.httpd.server_address[1]
        if body is not None and not raw_revision:
            body = with_revision(port, TOKEN, path, body)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def state(self):
        return self.request('/api/state')[1]

    def connect_and_calibrate(self):
        self.assertEqual(self.request('/api/camera/source', {'uri': self.fake.url + '/video'})[0], 200)
        self.assertTrue(wait_for(lambda: self.state()['vision']['fresh'], 5))
        status, started = self.request('/api/calibration/start', {})
        self.assertEqual(status, 200, started)
        status, calibrated = self.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                             'points': self.points})
        self.assertEqual(status, 200, calibrated)
        self.assertEqual(self.request('/api/verify', {'version': calibrated['vision']['version']})[0], 200)
        status, game = self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        self.assertEqual(status, 200, game)
        self.server.worker.call(lambda v: None)

    def throw_dart(self, k):
        """Show scene k (k darts in the board); return (pending, seconds until it showed in /api/state)."""
        self.fake.set_frames([self.scenes[k]])
        served = time.monotonic()
        pending = wait_for(lambda: self.state()['camera']['pending'], 5, step=0.02)
        return pending, time.monotonic() - served

    def test_accept_commits_exactly_the_detection_shown(self):
        self.server.app.flow.paused = True
        pending, latency = self.throw_dart(1)
        self.assertIsNotNone(pending)
        self.assertEqual(pending['label'], DART_SPOTS[0][2])
        self.assertIsNone(pending['commit_in'])  # paused: waits for Accept
        print(f'\nM1-12 pending dart visible in /api/state {latency:.2f} s after the frame was served')
        self.assertLess(latency, 1.5)
        status, state = self.request('/api/throw', {'proposal_id': pending['id']})
        self.assertEqual(status, 200, state)
        self.assertEqual(state['game']['darts'][0]['score'], 18)
        commit = [e for e in self.request('/api/events')[1]['events'] if e['type'] == 'commit'][-1]
        self.assertEqual((commit['source'], commit['proposal']['id']), ('accepted', pending['id']))
        self.assertEqual(self.request('/api/throw', {'proposal_id': pending['id']})[0], 409)
        self.assertEqual(len(self.state()['game']['darts']), 1)

    def test_one_tap_correction_replaces_the_pending_dart(self):
        self.server.app.flow.paused = True
        pending, _ = self.throw_dart(1)
        status, state = self.request('/api/throw', {'value': 1, 'multiplier': 1, 'replaces_proposal_id': pending['id']})
        self.assertEqual(status, 200, state)
        self.assertEqual(state['game']['darts'][0]['score'], 1)
        self.assertIsNone(state['camera']['pending'])
        time.sleep(1.0)  # the replaced detection must not come back
        self.assertIsNone(self.state()['camera']['pending'])
        commit = [e for e in self.request('/api/events')[1]['events'] if e['type'] == 'commit'][-1]
        self.assertEqual(commit['source'], 'corrected')
        self.assertEqual((commit['proposal']['label'], commit['dart']['score']), ('S18', 1))

    def test_auto_commit_after_about_three_seconds_and_pause(self):
        pending, _ = self.throw_dart(1)
        appeared = time.monotonic()
        self.assertIsNotNone(pending['commit_in'])
        self.assertTrue(wait_for(lambda: len(self.state()['game']['darts']) == 1, 6, step=0.05))
        waited = time.monotonic() - appeared
        print(f'\nM1-12 auto-commit {waited:.2f} s after the pending dart appeared (setting 3 s)')
        self.assertGreater(waited, 2.0)
        self.assertLess(waited, 4.0)
        commit = [e for e in self.request('/api/events')[1]['events'] if e['type'] == 'commit'][-1]
        self.assertEqual((commit['source'], commit['dart']['score']), ('auto', 18))
        # Paused: the next dart waits.
        self.assertEqual(self.request('/api/camera/auto_commit', {'paused': True})[0], 200)
        pending, _ = self.throw_dart(2)
        self.assertEqual(pending['label'], 'S7')
        time.sleep(4)
        self.assertEqual(len(self.state()['game']['darts']), 1)
        self.assertEqual(self.request('/api/camera/auto_commit', {'paused': False})[0], 200)
        self.assertTrue(wait_for(lambda: len(self.state()['game']['darts']) == 2, 6))

    def test_three_darts_then_end_turn_and_correct_a_committed_dart(self):
        self.server.app.flow.paused = True
        for k in (1, 2):
            pending, _ = self.throw_dart(k)
            self.assertEqual(pending['label'], DART_SPOTS[k - 1][2])
            self.assertEqual(self.request('/api/throw', {'proposal_id': pending['id']})[0], 200)
        # The third dart missed the board: the host ends the turn and the miss is filled in (decision #5).
        status, state = self.request('/api/turn/fill_misses', {})
        self.assertEqual(status, 200, state)
        self.assertEqual([d.get('filled', False) for d in state['game']['darts']], [False, False, True])
        revision = state['revision']
        status, state = self.request('/api/correct', {'dart_index': 0, 'value': 18, 'multiplier': 3})
        self.assertEqual(status, 200, state)
        self.assertEqual(state['revision'], revision + 1)
        self.assertEqual([d['score'] for d in state['game']['darts']], [54, 7, 0])
        self.assertEqual(self.request('/api/next', {})[0], 200)


if __name__ == '__main__':
    unittest.main()
