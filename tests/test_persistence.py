"""M1-16: the match and calibration survive a server restart (kill -9 included)."""
import http.client
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Server:
    """server.py in a subprocess with its own state file; restartable on the same port."""

    def __init__(self, state_file, extra=()):
        self.state_file, self.extra, self.port = str(state_file), list(extra), free_port()
        self.process = None

    def start(self):
        environment = {**os.environ, 'DART_STATE_FILE': os.devnull}
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'server.py'), '--host', '127.0.0.1', '--port', str(self.port),
             '--state-file', self.state_file] + self.extra,
            cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        while not any(line.startswith('Camera source:') for line in lines):
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError('server did not start:\n' + ''.join(lines))
            lines.append(line)
        self.output = ''.join(lines)
        self.token = next(l for l in lines if l.startswith('Controller:')).split('t=')[1].strip()
        return self

    def kill(self):
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(5)
        self.process.stdout.close()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate(); self.process.wait(5); self.process.stdout.close()

    def request(self, path, body=None):
        if body is not None:
            body = {**body, 'expected_revision': self.request('/api/state')[1]['revision']}
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        connection.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None,
                           {'Authorization': 'Bearer ' + self.token})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data


def wait_for(predicate, timeout, step=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class MatchSurvivesRestart(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.state_file = Path(self.folder.name) / 'state' / 'match.json'
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()
        self.folder.cleanup()

    def server(self, extra=()):
        server = Server(self.state_file, extra).start()
        self.servers.append(server)
        return server

    def test_kill_9_mid_turn_resumes_identical_state_and_undo_still_works(self):
        first = self.server()
        self.assertEqual(first.request('/api/game', {'names': ['Kapil', 'Aita'], 'camera': False, 'start': 501,
                                                     'double_out': True})[0], 200)
        for value, multiplier in ((20, 3), (20, 3), (20, 3)):
            first.request('/api/throw', {'value': value, 'multiplier': multiplier})
        first.request('/api/next', {})
        first.request('/api/throw', {'value': 19, 'multiplier': 3})
        first.request('/api/throw', {'value': 0})
        first.request('/api/undo', {})
        first.request('/api/throw', {'value': 25, 'multiplier': 2})  # mid-turn: 2 darts
        before = first.request('/api/state')[1]
        first.kill()
        second = self.server()
        self.assertIn('Resumed the saved match', second.output)
        after = second.request('/api/state')[1]
        self.assertEqual(after['game'], before['game'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertNotEqual(second.token, first.token)  # pairing tokens are never saved
        status, undone = second.request('/api/undo', {})
        self.assertEqual(status, 200)
        self.assertEqual([d['score'] for d in undone['game']['darts']], [57])
        self.assertEqual(undone['revision'], before['revision'] + 1)

    def test_corrupt_file_starts_clean_and_keeps_a_copy(self):
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text('{"schema": 1, "game": {"mode": "x01", "sta')
        server = self.server()
        self.assertIn('WARNING: the saved match could not be read', server.output)
        self.assertIsNone(server.request('/api/state')[1]['game'])
        copies = list(self.state_file.parent.glob('match.corrupt-*.json'))
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].read_text().startswith('{"schema": 1'))

    def test_fresh_starts_empty_and_keeps_the_previous_match(self):
        first = self.server()
        first.request('/api/game', {'names': ['A', 'B'], 'camera': False})
        first.stop()
        second = self.server(['--fresh'])
        self.assertIsNone(second.request('/api/state')[1]['game'])
        self.assertEqual(len(list(self.state_file.parent.glob('match.previous-*.json'))), 1)


class WriteSpeed(unittest.TestCase):
    def test_save_with_200_history_entries_is_under_20_ms_p95(self):
        import server
        from core import Game
        from persistence import MatchStore
        app = server.App('speed')
        app.game = Game(['A', 'B', 'C', 'D'], 501, True)
        while len(app.game.history) < 200:
            g = app.game
            if g.mode.can_advance(g.data): g.next_turn()
            else: g.throw(1, 1)
        with tempfile.TemporaryDirectory() as folder:
            store = MatchStore(Path(folder) / 'match.json')
            times = []
            for _ in range(60):
                store.save(app)
                times.append(store.last_write_seconds)
        median, p95 = statistics.median(times), sorted(times)[int(0.95 * len(times)) - 1]
        load = os.getloadavg()[0] / (os.cpu_count() or 1)
        print(f'\nM1-16 save with {len(app.game.history)} history entries: median {median * 1000:.2f} ms, '
              f'p95 {p95 * 1000:.2f} ms (load {load:.2f} per CPU)')
        # QA M1-16 L5: the median is the regression guard and always applies; the p95 limit only on a quiet
        # machine, because parallel disk load (other test suites) spikes single writes.
        self.assertLess(median, 0.020)
        if load < 1.0:
            self.assertLess(p95, 0.020)
        else:
            self.assertLess(p95, 0.100)


class DamagedSaveFiles(unittest.TestCase):  # QA M1-16 D1
    def test_every_damaged_shape_starts_clean_and_keeps_the_file(self):
        import server
        from core import Game
        from persistence import MatchStore
        good = {'schema': 1, 'game': Game(['A', 'B']).to_json(), 'revision': 3, 'camera_game': False,
                'auto_commit': {'paused': False, 'seconds': 3.0}, 'saved_at': 0}

        def broken(change):
            data = json.loads(json.dumps(good))
            change(data)
            return data
        cases = {
            'a list': [], 'null': None, 'a number': 7,
            'game is a list': broken(lambda d: d.update(game=[])),
            'state is null': broken(lambda d: d['game'].update(state=None)),
            'player out of range': broken(lambda d: d['game']['state'].update(player=5)),
            'missing scores': broken(lambda d: d['game']['state'].pop('scores')),
            'scores too short': broken(lambda d: d['game']['state'].update(scores=[301])),
            'bad dart': broken(lambda d: d['game']['state'].update(darts=[{'value': 21, 'multiplier': 1, 'score': 21}])),
            'four darts': broken(lambda d: d['game']['state'].update(darts=[{'value': 1, 'multiplier': 1, 'score': 1}] * 4)),
            'winner out of range': broken(lambda d: d['game']['state'].update(winner=9)),
            'names empty': broken(lambda d: d['game']['state'].update(names=[])),
            'history not a list': broken(lambda d: d['game'].update(history={})),
            'bad history entry': broken(lambda d: d['game'].update(history=[{'names': 'A'}])),
            'unknown mode': broken(lambda d: d['game'].update(mode='cricket')),
            'negative revision': broken(lambda d: d.update(revision=-1)),
            'auto_commit a list': broken(lambda d: d.update(auto_commit=[])),
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'match.json'
            path.write_text(json.dumps(good))
            self.assertIn('Resumed', MatchStore(path).load(server.App('damaged')))  # the good file loads
            for name, payload in cases.items():
                with self.subTest(case=name):
                    for old in Path(folder).glob('match.corrupt-*'):
                        old.unlink()
                    path.write_text(json.dumps(payload))
                    app = server.App('damaged')
                    message = MatchStore(path).load(app)
                    self.assertIn('WARNING', message)
                    self.assertIsNone(app.game)
                    self.assertEqual(app.revision, 0)
                    self.assertFalse(path.exists())
                    self.assertEqual(len(list(Path(folder).glob('match.corrupt-*'))), 1)


class SaveFailureNeverBreaksAWrite(unittest.TestCase):
    def test_a_failing_save_keeps_the_write_and_reports_it(self):
        import server
        from persistence import MatchStore
        app = server.App('save-failure')
        with tempfile.TemporaryDirectory() as folder:
            blocker = Path(folder) / 'not-a-folder'
            blocker.write_text('a file where the state folder should be')
            app.store = MatchStore(blocker / 'match.json')
            with app.game_lock:
                app.bump()
        self.assertEqual(app.revision, 1)
        self.assertIn('Could not save the match', app.store.error)

    def test_any_save_error_is_reported_not_raised(self):  # QA M1-16 L2
        import server
        from persistence import MatchStore
        app = server.App('save-error')
        app.store = MatchStore('/nonexistent/match.json')
        def failing(_):
            raise TypeError('not JSON serialisable')
        app.store.save = failing
        with app.game_lock:
            app.bump()
        self.assertEqual(app.revision, 1)
        self.assertIn('not JSON serialisable', app.store.error)

    def test_calibration_save_errors_are_reported_not_raised(self):  # QA M1-16 L3
        import cv2
        import persistence
        import server
        from unittest.mock import patch
        def failing(vision, directory):
            raise cv2.error('imencode failed')
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'CALIBRATION_DIR', Path(folder)), \
                patch.object(persistence, 'save_calibration', failing):
            server.save_calibration()  # must not raise


class CalibrationSurvivesRestart(unittest.TestCase):
    def test_restart_with_saved_calibration_reaches_overlay_review_without_clicks(self):
        import cv2
        from sim import camera_for_mount
        from sim.scene import calibration_points, render_clean
        camera = camera_for_mount('left', 1280, 720)
        with tempfile.TemporaryDirectory() as folder:
            frames = Path(folder) / 'frames'
            frames.mkdir()
            cv2.imwrite(str(frames / 'board.png'), render_clean(camera, []))
            state_file = Path(folder) / 'state' / 'match.json'
            extra = ['--camera', f'dir:{frames}?loop=1&fps=10']
            first = Server(state_file, extra).start()
            try:
                self.assertTrue(wait_for(lambda: first.request('/api/state')[1]['vision']['fresh'], 8))
                started = first.request('/api/calibration/start', {})[1]
                status, calibrated = first.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                                      'points': calibration_points(camera).tolist()})
                self.assertEqual(status, 200, calibrated)
                first.request('/api/verify', {'version': calibrated['vision']['version']})
                first.request('/api/camera/mount_side', {'mount_side': 'left'})
                overlay = first.request('/api/state')[1]['vision']['overlay']
            finally:
                first.kill()
            self.assertTrue((state_file.parent / 'calibration.json').exists())
            second = Server(state_file, extra).start()
            try:
                self.assertIn('Saved calibration loaded', second.output)
                phase = wait_for(lambda: second.request('/api/state')[1]['vision']['phase'] == 'review_overlay', 10)
                time.sleep(1.5)  # several frames later the review prompt must still be there (QA M1-16 D2)
                vision = second.request('/api/state')[1]['vision']
                self.assertTrue(phase, vision)
                self.assertEqual(vision['phase'], 'review_overlay')
                self.assertNotIn('Ready', vision['message'])
                self.assertEqual(vision['mount_side'], 'left')
                drift = max(abs(a - b) for p, q in zip(vision['overlay'], overlay) for a, b in zip(p, q))
                self.assertLess(drift, 2.0)
                status, verified = second.request('/api/verify', {'version': vision['version']})  # the one tap
                self.assertEqual(verified['vision']['phase'], 'ready')
            finally:
                second.stop()


