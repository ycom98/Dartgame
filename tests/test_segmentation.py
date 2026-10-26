"""M1-05b: colour-aware dart segmentation (synthetic images only; not real-board evidence)."""
import math
import unittest

import cv2
import numpy as np

import vision_segment
from core import score_point
from vision import CENTER, SCALE, SIZE, Vision, half_contrast_end, refine_tip

CREAM = (176, 216, 232)
BLACK = (24, 24, 24)
RED = (38, 36, 190)
GREEN = (58, 132, 34)
FOOT_LEFT = (CENTER - 450 * SCALE, CENTER)  # a camera mounted to the left of the board


def board_base():
    """A warped-board stand-in: black/cream quadrant sectors with a red ring, in warp pixels."""
    base = np.zeros((SIZE, SIZE, 3), np.uint8)
    base[:, :] = BLACK
    base[:CENTER_INT, :CENTER_INT] = CREAM
    base[CENTER_INT:, CENTER_INT:] = CREAM
    cv2.circle(base, (CENTER_INT, CENTER_INT), int(103 * SCALE), RED, int(8 * SCALE))
    return base


CENTER_INT = int(CENTER)


def mm(x, y):
    return int(round(CENTER + x * SCALE)), int(round(CENTER + y * SCALE))


def segment(frame, base, foot=FOOT_LEFT):
    return vision_segment.segment(frame, base, SCALE, CENTER, 200.0, np.float32(foot))


class ChangeDetection(unittest.TestCase):
    def test_colour_change_with_equal_gray_level_is_detected(self):
        base = board_base()
        frame = base.copy()
        # A lavender bar on cream with almost the same gray level as cream: a grayscale difference misses it.
        colour = (230, 200, 240)
        cv2.line(frame, mm(-80, -60), mm(-20, -60), colour, 6)
        gray_diff = cv2.absdiff(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.cvtColor(base, cv2.COLOR_BGR2GRAY))
        self.assertLess(int(gray_diff[mm(-50, -60)[1], mm(-50, -60)[0]]), 5)
        result = segment(frame, base)
        self.assertEqual(result.kind, 'dart')

    def test_exposure_and_white_balance_drift_is_not_a_change(self):
        base = board_base()
        for gains in [(1.08, 1.08, 1.08), (0.85, 0.85, 0.85), (1.05, 1.0, 0.93)]:
            with self.subTest(gains=gains):
                frame = np.clip(base.astype(np.float32) * np.float32(gains), 0, 255).astype(np.uint8)
                result = segment(frame, base)
                self.assertEqual(result.kind, 'none')
                for measured, true in zip(result.gains, gains):
                    self.assertAlmostEqual(measured, true, delta=0.02)

    def test_whole_board_change_is_large_change(self):
        base = board_base()
        self.assertEqual(segment(np.zeros_like(base), base).kind, 'large_change')

    def test_cast_shadow_alone_is_not_a_dart(self):
        base = board_base()
        mask = np.zeros(base.shape[:2], np.uint8)
        cv2.line(mask, mm(-100, -40), mm(-30, -10), 255, 14)
        frame = base.copy()
        frame[mask > 0] = (base[mask > 0] * 0.55).astype(np.uint8)
        result = segment(frame, base)
        self.assertEqual(result.kind, 'none')
        self.assertGreater(result.shadow_pixels, 100)

    def test_noisy_shadow_on_coloured_rings_is_shadow_but_a_dark_dart_is_not(self):
        rng = np.random.default_rng(4)
        base = board_base()
        noisy_base = np.clip(base + rng.normal(0, 4, base.shape), 0, 255).astype(np.uint8)
        frame = base.astype(np.float32)
        ring = np.zeros(base.shape[:2], np.uint8)
        cv2.circle(ring, (CENTER_INT, CENTER_INT), int(103 * SCALE), 255, int(8 * SCALE))
        shade = np.zeros(base.shape[:2], np.uint8)
        cv2.rectangle(shade, mm(-120, -120), mm(120, 120), 255, -1)
        region = (ring > 0) & (shade > 0)
        frame[region] *= 0.55
        frame = np.clip(frame + rng.normal(0, 4, base.shape), 0, 255).astype(np.uint8)
        corrected = frame.astype(np.float32)
        shadow = vision_segment.shadow_pixels(corrected, noisy_base, region, 30.0)
        self.assertGreater(shadow[region].mean(), 0.9)
        dart = noisy_base.copy()
        dart[region] = (52, 54, 58)  # a black barrel over the red ring
        dart_shadow = vision_segment.shadow_pixels(dart.astype(np.float32), noisy_base, region, 30.0)
        self.assertLess(dart_shadow[region].mean(), 0.05)  # at most a few blended edge pixels

    def test_neutral_dart_on_cream_is_not_mistaken_for_shadow(self):
        base = board_base()
        frame = base.copy()
        cv2.line(frame, mm(-90, -50), mm(-30, -50), (70, 70, 76), 10)  # the default barrel colour
        result = segment(frame, base)
        self.assertEqual(result.kind, 'dart')
        self.assertGreater(len(result.points), 0.6 * 60 * SCALE * 10)


    def test_faint_point_connected_to_a_strong_change_is_kept(self):
        base = board_base()
        frame = base.copy()
        cv2.line(frame, mm(-90, -50), mm(-50, -50), (70, 70, 76), 10)  # barrel: strong change
        faint = tuple(int(c) - 22 for c in CREAM)  # point: below the threshold, above half of it
        cv2.line(frame, mm(-110, -50), mm(-90, -50), faint, 3)
        cv2.circle(frame, mm(40, 60), 2, faint, -1)  # an isolated faint speck
        result = segment(frame, base)
        self.assertEqual(result.kind, 'dart')
        self.assertLessEqual(float(result.points[:, 0].min()), mm(-109, 0)[0])
        self.assertEqual(len(result.groups), 1)

    def test_blended_silver_point_on_cream_is_not_shadow(self):
        base = board_base()
        frame = base.copy()
        blend = tuple(int(0.7 * p + 0.3 * c) for p, c in zip((172, 174, 180), CREAM))
        cv2.line(frame, mm(-100, -50), mm(-60, -50), blend, 4)
        corrected, difference = vision_segment.normalised_difference(frame, base, (1.0, 1.0, 1.0))
        changed = difference > 0
        self.assertFalse(vision_segment.shadow_pixels(corrected, base, changed, 30.0).any())


