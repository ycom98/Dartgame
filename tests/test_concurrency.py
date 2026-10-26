"""M1-06: split locks and the background vision worker.

A slow align() must not block /api/state, image reads or game writes, and mixed concurrent
traffic must never deadlock. DART_STRESS_SECONDS shortens the stress test (default 30 s, the plan's figure).
"""
import http.client
import json
import os
import random
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import cv2
import numpy as np

import server
import vision as vision_module
from vision import Vision
from vision_worker import VisionWorker, WorkerBusy

POINTS = [[400, 150], [650, 400], [400, 650], [150, 400]]
TOKEN = 'concurrency-test-token'
STRESS_SECONDS = float(os.environ.get('DART_STRESS_SECONDS', '30'))


def textured_board():
    rng = np.random.default_rng(149)
    frame = np.full((800, 800, 3), 80, np.uint8)
    for _ in range(1600):
        x, y = rng.integers(155, 646, 2)
        if (x - 400) ** 2 + (y - 400) ** 2 < 240 ** 2:
            cv2.circle(frame, (int(x), int(y)), int(rng.integers(2, 6)),
                       tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
    return frame


def verified_vision():
    v = Vision()
    v.frame = textured_board(); v.timestamp = time.time()
    v.calibrate(POINTS); v.verify(v.version); v.publish()
    return v


class ServerFixture(unittest.TestCase):
    def setUp(self):
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = verified_vision()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join()
        server.app, server.vision = self.previous

    def request(self, path, body=None, raw=None, timeout=15):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        started = time.perf_counter()
        connection.request('POST' if payload is not None else 'GET', path, payload,
                           {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        data, status = response.read(), response.status
        elapsed = time.perf_counter() - started
        mime = response.getheader('Content-Type', '')
        connection.close()
        return status, json.loads(data) if 'application/json' in mime else data, elapsed


class SlowAlignDoesNotBlock(ServerFixture):
    def test_state_and_manual_throw_respond_during_slow_align(self):
        status, game, _ = self.request('/api/game', {'names': ['A', 'B'], 'camera': False})
        self.assertEqual(status, 200, game)
        before = self.request('/api/state')[1]
        self.assertTrue(before['vision']['verified'])
        started = threading.Event()
        original = Vision.align

        def slow_align(vision, *args, **kwargs):
            started.set()
            time.sleep(2)
            return original(vision, *args, **kwargs)

        results = {}
        with patch.object(Vision, 'align', slow_align):
            aligner = threading.Thread(target=lambda: results.setdefault('align', self.request('/api/align', {})))
            aligner.start()
            self.assertTrue(started.wait(2), 'align did not start on the worker')
            timings = []
            for _ in range(20):
                status, state, elapsed = self.request('/api/state')
                self.assertEqual(status, 200)
                timings.append(elapsed)
                # Pre-align state: same overlay version, still verified.
                self.assertEqual(state['vision']['version'], before['vision']['version'])
                self.assertTrue(state['vision']['verified'])
            status, image, image_elapsed = self.request('/api/image')
            self.assertEqual(status, 200)
            status, thrown, throw_elapsed = self.request(
                '/api/throw', {'value': 20, 'multiplier': 3, 'expected_revision': before['revision']})
            self.assertEqual(status, 200, thrown)
            self.assertEqual(thrown['game']['scores'][0], 241)
            self.assertTrue(aligner.is_alive(), 'align finished early; the timing proves nothing')
            aligner.join(10)
        print(f'\nM1-06 during a 2 s align: /api/state max {max(timings) * 1000:.1f} ms, '
              f'median {sorted(timings)[10] * 1000:.1f} ms; /api/throw {throw_elapsed * 1000:.1f} ms; '
              f'/api/image {image_elapsed * 1000:.1f} ms')
        self.assertLess(max(timings), 0.1)
        self.assertLess(throw_elapsed, 0.1)
        self.assertLess(image_elapsed, 0.5)
        self.assertEqual(results['align'][0], 200)
        after = self.request('/api/state')[1]
        self.assertGreater(after['vision']['version'], before['vision']['version'])
        self.assertEqual(after['revision'], before['revision'] + 1)

    def test_queued_action_that_cannot_start_in_time_is_cancelled(self):
        worker = VisionWorker(lambda: server.vision)
        ran = []
        blocker = worker.submit(lambda v: time.sleep(0.6))
        try:
            with self.assertRaises(WorkerBusy):
                worker.call(lambda v: ran.append(True), timeout=0.1)
            blocker.result(5)
            time.sleep(0.1)
            self.assertEqual(ran, [], 'a timed-out action must not run later')
        finally:
            worker.stop()

    def test_queued_actions_do_not_starve_frames(self):
        from camera_source import ImageFolderSource
        import tempfile, os
        vision = Vision()
        worker = VisionWorker(lambda: vision, max_fps=0)
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(os.path.join(folder, 'a.png'), textured_board())
            worker.set_source(ImageFolderSource(folder, fps=30, loop=True))
            try:
                futures = [worker.submit(lambda v: time.sleep(0.02)) for _ in range(60)]  # ~1.2 s of queued work
                time.sleep(0.6)
                frames_during_queue = len(worker.processed)
                for future in futures: future.result(10)
            finally:
                worker.stop()
        self.assertGreater(frames_during_queue, 5, 'frames were processed while actions were queued')

    def test_next_player_check_matches_the_published_state(self):
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': True})[0], 200)
        for value in (20, 20, 20):
            self.assertEqual(self.request('/api/throw', {'value': value})[0], 200)
        with server.vision.lock:
            server.vision.verified_version = None  # changed but not yet published, as part-way through align()
            status, body, _ = self.request('/api/next', {})
            server.vision.verified_version = server.vision.version
        self.assertEqual(status, 200, body)

    def test_proposal_commit_gives_up_with_503_when_vision_is_stuck(self):
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False})[0], 200)
        with patch.object(server, 'ACTION_TIMEOUT_SECONDS', 0.2), server.vision.lock:
            results = []
            thread = threading.Thread(target=lambda: results.append(self.request('/api/throw', {'proposal': True})))
            thread.start(); thread.join(5)
        self.assertEqual(results[0][0], 503)

    def test_stale_camera_shows_disconnected_without_a_new_publish(self):
        v = server.vision
        self.assertEqual(v.current_state()['phase'], 'ready')
        v.timestamp = time.time() - 6  # no publish: the worker might be busy
        state = v.current_state()
        self.assertEqual(state['phase'], 'camera_disconnected')
        self.assertFalse(state['verified']); self.assertFalse(state['aligned'])
        self.assertIsNone(state['proposal'])

    def test_proposal_commit_reads_proposal_under_vision_lock_and_commits_once(self):
        status, game, _ = self.request('/api/game', {'names': ['A', 'B'], 'camera': True})
        self.assertEqual(status, 200, game)
        with server.vision.lock:
            server.vision.proposal = {'value': 20, 'multiplier': 3}
            server.vision.publish()
        outcomes = []
        threads = [threading.Thread(target=lambda: outcomes.append(self.request('/api/throw', {'proposal': True})[0]))
                   for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join(10)
        self.assertEqual(sorted(outcomes), [200, 400, 400, 400])
        self.assertEqual(self.request('/api/state')[1]['game']['scores'][0], 241)


class NoDeadlockUnderStress(ServerFixture):
    def test_mixed_traffic_for_stress_period(self):
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False})[0], 200)
        ok, jpeg = cv2.imencode('.jpg', server.vision.frame)
        self.assertTrue(ok)
        jpeg = jpeg.tobytes()
        deadline = time.monotonic() + STRESS_SECONDS
        counts = {'writes': 0, 'requests': 0}
        failures = []
        count_lock = threading.Lock()
        original = Vision.align

        def jittery_align(vision, *args, **kwargs):
            time.sleep(random.uniform(0, 0.05))
            return original(vision, *args, **kwargs)

        def client(seed):
            rng = random.Random(seed)
            while time.monotonic() < deadline:
                choice = rng.choice(['state', 'state', 'throw', 'undo', 'next', 'align', 'frame', 'image'])
                try:
                    if choice == 'state':
                        status, _, _ = self.request('/api/state')
                    elif choice == 'throw':
                        status, _, _ = self.request('/api/throw', {'value': rng.randint(0, 20), 'multiplier': 1})
                    elif choice == 'undo':
                        status, _, _ = self.request('/api/undo', {})
                    elif choice == 'next':
                        status, _, _ = self.request('/api/next', {})
                    elif choice == 'align':
                        status, _, _ = self.request('/api/align', {})
                    elif choice == 'frame':
                        status, _, _ = self.request('/api/frame', raw=jpeg)
                    else:
                        status, _, _ = self.request('/api/image')
                except Exception as error:  # a timeout here means a deadlock or a stuck worker
                    failures.append(f'{choice}: {type(error).__name__}: {error}')
                    return
                if status >= 500:
                    failures.append(f'{choice}: HTTP {status}')
                with count_lock:
                    counts['requests'] += 1
                    if choice in ('throw', 'undo', 'next') and status == 200:
                        counts['writes'] += 1

        with patch.object(Vision, 'align', jittery_align):
            threads = [threading.Thread(target=client, args=(seed,), daemon=True) for seed in range(4)]
            for t in threads: t.start()
            for t in threads: t.join(STRESS_SECONDS + 20)
        self.assertFalse(any(t.is_alive() for t in threads), 'a client thread is stuck (deadlock)')
        self.assertEqual(failures, [])
        final = self.request('/api/state')[1]
        # Every successful write bumped the revision exactly once (1 for the game itself).
        self.assertEqual(final['revision'], counts['writes'] + 1)
        print(f'\nM1-06 stress: {counts["requests"]} requests in {STRESS_SECONDS:.0f} s, '
              f'{counts["writes"]} game writes, no deadlock')
        self.assertGreater(counts['requests'], 100)


if __name__ == '__main__':
    unittest.main()
