"""Record a synthetic trial session through the real server, recorder and fake IP Webcam (M4-03 validation).

A scripted host plays turns of three darts on the simulated board (sim/, ceiling-1.5ft by default): it accepts
right camera darts, corrects wrong ones with one tap, scores undetected darts by hand, sometimes lets all three
darts of a turn pile up before confirming any, then pulls the darts and taps Next player. The recording folder
is what tools/trial_report.py and tools/tune_params.py read. Synthetic only: not evidence of real accuracy.

Usage: .venv/bin/python tests/synthetic_session.py OUT_DIR [--turns 8] [--seed 2] [--mount ceiling-1.5ft]
"""
import argparse
import http.client
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402

from api_helper import with_revision  # noqa: E402
from fake_ipwebcam import FakeIPWebcam  # noqa: E402

TOKEN = 'synthetic-session-token'
SCENARIOS = ('t20-group', 't20-neighbours', 'stacked-below')


def wait_for(predicate, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class Session:
    def __init__(self, directory, mount, seed, profile='realistic', auto_commit=0.6):
        import server
        from sim import camera_for_mount
        from sim.scene import PROFILES, calibration_points
        from vision import Vision
        self.server = server
        self.directory = Path(directory)
        self.mount = mount
        self.camera = camera_for_mount(mount, 1280, 720)
        self.points = calibration_points(self.camera).tolist()
        self.degradation = PROFILES[profile]
        self.rng = np.random.default_rng([seed, 31])
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.app.flow.delay = auto_commit
        server.vision = Vision()
        self.fake = FakeIPWebcam([self.frames([])[0]], fps=15).start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.stats = {'accepted': 0, 'corrected': 0, 'manual': 0, 'piled_up_turns': 0}

    def frames(self, darts, count=3):
        """A few noisy renders of the board with these darts (the fake phone cycles through them)."""
        from sim.scene import degrade, render_clean
        clean = render_clean(self.camera, darts)
        return [degrade(clean, self.degradation, self.rng)[0] for _ in range(count)]

    def request(self, path, body=None):
        port = self.httpd.server_address[1]
        if body is not None:
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

    def setup(self):
        self.request('/api/camera/source', {'uri': self.fake.url + '/video'})
        assert wait_for(lambda: self.state()['vision']['fresh'], 5)
        self.server.start_recording(self.directory, {'mount': 'synthetic ' + self.mount, 'lighting': 'synthetic',
                                                     'phone': 'fake IP Webcam 1280x720 15 fps'})
        _, started = self.request('/api/calibration/start', {})
        _, calibrated = self.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                         'points': self.points})
        self.request('/api/verify', {'version': calibrated['vision']['version']})
        status, body = self.request('/api/game', {'names': ['A', 'B'], 'start': 501, 'camera': True})
        assert status == 200, body

    def settle(self, truth):
        """The host confirms the oldest pending camera dart (or scores truth by hand if there is none)."""
        from core import score_point
        expected = score_point(truth.x, truth.y)
        head = wait_for(lambda: self.state()['camera']['pending'], 2.5)
        if head and head['label'] == expected['label']:
            status, _ = self.request('/api/throw', {'proposal_id': head['id']})
            kind = 'accepted'
        elif head:
            status, _ = self.request('/api/throw', {'replaces_proposal_id': head['id'], 'value': expected['value'],
                                                    'multiplier': expected['multiplier']})
            kind = 'corrected'
        else:
            status, _ = self.request('/api/throw', {'value': expected['value'], 'multiplier': expected['multiplier']})
            kind = 'manual'
        if status == 409 and head:  # auto-commit got there first
            kind = 'accepted' if head['label'] == expected['label'] else 'auto (wrong)'
        self.stats[kind] = self.stats.get(kind, 0) + 1
        time.sleep(0.65)  # the controller ignores taps within 600 ms of the last write

    def play(self, turns):
        from tools.eval_occlusion import turn_darts
        for turn in range(turns):
            darts = turn_darts(SCENARIOS[turn % len(SCENARIOS)], self.rng)
            pile_up = turn % 3 == 2  # the host looks away until all three darts are in
            if pile_up:
                self.server.app.flow.paused = True
                self.stats['piled_up_turns'] += 1
            for k in range(1, 4):
                self.fake.set_frames(self.frames(darts[:k]))
                time.sleep(0.8)
                if not pile_up:
                    self.settle(darts[k - 1])
            if pile_up:
                for dart in darts:
                    self.settle(dart)
                self.server.app.flow.paused = False
            if self.state()['game']['winner'] is not None:
                break
            self.fake.set_frames(self.frames([]))  # the darts are pulled
            time.sleep(0.8)
            self.request('/api/next', {})

    def close(self):
        self.request('/api/record', {'enabled': False})
        self.server.set_camera_source(None)
        self.fake.stop()
        self.httpd.shutdown(); self.httpd.server_close()
        self.server.app, self.server.vision = self.previous
        self.server.recorder = None


def record(directory, turns=8, seed=2, mount='ceiling-1.5ft'):
    session = Session(directory, mount, seed)
    try:
        session.setup()
        session.play(turns)
    finally:
        session.close()
    return session.stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory')
    parser.add_argument('--turns', type=int, default=8)
    parser.add_argument('--seed', type=int, default=2)
    parser.add_argument('--mount', default='ceiling-1.5ft')
    args = parser.parse_args(argv)
    print(record(args.directory, args.turns, args.seed, args.mount))


if __name__ == '__main__':
    main()
