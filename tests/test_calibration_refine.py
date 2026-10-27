"""M1-05c: automatic refinement of the four-click calibration from the board's own edges (synthetic)."""
import time
import unittest

import cv2
import numpy as np

import vision
import vision_calibrate
from sim.camera import camera_for_mount
from sim.scene import PROFILES, Dart, calibration_points, degrade, render_clean
from tools.eval_detection import calibration_error_mm


def click_homography(camera, offsets):
    points = calibration_points(camera).astype(np.float64) + np.asarray(offsets, np.float64)
    return cv2.getPerspectiveTransform(points.astype(np.float32), vision.TARGETS)


def map_error_mm(camera, H):
    """Largest error (mm) of an image -> warp homography within the double ring (uses the true camera)."""
    true_map = np.linalg.inv(camera.plane_homography())
    return vision_calibrate.board_shift_mm(true_map, np.linalg.inv(vision_calibrate.scaling(vision.SCALE,
                                                                                            vision.CENTER)) @ H)


# A fixed, deliberately bad set of clicks (px): about 2-5 mm of board error on these mounts.
CLICK_OFFSETS = [[2.5, -1.5], [-2.0, 2.5], [1.5, 2.0], [-2.5, -2.0]]


class RefineChecks:
    """check_refines for TestCase classes (also used by tests/test_ceiling.py)."""

    def check_refines(self, mount, profile):
        camera = camera_for_mount(mount)
        frame, _ = degrade(render_clean(camera, []), PROFILES[profile], np.random.default_rng(7))
        H = click_homography(camera, CLICK_OFFSETS)
        before = map_error_mm(camera, H)
        started = time.perf_counter()
        refined, report = vision_calibrate.refine(frame, H, vision.SCALE, vision.CENTER)
        seconds = time.perf_counter() - started
        after = map_error_mm(camera, refined)
        self.assertEqual(report['method'], 'refined', report)
        self.assertEqual(report['confidence'], 'high')
        self.assertIsNone(report['reason'])
        self.assertGreater(before, 1.5)
        self.assertLess(after, 0.5)
        self.assertLess(report['residual_mm'], vision_calibrate.MAX_RESIDUAL_MM)
        self.assertGreater(report['click_offset_mm'], 1.0)
        self.assertLess(seconds, 2.0)
        return report


class RefineSyntheticBoard(RefineChecks, unittest.TestCase):
    def test_refines_noisy_clicks_on_side_mount(self):
        self.check_refines('left', 'realistic')

    def test_refines_noisy_clicks_on_steep_mount(self):
        self.check_refines('steep-topleft', 'ideal')

    def test_darts_in_the_calibration_image_are_outliers(self):
        camera = camera_for_mount('top')
        darts = [Dart(0.0, -103.0, tilt=12, azimuth=5), Dart(10.0, -100.0, tilt=20, azimuth=-15),
                 Dart(-60.0, 40.0, tilt=10, azimuth=30)]
        frame = render_clean(camera, darts)
        refined, report = vision_calibrate.refine(frame, click_homography(camera, CLICK_OFFSETS),
                                                  vision.SCALE, vision.CENTER)
        self.assertEqual(report['method'], 'refined', report)
        self.assertLess(map_error_mm(camera, refined), 0.5)