class DifferentViewAfterRestart(unittest.TestCase):  # QA M1-16 D2
    def test_a_restart_with_another_camera_view_asks_for_the_four_points_again(self):
        import cv2
        from sim import camera_for_mount
        from sim.scene import calibration_points, render_clean
        left, right = camera_for_mount('left', 1280, 720), camera_for_mount('right', 1280, 720)
        with tempfile.TemporaryDirectory() as folder:
            frames = {name: Path(folder) / name for name in ('left', 'right')}
            for name, camera in (('left', left), ('right', right)):
                frames[name].mkdir()
                cv2.imwrite(str(frames[name] / 'board.png'), render_clean(camera, []))
            state_file = Path(folder) / 'state' / 'match.json'
            first = Server(state_file, ['--camera', f"dir:{frames['left']}?loop=1&fps=10"]).start()
            try:
                self.assertTrue(wait_for(lambda: first.request('/api/state')[1]['vision']['fresh'], 8))
                started = first.request('/api/calibration/start', {})[1]
                status, calibrated = first.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                                      'points': calibration_points(left).tolist()})
                self.assertEqual(status, 200, calibrated)
                first.request('/api/verify', {'version': calibrated['vision']['version']})
            finally:
                first.kill()
            second = Server(state_file, ['--camera', f"dir:{frames['right']}?loop=1&fps=10"]).start()
            try:
                message = lambda: second.request('/api/state')[1]['vision']['message'].lower()
                self.assertTrue(wait_for(lambda: 'set four points' in message(), 10), message())
                time.sleep(1.0)
                vision = second.request('/api/state')[1]['vision']
                self.assertEqual(vision['phase'], 'needs_alignment', vision['message'])
                self.assertFalse(vision['verified'])
            finally:
                second.stop()


if __name__ == '__main__':
    unittest.main()
