"""QA M1-17 #3 / criterion C9: after a phone stream drop the camera comes back without recalibration.

Ready returns automatically only if the board has not moved (markers within server.AUTO_READY_PX of where they
were verified); otherwise the host is asked to check the overlay on the Mac.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_ipwebcam import FakeIPWebcam  # noqa: E402
from test_persistence import Server, wait_for  # noqa: E402


class StreamDropRecovery(unittest.TestCase):
    def setUp(self):
        from sim import camera_for_mount
        from sim.scene import calibration_points, render_clean
        camera = camera_for_mount('left', 1280, 720)
        self.frame = render_clean(camera, [])
        self.points = calibration_points(camera).tolist()
        self.folder = tempfile.TemporaryDirectory()
        self.fake = FakeIPWebcam([self.frame], fps=15).start()
        self.server = Server(Path(self.folder.name) / 'state' / 'match.json',
                             ['--camera', self.fake.url + '/video']).start()
        self.assertTrue(wait_for(lambda: self.vision()['fresh'], 8))
        started = self.server.request('/api/calibration/start', {})[1]
        calibrated = self.server.request('/api/calibrate', {'snapshot_id': started['snapshot']['snapshot_id'],
                                                            'points': self.points})[1]
        self.server.request('/api/verify', {'version': calibrated['vision']['version']})
        self.assertTrue(wait_for(lambda: self.vision()['verified'], 3))
        time.sleep(1.0)  # the watcher notes the verified overlay

    def tearDown(self):
        self.server.stop()
        self.fake.stop()
        self.folder.cleanup()

    def vision(self):
        return self.server.request('/api/state')[1]['vision']

    def drop_for(self, seconds, frames):
        self.fake.stop()
        self.assertTrue(wait_for(lambda: self.vision()['phase'] == 'camera_disconnected', 8))
        self.assertIn('Camera stream lost', self.vision()['message'])  # not "Ready"
        time.sleep(seconds)
        self.fake = FakeIPWebcam(frames, fps=15, port=self.fake.port).start()
        return time.monotonic()

    def test_unchanged_board_is_ready_again_without_any_tap(self):
        back = self.drop_for(4, [self.frame])
        self.assertTrue(wait_for(lambda: self.vision()['verified'], 12), self.vision())
        recovered = time.monotonic() - back
        print(f'\nM1-17 stream drop: ready again {recovered:.1f} s after the stream came back (no tap)')
        self.assertLess(recovered, 10)
        self.assertEqual(self.vision()['phase'], 'ready')

    def test_moved_board_asks_the_host_on_the_mac(self):
        moved = cv2.warpAffine(self.frame, np.float32([[1, 0, 14], [0, 1, 9]]), (1280, 720))
        self.drop_for(4, [moved])
        self.assertTrue(wait_for(lambda: 'moved' in self.vision()['message'] or 'Check / realign' in self.vision()['message'],
                                 12), self.vision())
        time.sleep(1.5)
        vision = self.vision()
        self.assertFalse(vision['verified'])
        self.assertIn(vision['phase'], ('review_overlay', 'needs_alignment'))


if __name__ == '__main__':
    unittest.main()
