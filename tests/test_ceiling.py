"""M1-05d: ceiling mount profiles and the throw-by-throw occlusion harness (synthetic only)."""
import math
import unittest

import numpy as np

from sim.camera import (CEILING_DISTANCES, CEILING_HEIGHT_ABOVE_BULL, CEILING_MOUNTS, DEFAULT_HFOV, MOUNTS,
                        S22_HFOV, camera_for_mount, hfov_from_diagonal)
from sim.scene import Dart, calibration_points, dart_silhouette, render_clean
from tests.test_calibration_refine import RefineChecks
from tools import eval_occlusion


class CeilingMounts(unittest.TestCase):
    def test_owner_geometry(self):
        self.assertAlmostEqual(CEILING_HEIGHT_ABOVE_BULL, 526.0)
        self.assertEqual(CEILING_MOUNTS, ('ceiling-0.5ft', 'ceiling-1.5ft', 'ceiling-2ft', 'ceiling-3ft'))
        for name, distance in CEILING_DISTANCES.items():
            camera = camera_for_mount(name)
            self.assertEqual(MOUNTS[name], (0.0, -526.0, distance))
            self.assertEqual(camera.foot_point, (0.0, -526.0))
            self.assertAlmostEqual(camera.hfov, S22_HFOV)
        # 1.5 ft from the wall is about 41 degrees above the board plane (docs/DECISIONS.md #2).
        self.assertAlmostEqual(math.degrees(math.atan2(457.0, 526.0)), 41.0, delta=0.5)

    def test_s22_field_of_view_assumption(self):
        self.assertAlmostEqual(S22_HFOV, 70.43, places=2)
        diagonal = math.hypot(1920, 1080) / 1920 * math.tan(math.radians(S22_HFOV) / 2)
        self.assertAlmostEqual(math.degrees(2 * math.atan(diagonal)), 78.0, places=6)
        self.assertAlmostEqual(hfov_from_diagonal(78.0), S22_HFOV)

    def test_original_mounts_are_unchanged(self):
        expected = {'top': (0.0, -450.0, 500.0), 'bottom': (0.0, 450.0, 500.0), 'left': (-450.0, 0.0, 500.0),
                    'right': (450.0, 0.0, 500.0), 'steep-topleft': (-300.0, -500.0, 350.0),
                    'near-frontal': (150.0, -200.0, 1200.0)}
        for name, position in expected.items():
            self.assertEqual(MOUNTS[name], position)
            self.assertEqual(camera_for_mount(name).hfov, DEFAULT_HFOV)

    def test_board_is_in_frame_and_upright(self):
        for name in CEILING_MOUNTS:
            camera = camera_for_mount(name)
            top, right, bottom, left = calibration_points(camera)
            self.assertTrue((calibration_points(camera) > 0).all())
            self.assertTrue((calibration_points(camera)[:, 0] < camera.width).all())
            self.assertTrue((calibration_points(camera)[:, 1] < camera.height).all())
            self.assertLess(top[1], bottom[1])
            self.assertLess(left[0], right[0])


class CeilingCalibrationRefinement(RefineChecks, unittest.TestCase):
    """M1-05c refinement on the owner's planned and grazing mounts."""

    def test_refines_noisy_clicks_on_planned_ceiling_mount(self):
        self.check_refines('ceiling-1.5ft', 'realistic')

    def test_refines_grazing_ceiling_mount(self):
        self.check_refines('ceiling-0.5ft', 'ideal')


class OcclusionHarness(unittest.TestCase):
    def test_scenarios(self):
        rng = np.random.default_rng(5)
        for _ in range(20):
            stacked = eval_occlusion.turn_darts('stacked-below', rng)
            for upper, lower in zip(stacked, stacked[1:]):
                self.assertTrue(30.0 <= lower.y - upper.y <= 80.0)
            self.assertTrue(all(math.hypot(d.x, d.y) <= 168.0 for d in stacked))
            neighbours = eval_occlusion.turn_darts('t20-neighbours', rng)
            angles = sorted(round(math.degrees(math.atan2(d.x, -d.y)) / 18) for d in neighbours)
            self.assertEqual(angles, [-1, 0, 1])
            self.assertEqual(len(eval_occlusion.turn_darts('t20-group', rng)), 3)

    def test_dart_above_hides_the_board_below_it_from_a_ceiling_camera(self):
        camera = camera_for_mount('ceiling-0.5ft')
        upper = Dart(0.0, -40.0, length=125.0, tilt=10.0, azimuth=0.0)
        lower = Dart(0.0, 0.0, length=125.0, tilt=10.0, azimuth=0.0)
        hidden = eval_occlusion.visibility(camera, [upper, lower], 1)
        self.assertTrue(hidden['hidden_by_earlier'])
        beside = Dart(80.0, 0.0, length=125.0, tilt=10.0, azimuth=0.0)
        self.assertFalse(eval_occlusion.visibility(camera, [upper, beside], 1)['hidden_by_earlier'])

    def test_silhouette_matches_the_rendered_dart(self):
        camera = camera_for_mount('top')
        dart = Dart(20.0, 30.0)
        mask = dart_silhouette(camera, [dart]) >= 128
        changed = np.abs(render_clean(camera, [dart]).astype(int) - render_clean(camera, []).astype(int)).max(axis=2)
        self.assertGreater((mask & (changed > 0)).sum() / mask.sum(), 0.97)
        without_point = dart_silhouette(camera, [dart], include_point=False) >= 128
        self.assertLess(without_point.sum(), mask.sum())

    def test_cell_runs_throw_by_throw(self):
        key, summary, records = eval_occlusion.run_cell(('ceiling-1.5ft', 'ideal', 4, 1, None, 4))
        self.assertEqual(key, ('ceiling-1.5ft', 'ideal', 4))
        self.assertEqual(len(records), 3 * len(eval_occlusion.SCENARIOS))
        self.assertEqual([r['dart'] for r in records[:3]], [1, 2, 3])
        self.assertEqual(summary['all']['dart2']['n'], len(eval_occlusion.SCENARIOS))
        self.assertEqual(summary['calibration']['refined'], summary['calibration']['n'])
        for record in records:
            self.assertIn(record['outcome'], ('exact', 'wrong_sector', 'wrong_ring', 'no_proposal'))


if __name__ == '__main__':
    unittest.main()
