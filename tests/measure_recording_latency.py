"""M1-14 acceptance 4: detection latency while recording 1080p / 15 fps for 60 s (sim, localhost).

Runs the server in-process against tests/fake_ipwebcam.py at 1920x1080 / 15 fps, records, and throws nine
sim darts about 6.5 s apart. Latency = scene switched on the fake phone -> pending dart in /api/state (the
M1-12 limit is 1.5 s to /control; /control polls every 0.4 s on top). Also runs the same without recording.

  .venv/bin/python -B tests/measure_recording_latency.py [--seconds 60] [--out qa-artifacts/M1-14-recording-latency.json]
"""
import argparse
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from fake_ipwebcam import FakeIPWebcam  # noqa: E402
from test_recording import PLAN  # noqa: E402


def run(seconds, record, scenes, points):
    import server
    from vision import Vision
    server.app = server.App('measure')
    server.vision = Vision()
    folder = tempfile.mkdtemp()
    server.RECORDINGS_ROOT = Path(folder)
    fake = FakeIPWebcam([scenes[0]], fps=15).start()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def post(path, body):
        body = {**body, 'expected_revision': server.app.revision}
        handler = type('H', (), {})  # call the routing directly: no HTTP noise in the timing
        return server.Handler.route_post(handler, path, body)

    try:
        server.set_camera_source(fake.url + '/video')
        while not server.vision.current_state()['fresh']:
            time.sleep(0.05)
        snapshot = server.worker.call(lambda v: v.begin_calibration())
        server.worker.call(lambda v: v.calibrate(points, snapshot['snapshot_id']))
        server.worker.call(lambda v: v.verify(v.version))
        post('/api/game', {'names': ['A', 'B'], 'camera': True})
        server.app.flow.paused = True
        if record:
            server.start_recording()
        latencies, ages = [], []
        started = time.monotonic()
        interval = seconds / len(PLAN)
        for k in range(1, len(PLAN) + 1):
            fake.set_frames([scenes[k]])
            shown = time.monotonic()
            pending = None
            while pending is None and time.monotonic() - shown < 5:
                pending = server.app.state()['camera']['pending']
                time.sleep(0.01)
            latencies.append(round(time.monotonic() - shown, 3) if pending else None)
            if pending:
                server.commit_camera_dart(pending['id'], 'accepted')
            if k % 3 == 0:
                post('/api/next', {})
            while time.monotonic() - started < k * interval:
                ages.append(server.worker.source_status()['last_frame_age'])
                time.sleep(0.2)
        status = server.app.state()['recording']
        source = server.worker.source_status()
        if record:
            server.stop_recording()
        found = [l for l in latencies if l is not None]
        return {'recording': record, 'seconds': round(time.monotonic() - started, 1), 'darts': len(PLAN),
                'detected': len(found), 'latency_s': latencies,
                'latency_median_s': statistics.median(found) if found else None,
                'latency_p95_s': sorted(found)[min(len(found) - 1, math.ceil(0.95 * len(found)) - 1)] if found else None,
                'frame_age_max_s': max(a for a in ages if a is not None), 'received_fps': source['fps'],
                'processed_fps': source['processed_fps'],
                'recorded_frames': status['frames'] if record else None,
                'recorded_skipped_frames': status['skipped_frames'] if record else None,
                'recorded_bytes': status['bytes'] if record else None}
    finally:
        server.set_camera_source(None)
        server.recorder = None
        fake.stop()
        httpd.shutdown(); httpd.server_close()
        shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--out')
    args = parser.parse_args()
    from core import SECTORS
    from sim import camera_for_mount
    from sim.scene import Dart, calibration_points, render_clean
    camera = camera_for_mount('left', 1920, 1080)
    darts = []
    for sector, radius in PLAN:
        angle = math.radians(SECTORS.index(sector) * 18)
        darts.append(Dart(x=radius * math.sin(angle), y=-radius * math.cos(angle), tilt=11.0))
    scenes = [render_clean(camera, darts[:k]) for k in range(len(PLAN) + 1)]
    points = calibration_points(camera).tolist()
    report = {'note': 'sim board, localhost, this machine; not real-phone numbers', 'resolution': '1920x1080',
              'stream_fps': 15, 'cpu_count': os.cpu_count(),
              'runs': [run(args.seconds, True, scenes, points), run(args.seconds, False, scenes, points)]}
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
