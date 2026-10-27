"""Regression tests for QA report QA-M1-10-11-12-14 (Q2-Q5). Q1 (tap board) is in tests/qa_tap_board.cjs."""
import errno
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402

import server  # noqa: E402
from camera_flow import CameraFlow, EventLog  # noqa: E402
from vision import Vision  # noqa: E402

TOKEN = 'qa-m1d-token'
POINTS = [[400, 150], [650, 400], [400, 650], [150, 400]]


class DiskFull:
    """A file handle whose writes fail like a full disk or an unplugged drive."""
    closed = False

    def write(self, text):
        raise OSError(errno.ENOSPC, 'No space left on device')

    def flush(self):
        pass

    def close(self):
        self.closed = True


def verified_vision():
    rng = np.random.default_rng(149)
    frame = np.full((800, 800, 3), 80, np.uint8)
    for _ in range(1600):
        x, y = rng.integers(155, 646, 2)
        if (x - 400) ** 2 + (y - 400) ** 2 < 240 ** 2:
            cv2.circle(frame, (int(x), int(y)), int(rng.integers(2, 6)), tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
    v = Vision()
    v.frame = frame; v.timestamp = time.time()
    v.calibrate(POINTS); v.verify(v.version); v.publish()
    return v


def wait_for(predicate, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.previous = (server.app, server.vision, server.recorder, server.RECORDINGS_ROOT)
        server.app = server.App(TOKEN)
        server.vision = verified_vision()
        server.recorder = None
        server.RECORDINGS_ROOT = Path(self.folder.name)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        if server.recorder is not None:
            server.recorder.stop()
        self.httpd.shutdown(); self.httpd.server_close()
        server.app, server.vision, server.recorder, server.RECORDINGS_ROOT = self.previous
        self.folder.cleanup()

    def request(self, path, body=None, revision=None):
        port = self.httpd.server_address[1]
        if body is not None:
            body = {**body, 'expected_revision': revision} if revision is not None else with_revision(port, TOKEN, path, body)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def failing_recorder(self):
        """Start a recording, then make its event log fail like a full disk."""
        self.assertEqual(self.request('/api/record', {'enabled': True})[0], 200)
        server.recorder.files['events.jsonl'] = DiskFull()
        return server.recorder

    def set_proposal(self, label='T20', value=20, multiplier=3, x=0.0, y=-103.0):
        with server.vision.lock:
            server.vision.proposal = {'value': value, 'multiplier': multiplier, 'label': label, 'score': value * multiplier,
                                      'x': x, 'y': y}
            server.vision.publish()
            server.app.flow.observe(server.vision)


class RecorderNeverBreaksTheGame(ServerCase):  # Q2, Q3
    def test_manual_throw_with_a_failing_log_is_recorded_once_and_the_retry_is_refused(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': False})
        recorder = self.failing_recorder()
        revision = self.request('/api/state')[1]['revision']
        status, state = self.request('/api/throw', {'value': 20, 'multiplier': 3}, revision=revision)
        self.assertEqual(status, 200, state)
        self.assertEqual(state['revision'], revision + 1)
        self.assertEqual(len(state['game']['darts']), 1)
        status, _ = self.request('/api/throw', {'value': 20, 'multiplier': 3}, revision=revision)  # the host's retry
        self.assertEqual(status, 409)
        self.assertEqual(len(self.request('/api/state')[1]['game']['darts']), 1)
        recording = self.request('/api/state')[1]['recording']
        self.assertFalse(recording['active'])
        self.assertIn('could not write events.jsonl', recording['error'])
        self.assertNotIn(recorder.match_event, server.app.events.listeners)
        recorder.stop(); recorder.stop()  # idempotent, never raises

    def test_auto_commit_with_a_failing_log_commits_a_camera_dart_exactly_once(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        server.worker.call(lambda v: None)
        server.app.flow.delay = 0.3
        self.failing_recorder()
        self.set_proposal()
        self.assertTrue(wait_for(lambda: len(server.app.game.data['darts']) >= 1, 3))
        time.sleep(2.5)
        self.assertEqual([d['score'] for d in server.app.game.data['darts']], [60])
        self.assertIsNone(self.request('/api/state')[1]['camera']['pending'])

    def test_a_listener_error_is_contained(self):
        log = EventLog()
        seen = []
        log.listeners += [lambda e: 1 / 0, seen.append]
        log.add('commit', dart=None)
        self.assertEqual(len(seen), 1)

    def test_frame_writer_failure_stops_the_recording_and_says_why(self):
        self.request('/api/record', {'enabled': True})
        recorder = server.recorder

        def broken(source):
            raise OSError(errno.EIO, 'Input/output error')
        recorder.write_new_frames = broken

        class Source:
            seq, kind, description, size = 1, 'mjpeg', 'test', None
        recorder.get_source = lambda: Source()
        self.assertTrue(wait_for(lambda: not recorder.active, 3))
        self.assertIn('frame writer failed', recorder.status()['error'])
        self.assertFalse(self.request('/api/state')[1]['recording']['active'])

    def test_disk_guard_stop_unhooks_the_recorder_and_free_space_is_for_the_recording_folder(self):
        self.request('/api/record', {'enabled': True})
        recorder = server.recorder
        self.assertEqual(server.free_disk_bytes(), recorder.free_bytes())
        recorder.min_free_bytes = 10 ** 18
        self.assertTrue(wait_for(lambda: not recorder.active, 4))
        self.assertNotIn(recorder.match_event, server.app.events.listeners)


class PendingCameraDart(ServerCase):  # Q4, Q5
    def test_label_flips_keep_one_id_and_restart_the_countdown_once(self):
        flow = CameraFlow(delay=0.5)

        class FakeVision:
            base = object(); aligned = True; proposal = None
            def fresh(self): return True
        vision = FakeVision()
        ids, started, committed_at = set(), time.monotonic(), None
        for step in range(12):  # S20 <-> S1 every 0.15 s, tip jitter under 1 mm
            label = 'S20' if step % 2 == 0 else 'S1'
            vision.proposal = {'value': int(label[1:]), 'multiplier': 1, 'label': label, 'score': int(label[1:]),
                               'x': 8.6 + step % 3 * 0.3, 'y': -59.0}
            ids.add(flow.observe(vision)['id'])
            if committed_at is None and flow.due():
                committed_at = time.monotonic() - started
            time.sleep(0.15)
        self.assertEqual(len(ids), 1)
        self.assertIsNotNone(committed_at, 'a flickering label must still auto-commit')
        self.assertLess(committed_at, 1.2)  # one fresh 0.5 s countdown after the first change, not one per flip

    def test_accept_names_the_label_the_host_saw(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        server.worker.call(lambda v: None)
        server.app.flow.paused = True
        self.set_proposal(label='S20', value=20, multiplier=1, x=8.0, y=-60.0)
        shown = self.request('/api/state')[1]['camera']['pending']
        self.set_proposal(label='S1', value=1, multiplier=1, x=8.4, y=-60.0)  # flipped after the host looked
        status, data = self.request('/api/throw', {'proposal_id': shown['id'], 'label': 'S20'})
        self.assertEqual(status, 409, data)
        self.assertIn('now reads S1', data['error'])
        self.assertEqual(self.request('/api/throw', {'proposal_id': shown['id'], 'label': 'S1'})[0], 200)
        self.assertEqual(server.app.game.data['darts'][0]['score'], 1)

    def test_undo_keeps_a_pending_camera_dart_and_turn_over_stops_the_countdown(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        server.worker.call(lambda v: None)
        server.app.flow.paused = True
        self.request('/api/throw', {'value': 20})
        server.worker.call(lambda v: None)
        self.set_proposal()
        status, state = self.request('/api/undo', {})
        server.worker.call(lambda v: None)
        self.assertIsNotNone(self.request('/api/state')[1]['camera']['pending'], 'undo must not swallow the pending dart')
        self.assertTrue([e for e in server.app.events.since() if e['type'] == 'undo'][-1]['pending_camera_dart_kept'])
        server.app.flow.paused = False
        for _ in range(3):
            server.app.game.throw(0, 1)  # the turn is over with a dart still pending
        pending = self.request('/api/state')[1]['camera']['pending']
        self.assertTrue(pending['turn_over'])
        self.assertIsNone(pending['commit_in'])


if __name__ == '__main__':
    unittest.main()
