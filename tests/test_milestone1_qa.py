"""Independent milestone-1 acceptance checks; synthetic fixtures are not live-board evidence."""
import http.client
import json
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
POINTS = [[400, 150], [650, 400], [400, 650], [150, 400]]


class MilestoneOneQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from http.server import ThreadingHTTPServer
        cls.module = server
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join()

    def setUp(self):
        import cv2
        import numpy as np
        from vision import Vision
        self.cv2, self.np = cv2, np
        self.module.vision = Vision()
        self.module.app = self.module.App('independent-m1-qa')
        rng = np.random.default_rng(8741)
        self.image = np.full((800, 800, 3), 70, np.uint8)
        for _ in range(1500):
            x, y = rng.integers(165, 636, 2)
            if (x - 400) ** 2 + (y - 400) ** 2 < 230 ** 2:
                cv2.circle(self.image, (int(x), int(y)), int(rng.integers(2, 6)),
                           tuple(int(v) for v in rng.integers(0, 256, 3)), -1)

    def request(self, path, body=None, raw=None, token='independent-m1-qa'):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        headers = {'Authorization': 'Bearer ' + token}
        connection.request('POST' if payload is not None else 'GET', path, payload, headers)
        response = connection.getresponse()
        data, status = response.read(), response.status
        mime = response.getheader('Content-Type', '')
        connection.close()
        return status, json.loads(data) if 'application/json' in mime else data

    def upload(self, image=None):
        ok, encoded = self.cv2.imencode('.png', self.image if image is None else image)
        self.assertTrue(ok)
        status, result = self.request('/api/frame', raw=encoded.tobytes())
        self.assertEqual(status, 200, result)

    def begin(self):
        status, result = self.request('/api/calibration/start', {})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['vision']['phase'], 'calibrating')
        self.assertFalse(result['vision']['verified'])
        return result['snapshot']['snapshot_id']

    def finish(self, snapshot):
        status, result = self.request('/api/calibrate', {'snapshot_id': snapshot, 'points': POINTS})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['vision']['phase'], 'review_overlay')
        return result

    def ready(self):
        self.upload()
        result = self.finish(self.begin())
        status, result = self.request('/api/verify', {'version': result['vision']['version']})
        self.assertEqual(status, 200, result)
        self.assertTrue(result['vision']['verified'])
        self.assertEqual(result['vision']['phase'], 'ready')
        return result

    def test_frozen_reference_maps_onto_new_live_frame_before_verification(self):
        self.upload()
        snapshot = self.begin()
        status, jpeg_before = self.request('/api/calibration/image?id=' + snapshot)
        self.assertEqual(status, 200)
        transform = self.np.float32([[1, 0, 11], [0, 1, -7]])
        moved = self.cv2.warpAffine(self.image, transform, (800, 800))
        self.upload(moved)
        status, jpeg_after = self.request('/api/calibration/image?id=' + snapshot)
        self.assertEqual(status, 200)
        self.assertEqual(jpeg_before, jpeg_after, 'Calibration image must stay fixed while live frames change')
        result = self.finish(snapshot)
        expected = self.np.float32(POINTS) + [11, -7]
        error = self.np.linalg.norm(self.np.asarray(result['vision']['overlay']) - expected, axis=1)
        self.assertLess(float(error.max()), 3)
        self.assertTrue(self.np.array_equal(self.module.vision.frame, moved),
                        'Calibration must not replace the live frame with the frozen reference')
        status, _ = self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        self.assertEqual(status, 400, 'Camera gameplay must wait for explicit overlay review')
        status, verified = self.request('/api/verify', {'version': result['vision']['version']})
        self.assertEqual(status, 200, verified)
        status, game = self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        self.assertEqual(status, 200, game)
        self.assertTrue(game['vision']['verified'])

    def test_snapshot_replacement_invalid_points_and_cancel_never_keep_old_readiness(self):
        self.ready()
        old = self.begin()
        new = self.begin()
        status, _ = self.request('/api/calibrate', {'snapshot_id': old, 'points': POINTS})
        self.assertEqual(status, 400)
        status, result = self.request('/api/calibrate', {'snapshot_id': new, 'points': [[0, 0]] * 4})
        self.assertEqual(status, 400)
        self.assertFalse(self.module.vision.verified())
        status, result = self.request('/api/calibration/cancel', {})
        self.assertEqual(status, 200, result)
        self.assertFalse(result['vision']['calibration_active'])
        self.assertFalse(result['vision']['verified'])
        self.assertEqual(self.request('/api/calibration/image?id=' + new)[0], 400)

    def test_snapshot_expiry_does_not_restore_ready_state_even_with_fresh_stream(self):
        self.upload()
        vision = self.module.vision
        started = time.time()
        with patch('vision.time.time', return_value=started):
            capture = vision.begin_calibration()
        with patch('vision.time.time', return_value=started + capture['expires_in'] + 1):
            self.upload()
            status, _ = self.request('/api/calibrate',
                                     {'snapshot_id': capture['snapshot_id'], 'points': POINTS})
            self.assertEqual(status, 400)
            self.assertFalse(vision.verified())
            self.assertFalse(vision.state()['calibration_active'])

    def test_version_change_and_stream_gap_require_new_overlay_review(self):
        result = self.ready()
        old_version = result['vision']['version']
        status, result = self.request('/api/align', {})
        self.assertEqual(status, 200, result)
        self.assertFalse(result['vision']['verified'])
        self.assertEqual(self.request('/api/verify', {'version': old_version})[0], 400)
        self.assertEqual(self.request('/api/verify', {'version': result['vision']['version']})[0], 200)
        self.module.vision.timestamp = time.time() - 6
        status, result = self.request('/api/state')
        self.assertEqual(result['vision']['phase'], 'camera_disconnected')
        self.assertFalse(result['vision']['verified'])
        self.upload()
        self.assertEqual(self.request('/api/state')[1]['vision']['phase'], 'needs_alignment')
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': True})[0], 400)

    def test_resolution_change_during_selection_rejects_old_snapshot(self):
        self.upload()
        snapshot = self.begin()
        smaller = self.cv2.resize(self.image, (600, 600))
        self.upload(smaller)
        status, _ = self.request('/api/calibrate', {'snapshot_id': snapshot, 'points': POINTS})
        self.assertEqual(status, 400)
        state = self.request('/api/state')[1]['vision']
        self.assertFalse(state['aligned'])
        self.assertFalse(state['verified'])
        self.assertEqual((state['width'], state['height']), (600, 600))

    def test_snapshot_routes_require_pairing_and_http_points_require_snapshot(self):
        self.upload()
        snapshot = self.begin()
        self.assertEqual(self.request('/api/calibration/image?id=' + snapshot, token='wrong')[0], 401)
        self.assertEqual(self.request('/api/calibration/start', {}, token='wrong')[0], 401)
        self.assertEqual(self.request('/api/calibrate', {'points': POINTS})[0], 400)
        self.assertFalse(self.module.vision.verified())

    def test_failed_camera_game_does_not_replace_active_manual_game(self):
        status, result = self.request('/api/game', {'names': ['Keep', 'Me'], 'camera': False})
        self.assertEqual(status, 200, result)
        self.request('/api/throw', {'value': 20, 'multiplier': 3})
        before = self.request('/api/state')[1]['game']
        self.assertEqual(self.request('/api/game', {'names': ['New', 'Game'], 'camera': True})[0], 400)
        self.assertEqual(self.request('/api/state')[1]['game'], before)


