"""M1-04: camera pose and foot point from calibration (synthetic geometry only)."""
import json
import math
import time
import unittest

import cv2
import numpy as np

import vision_pose
from sim.camera import MOUNTS, camera_for_mount
from sim.scene import calibration_points, render_clean
from tools.eval_pose import evaluate
from vision import CENTER, SCALE, TARGETS, Vision

OFF_AXIS = ('top', 'bottom', 'left', 'right', 'steep-topleft')


def pose_for(points, camera):
    H = cv2.getPerspectiveTransform(np.asarray(points, np.float32), TARGETS)
    return vision_pose.estimate_pose(H, camera.width, camera.height, SCALE, CENTER)


class FootPoint(unittest.TestCase):
    def test_exact_calibration_recovers_foot_on_all_mounts(self):
        for mount in MOUNTS:
            with self.subTest(mount=mount):
                camera = camera_for_mount(mount)
                pose = pose_for(calibration_points(camera), camera)
                true = camera.foot_point
                direction = vision_pose.angle_difference(vision_pose.direction_degrees(pose['foot']),
                                                         vision_pose.direction_degrees(true))
                self.assertLessEqual(direction, 2.0)
                ratio = math.hypot(*pose['foot']) / math.hypot(*true)
                self.assertLess(abs(ratio - 1.0), 0.10)
                self.assertGreater(pose['height'], 0)

    def test_off_axis_mounts_solve_focal_length(self):
        for mount in OFF_AXIS:
            with self.subTest(mount=mount):
                camera = camera_for_mount(mount)
                pose = pose_for(calibration_points(camera), camera)
                self.assertEqual(pose['source'], 'solved')
                self.assertLess(abs(pose['f'] / camera.f - 1.0), 0.01)
                self.assertAlmostEqual(pose['height'], camera.position[2], delta=1.0)

    def test_click_noise_direction_p95_within_10_degrees_off_axis(self):
        for mount in OFF_AXIS:
            with self.subTest(mount=mount):
                result = evaluate(mount, seeds=50, click_noise=2.0)
                self.assertLessEqual(result['click_noise']['direction_error_deg_p95'], 10.0)

    def test_near_frontal_falls_back_without_raising(self):
        camera = camera_for_mount('near-frontal')
        pose = pose_for(calibration_points(camera), camera)
        self.assertEqual(pose['source'], 'fallback')
        self.assertIn('frontal', pose['reason'])
        self.assertIsNotNone(pose['foot'])

    def test_degenerate_homography_falls_back_without_raising(self):
        for H in (np.zeros((3, 3)), np.full((3, 3), np.nan), np.eye(3)):
            with self.subTest(H=H.tolist()):
                pose = vision_pose.estimate_pose(H, 1920, 1080, SCALE, CENTER)
                self.assertEqual(pose['source'], 'fallback')
                json.dumps(pose, allow_nan=False)

    def test_manual_mount_side(self):
        pose = vision_pose.manual_pose('left', {'f': 1000.0, 'foot': [1.0, 2.0], 'source': 'solved'})
        self.assertEqual(pose['foot'], [-2000.0, 0.0])
        self.assertEqual(pose['source'], 'manual')
        with self.assertRaises(ValueError):
            vision_pose.manual_pose('diagonal')


class VisionPoseState(unittest.TestCase):
    def calibrated(self, mount):
        camera = camera_for_mount(mount)
        vision = Vision()
        vision.frame = render_clean(camera, [])
        vision.timestamp = time.time()
        vision.calibrate(calibration_points(camera).tolist())
        return vision, camera

    def test_calibrate_stores_pose_and_state_exposes_it(self):
        vision, camera = self.calibrated('right')
        state = vision.state()
        json.dumps(state, allow_nan=False)
        self.assertEqual(state['pose']['source'], 'solved')
        self.assertLess(np.linalg.norm(np.subtract(state['foot'], camera.foot_point)), 5.0)
        self.assertIsNone(state['mount_side'])
        for key in ('f', 'C', 'foot', 'source'):
            self.assertIn(key, vision.pose)

    def test_mount_side_override_and_clear(self):
        vision, _ = self.calibrated('top')
        vision.set_mount_side('bottom')
        state = vision.state()
        self.assertEqual(state['pose']['source'], 'manual')
        self.assertEqual(state['foot'], [0.0, 2000.0])
        self.assertEqual(state['mount_side'], 'bottom')
        with self.assertRaises(ValueError):
            vision.set_mount_side('up')
        vision.set_mount_side(None)
        self.assertEqual(vision.state()['pose']['source'], 'solved')
        self.assertLess(abs(vision.state()['foot'][1] + 450), 5)

    def test_align_recomputes_pose(self):
        vision, _ = self.calibrated('left')
        vision.pose = None
        vision.align()
        self.assertEqual(vision.state()['pose']['source'], 'solved')

    def test_invalidation_and_failed_align_clear_pose_but_keep_mount_side(self):
        vision, _ = self.calibrated('left')
        vision.set_mount_side('left')
        vision.invalidate('test invalidation')
        state = vision.state()
        self.assertIsNone(state['pose'])
        self.assertIsNone(state['foot'])
        self.assertEqual(state['mount_side'], 'left')
        vision.set_mount_side(None)
        vision.frame = np.full_like(vision.frame, 127)
        vision.timestamp = time.time()
        with self.assertRaises(ValueError):
            vision.align()
        self.assertIsNone(vision.state()['pose'])
        self.assertIsNone(vision.state()['foot'])

    def test_frontal_test_board_reports_fallback(self):
        rng = np.random.default_rng(149)
        frame = np.full((800, 800, 3), 80, np.uint8)
        for _ in range(1600):
            x, y = rng.integers(155, 646, 2)
            if (x - 400) ** 2 + (y - 400) ** 2 < 240 ** 2:
                cv2.circle(frame, (int(x), int(y)), int(rng.integers(2, 6)),
                           tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
        vision = Vision()
        vision.frame = frame
        vision.timestamp = time.time()
        vision.calibrate([[400, 150], [650, 400], [400, 650], [150, 400]])
        self.assertEqual(vision.state()['pose']['source'], 'fallback')


if __name__ == '__main__':
    unittest.main()
