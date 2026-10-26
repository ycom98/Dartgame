"""M1-10: every write needs the current expected_revision; start scores are integers only."""
import http.client
import json
import threading
import time
import os
import sys
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOKEN = 'hardening-token'
POINTS = [[400, 150], [650, 400], [400, 650], [150, 400]]
WRITES = {
    '/api/game': {'names': ['A', 'B'], 'camera': False},
    '/api/throw': {'value': 20},
    '/api/next': {},
    '/api/undo': {},
    '/api/correct': {'dart_index': 0, 'value': 1},
    '/api/turn/fill_misses': {},
    '/api/camera/source': {'uri': None},
    '/api/camera/test': {'uri': 'http://127.0.0.1:9/video'},
    '/api/camera/auto_commit': {'paused': True},
    '/api/camera/mount_side': {'mount_side': 'top'},
    '/api/camera/reset': {},
    '/api/calibration/start': {},
    '/api/calibration/cancel': {},
    '/api/calibrate': {'snapshot_id': 'x', 'points': POINTS},
    '/api/verify': {'version': 0},
    '/api/align': {},
    '/api/baseline': {},
}


class WriteHardening(unittest.TestCase):
    def setUp(self):
        import server
        from vision import Vision
        self.server = server
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = Vision()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close()
        self.server.app, self.server.vision = self.previous

    def request(self, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def snapshot(self):
        state = self.request('/api/state')[1]
        return state['game'], state['revision'], state['camera']['auto_commit'], state['vision']['mount_side']

    def test_every_write_needs_an_integer_revision_and_a_stale_one_changes_nothing(self):
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'expected_revision': 0})[0], 200)
        self.assertEqual(self.request('/api/throw', {'value': 20, 'expected_revision': 1})[0], 200)
        before = self.snapshot()
        for path, body in WRITES.items():
            with self.subTest(path=path):
                for bad in (None, '2', 2.0, True):
                    payload = dict(body) if bad is None else {**body, 'expected_revision': bad}
                    status, data = self.request(path, payload)
                    self.assertEqual(status, 400, (bad, data))
                status, data = self.request(path, {**body, 'expected_revision': 1})  # current is 2
                self.assertEqual(status, 409, data)
                self.assertEqual(data['revision'], 2)
                self.assertEqual(self.snapshot(), before)

    def test_frame_push_is_the_only_write_without_a_revision(self):
        import cv2
        import numpy as np
        ok, png = cv2.imencode('.png', np.full((300, 300, 3), 90, np.uint8))
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)
        connection.request('POST', '/api/frame', png.tobytes(), {'Authorization': 'Bearer ' + TOKEN})
        self.assertEqual(connection.getresponse().status, 200)
        connection.close()

    def test_start_must_be_an_integer_301_or_501(self):
        for start in (301.0, '301', True, 401, None):
            with self.subTest(start=start):
                status, _ = self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'start': start,
                                                       'expected_revision': 0})
                self.assertEqual(status, 400)
        self.assertIsNone(self.request('/api/state')[1]['game'])
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'start': 501,
                                                    'expected_revision': 0})[0], 200)

    def test_legacy_proposal_true_and_unknown_or_replaced_ids_record_nothing(self):
        vision = self.server.vision
        import cv2
        import numpy as np
        rng = np.random.default_rng(3)
        frame = np.full((800, 800, 3), 80, np.uint8)
        for _ in range(1600):
            x, y = rng.integers(155, 646, 2)
            cv2.circle(frame, (int(x), int(y)), int(rng.integers(2, 6)), tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
        vision.frame = frame; vision.timestamp = time.time()
        vision.calibrate(POINTS)
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'expected_revision': 0})[0], 200)
        self.server.worker.call(lambda v: None)  # let the base reset queued by the game start finish
        vision.proposal = {'value': 20, 'multiplier': 3, 'label': 'T20'}
        from api_helper import pending_id
        first = pending_id(self.server)
        self.assertIsNotNone(first)
        self.assertEqual(self.request('/api/throw', {'proposal': True, 'expected_revision': 1})[0], 400)
        self.assertEqual(self.request('/api/throw', {'proposal_id': 'unknown', 'expected_revision': 1})[0], 409)
        vision.proposal = {'value': 19, 'multiplier': 3, 'label': 'T19'}  # the detection changed after the host looked
        self.assertNotEqual(pending_id(self.server), first)
        status, data = self.request('/api/throw', {'proposal_id': first, 'expected_revision': 1})
        self.assertEqual(status, 409)
        self.assertIn('Proposal changed', data['error'])
        vision.proposal = None  # retracted
        self.assertIsNone(pending_id(self.server))
        self.assertEqual(self.request('/api/throw', {'proposal_id': first, 'expected_revision': 1})[0], 409)
        self.assertEqual(self.request('/api/state')[1]['game']['darts'], [])


if __name__ == '__main__':
    unittest.main()