class ManualDependencyFallbackQA(unittest.TestCase):
    def test_manual_only_http_works_without_vision_dependencies(self):
        code = r'''
import builtins, http.client, json, threading
original_import = builtins.__import__
def import_without_vision(name, *args, **kwargs):
    if name in ('vision', 'cv2', 'numpy'):
        raise ImportError('Intentionally unavailable for independent fallback QA')
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_vision
import server
assert server.vision is None
server.app = server.App('manual-fallback-qa')
httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
worker = threading.Thread(target=httpd.serve_forever, daemon=True)
worker.start()
def request(path, body=None):
    connection = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1], timeout=5)
    connection.request('GET' if body is None else 'POST', path,
        None if body is None else json.dumps(body).encode(),
        {'Authorization': 'Bearer manual-fallback-qa'})
    response = connection.getresponse()
    status, data = response.status, response.read()
    connection.close()
    return status, data
try:
    assert request('/')[0] == 200
    assert request('/phone')[0] == 200
    status, data = request('/api/state')
    assert status == 200 and json.loads(data)['vision']['phase'] == 'unavailable'
    assert request('/api/game', {'names': ['A', 'B'], 'camera': False})[0] == 200
    status, data = request('/api/throw', {'value': 20, 'multiplier': 2})
    assert status == 200 and json.loads(data)['game']['scores'][0] == 261
    assert request('/api/game', {'names': ['A', 'B'], 'camera': True})[0] == 400
finally:
    httpd.shutdown()
    httpd.server_close()
    worker.join()
print('Manual-only HTTP fallback passed with vision imports unavailable')
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