class FragmentGrouping(unittest.TestCase):
    def test_collinear_fragments_with_a_gap_are_one_dart(self):
        base = board_base()
        frame = base.copy()
        # Point and barrel, a 35 mm gap (an invisible shaft), then a broad flight, along one line.
        cv2.line(frame, mm(-120, -40), mm(-95, -40), (172, 174, 180), 4)
        cv2.line(frame, mm(-95, -40), mm(-60, -40), GREEN, 11)
        flight = np.array([mm(-25, -40), mm(-5, -55), mm(10, -55), mm(10, -25), mm(-5, -25)], np.int32)
        cv2.fillPoly(frame, [flight], (200, 120, 20))
        result = segment(frame, base)
        self.assertEqual(result.kind, 'dart')
        self.assertEqual(sum(len(g.points) >= vision_segment.MIN_DART_MM2 * SCALE ** 2 for g in result.groups), 1)

    def test_fragment_off_the_axis_is_not_merged(self):
        grouper = vision_segment.FragmentGrouper(SCALE, foot=None)

        def bar(x0, x1, y):
            mask = np.zeros((SIZE, SIZE), np.uint8)
            mask[y:y + 4, x0:x1] = 255
            return vision_segment.fragments(mask, 1)[0]

        shaft = bar(200, 300, 300)
        aside = bar(330, 360, 380)
        ahead = bar(330, 360, 300)
        self.assertEqual(len(grouper.group([shaft, aside])), 2)
        self.assertEqual(len(grouper.group([shaft, ahead])), 1)

    def test_past_the_tip_only_a_point_shaped_fragment_joins(self):
        # FOOT_LEFT: the tip end of this dart is its left end. A gap, then something further left.
        grouper = vision_segment.FragmentGrouper(SCALE, foot=FOOT_LEFT)

        def blob(mask):
            return vision_segment.fragments(mask, 1)[0]

        body = np.zeros((SIZE, SIZE), np.uint8)
        cv2.line(body, mm(-60, -40), mm(0, -40), 255, 9)
        point = np.zeros((SIZE, SIZE), np.uint8)
        cv2.line(point, mm(-85, -40), mm(-72, -40), 255, 4)
        cloud = np.zeros((SIZE, SIZE), np.uint8)
        rng = np.random.default_rng(1)
        for x, y in rng.uniform([-88, -46], [-72, -34], (60, 2)):
            cloud[mm(x, y)[1], mm(x, y)[0]] = 255
        cloud = cv2.dilate(cloud, np.ones((2, 2), np.uint8))
        cloud_group = grouper.group(vision_segment.fragments(cloud, 1))[0]
        self.assertEqual(len(grouper.group([blob(body), blob(point)])), 1)
        self.assertEqual(len(grouper.group([blob(body), cloud_group])), 2)

    def test_two_separate_darts_are_reported_as_multiple(self):
        base = board_base()
        frame = base.copy()
        cv2.line(frame, mm(-120, -60), mm(-60, -60), GREEN, 10)
        cv2.line(frame, mm(40, 90), mm(100, 90), (200, 120, 20), 10)
        self.assertEqual(segment(frame, base).kind, 'multiple')

    def test_small_speck_is_not_a_dart(self):
        base = board_base()
        frame = base.copy()
        cv2.circle(frame, mm(-50, -50), 2, GREEN, -1)
        self.assertEqual(segment(frame, base).kind, 'none')

    def test_oversized_change_is_too_large(self):
        base = board_base()
        frame = base.copy()
        cv2.circle(frame, mm(-60, -60), int(60 * SCALE), GREEN, -1)
        self.assertEqual(segment(frame, base).kind, 'too_large')