class RefineDegradesGracefully(unittest.TestCase):
    def test_blank_image_keeps_the_clicks(self):
        camera = camera_for_mount('top')
        H = click_homography(camera, CLICK_OFFSETS)
        blank = np.full((camera.height, camera.width, 3), 120, np.uint8)
        kept, report = vision_calibrate.refine(blank, H, vision.SCALE, vision.CENTER)
        self.assertTrue(np.allclose(kept, H))
        self.assertEqual(report['method'], 'clicks')
        self.assertEqual(report['confidence'], 'low')
        self.assertTrue(report['reason'])

    def test_random_texture_keeps_the_clicks(self):
        rng = np.random.default_rng(3)
        frame = cv2.resize(rng.integers(0, 256, (108, 192, 3), dtype=np.uint8), (1920, 1080),
                           interpolation=cv2.INTER_NEAREST)
        H = click_homography(camera_for_mount('left'), [[0, 0]] * 4)
        kept, report = vision_calibrate.refine(frame, H, vision.SCALE, vision.CENTER)
        self.assertEqual(report['method'], 'clicks', report)
        self.assertTrue(np.allclose(kept, H))

    def test_partly_hidden_board_keeps_the_clicks(self):
        camera = camera_for_mount('right')
        frame = render_clean(camera, []).copy()
        frame[:, : camera.width * 3 // 5] = 90  # most of the board covered (a person in front of it)
        H = click_homography(camera, CLICK_OFFSETS)
        kept, report = vision_calibrate.refine(frame, H, vision.SCALE, vision.CENTER)
        self.assertEqual(report['method'], 'clicks', report)
        self.assertTrue(np.allclose(kept, H))

    def test_model_samples_avoid_edge_junctions(self):
        points, normals, kinds, indices = vision_calibrate.model_points()
        self.assertTrue(np.allclose(np.linalg.norm(normals, axis=1), 1.0))
        rings = kinds == 0
        radius = np.linalg.norm(points, axis=1)
        self.assertTrue(np.allclose(radius[rings], np.asarray(vision_calibrate.RING_EDGES)[indices[rings]]))
        gaps = np.abs(radius[~rings, None] - np.asarray(vision_calibrate.RING_EDGES)[None, :]).min(axis=1)
        self.assertGreaterEqual(gaps.min() + 1e-9, vision_calibrate.JUNCTION_CLEARANCE_MM)
        self.assertEqual(set(indices[~rings]), set(range(20)))


class VisionReportsCalibrationQuality(unittest.TestCase):
    def calibrated(self, refine):
        camera = camera_for_mount('bottom')
        clean = render_clean(camera, [])
        v = vision.Vision()
        v.refine_calibration = refine
        ok, data = cv2.imencode('.png', clean)
        v.ingest(data.tobytes())
        points = calibration_points(camera).astype(np.float64) + np.asarray(CLICK_OFFSETS)
        result = v.calibrate(points.tolist())
        return v, camera, result

    def test_state_exposes_refined_calibration(self):
        v, camera, result = self.calibrated(True)
        calibration = v.state()['calibration']
        self.assertEqual(calibration['method'], 'refined')
        self.assertEqual(calibration['confidence'], 'high')
        self.assertIsInstance(calibration['residual_mm'], float)
        self.assertIsInstance(calibration['click_offset_mm'], float)
        self.assertEqual(result['calibration']['method'], 'refined')
        self.assertLess(calibration_error_mm(v, camera)[1], 0.5)
        # The pose and the alignment reference use the refined geometry.
        self.assertTrue(np.allclose(v.reference_H, v.H))
        self.assertEqual(v.state()['pose']['source'], 'solved')

    def test_refinement_can_be_turned_off(self):
        v, camera, _ = self.calibrated(False)
        calibration = v.state()['calibration']
        self.assertEqual(calibration['method'], 'clicks')
        self.assertEqual(calibration['reason'], 'refinement disabled')
        self.assertGreater(calibration_error_mm(v, camera)[1], 1.5)

    def test_low_confidence_message_names_the_reason(self):
        v = vision.Vision()
        v.frame = np.full((1080, 1920, 3), 100, np.uint8)
        v.timestamp = time.time()
        v.calibrate(calibration_points(camera_for_mount('left')).tolist())
        self.assertEqual(v.state()['calibration']['method'], 'clicks')
        self.assertIn('four points only', v.message)


if __name__ == '__main__':
    unittest.main()


class QAFixes(unittest.TestCase):
    """M1-05c/e QA: D1 sloppy clicks, D3 grayscale input, D6 click order, D7 report keys."""

    def test_sloppy_clicks_still_refine(self):
        for mount in ('ceiling-1.5ft', 'left'):
            camera = camera_for_mount(mount)
            clean = render_clean(camera, [])
            for sigma in (6.0, 8.0):
                rng = np.random.default_rng([int(sigma), len(mount)])
                for _ in range(4):
                    frame, _ = degrade(clean, PROFILES['realistic'], rng)
                    H = click_homography(camera, rng.normal(0.0, sigma, (4, 2)))
                    refined, report = vision_calibrate.refine(frame, H, vision.SCALE, vision.CENTER)
                    with self.subTest(mount=mount, sigma=sigma):
                        self.assertEqual(report['method'], 'refined', report)
                        self.assertLess(map_error_mm(camera, refined), 0.6)

    def test_click_error_limit_still_catches_a_sector_slip(self):
        for mount in ('ceiling-0.5ft', 'ceiling-1.5ft', 'top', 'near-frontal'):
            clicked = calibration_points(camera_for_mount(mount)).astype(np.float64)
            limit = vision_calibrate.click_error_limit(clicked)
            radius = np.linalg.norm(clicked - clicked.mean(axis=0), axis=1).mean()
            slip = 2 * radius * np.sin(np.radians(9.0))  # a click moved by one sector along the ring
            with self.subTest(mount=mount):
                self.assertGreaterEqual(limit, 30.0)
                self.assertLess(limit, slip)
        inliers = np.ones(2000, bool)
        self.assertIn('implausibly far', vision_calibrate.rejection_reason(inliers, 0.3, 12, 20, 80.0, 30.0))
        self.assertIsNone(vision_calibrate.rejection_reason(inliers, 0.3, 12, 20, 25.0, 30.0))

    def test_grayscale_and_malformed_images_never_raise(self):
        camera = camera_for_mount('top')
        H = click_homography(camera, CLICK_OFFSETS)
        gray = cv2.cvtColor(render_clean(camera, []), cv2.COLOR_BGR2GRAY)
        _, report = vision_calibrate.refine(gray, H, vision.SCALE, vision.CENTER)
        self.assertIn(report['method'], ('refined', 'clicks'))
        for bad in (np.zeros((10,), np.uint8), np.zeros((1080, 1920, 4), np.uint8), None):
            kept, report = vision_calibrate.refine(bad, H, vision.SCALE, vision.CENTER)
            self.assertEqual(report['method'], 'clicks')
            self.assertTrue(np.allclose(kept, H))

    def test_clicks_in_the_wrong_order_are_flagged(self):
        camera = camera_for_mount('left')
        frame = render_clean(camera, [])
        points = calibration_points(camera).astype(np.float64)
        rotated = np.roll(points, 1, axis=0)  # 11, 20, 6, 3 clicked as 20, 6, 3, 11
        H = cv2.getPerspectiveTransform(rotated.astype(np.float32), vision.TARGETS)
        _, report = vision_calibrate.refine(frame, H, vision.SCALE, vision.CENTER)
        self.assertEqual(report['method'], 'refined')
        self.assertEqual(report['confidence'], 'low')
        self.assertIn('click order', report['warning'])
        _, good = vision_calibrate.refine(frame, click_homography(camera, CLICK_OFFSETS), vision.SCALE, vision.CENTER)
        self.assertIsNone(good['warning'])
        self.assertEqual(good['confidence'], 'high')

    def test_every_report_has_the_same_keys(self):
        camera = camera_for_mount('bottom')
        H = click_homography(camera, CLICK_OFFSETS)
        _, refined = vision_calibrate.refine(render_clean(camera, []), H, vision.SCALE, vision.CENTER)
        _, failed = vision_calibrate.refine(np.zeros((1080, 1920, 3), np.uint8), H, vision.SCALE, vision.CENTER)
        disabled = vision_calibrate.clicks_report('refinement disabled', confidence=None)
        self.assertEqual(set(refined), set(failed))
        self.assertEqual(set(refined), set(disabled))
