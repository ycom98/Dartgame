"""Alignment falls back to a direct image fit when ORB features are not confident (zoomed-in real board)."""
import time
import unittest

import cv2
import numpy as np

from sim.scene import calibration_points
from tests.test_camera_source import sim_frames
from vision import TARGETS, Vision


class AlignFallback(unittest.TestCase):
    def setUp(self):
        self.camera, frames = sim_frames('left', 1280, 720)
        self.frame = frames[0]
        self.vision = Vision()
        self.vision.ingest(cv2.imencode('.jpg', self.frame)[1].tobytes())
        self.vision.calibrate(calibration_points(self.camera).tolist())
        self.before = np.asarray(self.vision.overlay())

    def show(self, frame):
        self.vision.frame = frame; self.vision.timestamp = time.time()

    def test_align_succeeds_without_orb_when_nothing_moved(self):
        def no_features(*args, **kwargs):
            raise ValueError('Cannot confidently locate board')
        self.vision.orb_match_reference = no_features
        result = self.vision.align()
        self.assertTrue(result['ok'])
        self.assertLess(np.max(np.linalg.norm(np.asarray(self.vision.overlay()) - self.before, axis=1)), 1.0)

    def test_small_shift_is_followed(self):
        self.show(cv2.warpAffine(self.frame, np.float32([[1, 0, 6], [0, 1, -4]]), (1280, 720)))
        H = self.vision.ecc_match_reference()
        now = cv2.perspectiveTransform(TARGETS.reshape(1, -1, 2), np.linalg.inv(H))[0]
        np.testing.assert_allclose((now - self.before).mean(axis=0), [6, -4], atol=0.5)

    def test_a_different_picture_is_not_trusted(self):
        self.vision.orb_match_reference = lambda *a, **k: (_ for _ in ()).throw(ValueError('no ORB'))
        self.show(np.full_like(self.frame, 60))
        with self.assertRaises(ValueError):
            self.vision.align()
        self.show(cv2.flip(self.frame, 1))
        with self.assertRaises(ValueError):
            self.vision.align()


if __name__ == '__main__':
    unittest.main()