class TipRefinement(unittest.TestCase):
    def test_tip_is_centre_of_the_point_end_even_with_a_skewed_axis(self):
        # A 4 px wide point along +x ending at x=300, y=200; the blob axis guess is 8 degrees off.
        points = np.array([[x, y] for x in range(260, 301) for y in range(198, 203)], np.float32)
        skew = math.radians(8)
        direction = np.array([math.cos(skew), math.sin(skew)], np.float32)
        corner = points[np.argmax(points @ direction)]
        tip, axis = refine_tip(points, corner, direction)
        self.assertAlmostEqual(float(tip[0]), 300.0, delta=0.6)
        self.assertAlmostEqual(float(tip[1]), 200.0, delta=0.6)
        self.assertGreater(float(axis[0]), 0.99)


    def test_half_contrast_end_finds_a_blurred_edge_independent_of_contrast(self):
        for contrast in (40.0, 160.0):
            with self.subTest(contrast=contrast):
                difference = np.zeros((SIZE, SIZE), np.float32)
                difference[198:203, 200:300] = contrast  # a rod ending at x = 299.5
                difference = cv2.GaussianBlur(difference, (0, 0), 1.2)
                # Start from a pixel end chosen by a threshold of 30 (too far in or out).
                start = np.float32([297.5 if contrast == 40.0 else 301.0, 200.0])
                tip = half_contrast_end(difference, start, np.float32([1.0, 0.0]))
                self.assertAlmostEqual(float(tip[0]), 299.5, delta=0.35)
                self.assertAlmostEqual(float(tip[1]), 200.0, delta=0.01)


class EndToEnd(unittest.TestCase):
    """Rendered darts through Vision.ingest (sim/), including cases M1-05 fragmented."""

    @staticmethod
    def detect(mount, darts, shadow=None):
        from sim import camera_for_mount
        from sim.scene import calibration_points, render_clean
        camera = camera_for_mount(mount)
        vision = Vision()
        empty = cv2.imencode('.bmp', render_clean(camera, []))[1].tobytes()
        vision.ingest(empty)
        vision.calibrate(calibration_points(camera).tolist())
        for _ in range(3):
            vision.ingest(empty)
        vision.reset_base()
        scene = cv2.imencode('.bmp', render_clean(camera, darts, shadow))[1].tobytes()
        for _ in range(4):
            vision.ingest(scene)
        return vision

    def test_black_shaft_over_black_segment_is_one_dart(self):
        from sim.scene import Dart
        # Black shaft on a black segment: the M1-05 detector split this dart into fragments.
        dart = Dart(x=40.0, y=-60.0, length=125.0, tilt=12.0, azimuth=0.0, spin=20.0,
                    barrel_colour=(52, 54, 58), shaft_colour=(30, 30, 30), flight_colour=(30, 30, 200))
        vision = self.detect('left', [dart])
        proposal = vision.proposal
        self.assertIsNotNone(proposal, vision.message)
        self.assertEqual(proposal['label'], score_point(dart.x, dart.y)['label'])
        self.assertLess(math.hypot(proposal['x'] - dart.x, proposal['y'] - dart.y), 2.0)

    def test_hard_shadow_does_not_become_the_tip(self):
        from sim.scene import DEFAULT_LIGHT, Dart
        dart = Dart(x=-30.0, y=-50.0, length=125.0, tilt=15.0, azimuth=0.0, spin=10.0,
                    barrel_colour=(70, 70, 76), shaft_colour=(220, 220, 220), flight_colour=(200, 120, 20))
        for mount in ('bottom', 'right'):
            with self.subTest(mount=mount):
                proposal = self.detect(mount, [dart], DEFAULT_LIGHT).proposal
                self.assertIsNotNone(proposal)
                self.assertLess(math.hypot(proposal['x'] - dart.x, proposal['y'] - dart.y), 2.0)

    def test_two_new_darts_give_no_single_proposal(self):
        from sim.scene import Dart
        darts = [Dart(x=-60.0, y=-60.0, tilt=10.0), Dart(x=70.0, y=50.0, tilt=10.0)]
        vision = self.detect('top', darts)
        self.assertIsNone(vision.proposal)
        self.assertIn('More than one new dart', vision.message)
        self.assertEqual(vision.segmentation.kind, 'multiple')


if __name__ == '__main__':
    unittest.main()
