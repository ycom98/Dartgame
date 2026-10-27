"""M1-05e: segmentation hardening (QA D-A, D-B, D-C on M1-05b). Synthetic images only."""
import time
import unittest
from unittest import mock

import cv2
import numpy as np

import vision_segment
from tests.test_segmentation import GREEN, board_base, mm, segment
from vision import SCALE, SIZE, Vision


def specks(base, rng, count, colour=None, radius_mm=(1.0, 2.0)):
    """base plus count isolated small discs (each well below a dart fragment)."""
    frame = base.copy()
    for _ in range(count):
        radius = np.sqrt(rng.uniform()) * 165.0
        angle = rng.uniform(0.0, 2.0 * np.pi)
        centre = mm(radius * np.sin(angle), -radius * np.cos(angle))
        fill = colour or tuple(int(v) for v in rng.integers(0, 256, 3))
        cv2.circle(frame, centre, max(1, int(round(rng.uniform(*radius_mm) * SCALE))), fill, -1, cv2.LINE_AA)
    return frame


def reference_groups(grouper, pieces):
    """Grouping without the 'apart' cache: merge any pair that belongs until none does."""
    groups = list(pieces)
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if grouper.belongs(groups[i], groups[j]):
                    groups[i] = groups[i].merged(groups[j])
                    del groups[j]
                    merged = True
                    break
            if merged:
                break
    return groups


def pixel_sets(groups):
    return sorted(tuple(sorted(map(tuple, g.points.astype(int).tolist()))) for g in groups)


class StableCacheKeys(unittest.TestCase):
    """D-A: the 'already apart' cache was keyed by id(), which CPython reuses for freed merged blobs."""

    def test_serials_are_unique_and_merges_get_new_ones(self):
        mask = np.zeros((SIZE, SIZE), np.uint8)
        mask[100:110, 100:140] = 255
        mask[200:210, 100:140] = 255
        first, second = vision_segment.fragments(mask, 1)
        merged = first.merged(second)
        self.assertEqual(len({first.serial, second.serial, merged.serial}), 3)
        self.assertEqual(merged.largest, max(len(first.points), len(second.points)))

    def test_grouping_matches_an_uncached_reference(self):
        rng = np.random.default_rng(11)
        grouper = vision_segment.FragmentGrouper(SCALE, foot=np.float32((350 - 450 * SCALE, 350)))
        for trial in range(40):
            mask = np.zeros((SIZE, SIZE), np.uint8)
            # A dart-like bar broken into pieces, plus scattered pieces of mixed sizes.
            y = int(rng.integers(150, 550))
            for x0 in range(150, 450, 40):
                mask[y:y + int(rng.integers(3, 9)), x0:x0 + int(rng.integers(10, 30))] = 255
            for _ in range(int(rng.integers(5, 25))):
                x, y = rng.integers(80, 620, 2)
                size = int(rng.integers(2, 14))
                mask[y:y + size, x:x + int(rng.integers(2, 14))] = 255
            pieces = vision_segment.fragments(mask, 3)
            with self.subTest(trial=trial):
                self.assertEqual(pixel_sets(grouper.group(pieces)), pixel_sets(reference_groups(grouper, pieces)))


class FragmentCap(unittest.TestCase):
    """D-B: the pairwise grouping cost grew with the fragment count (about 1 s at 200 specks)."""

    def test_many_fragments_are_a_noisy_scene_without_grouping(self):
        base = board_base()
        frame = specks(base, np.random.default_rng(2), 200)
        with mock.patch.object(vision_segment.FragmentGrouper, 'group') as group:
            result = segment(frame, base)
        self.assertEqual(result.kind, 'noisy')
        self.assertGreater(result.fragment_count, vision_segment.MAX_FRAGMENTS)
        group.assert_not_called()

    def test_worst_case_time_is_bounded(self):
        base = board_base()
        rng = np.random.default_rng(4)
        frames = [specks(base, rng, count) for count in (vision_segment.MAX_FRAGMENTS - 2, 200)]
        segment(frames[0], base)  # warm the caches
        for frame in frames:
            started = time.perf_counter()
            segment(frame, base)
            # About 60 ms unloaded; M1-05b took about 1 s at 200 specks. Loose bound for loaded CI.
            self.assertLess(time.perf_counter() - started, 0.5)

    def test_many_large_fragments_are_noisy_and_fast(self):
        base = board_base()
        rng = np.random.default_rng(21)
        frame = base.copy()
        for _ in range(30):  # 25 x 3 mm strokes, each core-sized: an arm shadow broken into pieces
            x, y = rng.uniform(-150, 120, 2)
            angle = rng.uniform(0, np.pi)
            end = (x + 25 * np.cos(angle), y + 25 * np.sin(angle))
            cv2.line(frame, mm(x, y), mm(*end), GREEN, int(3 * SCALE))
        segment(frame, base)
        started = time.perf_counter()
        result = segment(frame, base)
        self.assertEqual(result.kind, 'noisy')
        self.assertLess(time.perf_counter() - started, 0.5)

    def test_vision_reports_a_noisy_scene(self):
        vision = Vision()
        vision.segmentation = object()
        vision.invalidate('test')
        self.assertIsNone(vision.segmentation)
        self.assertIn('Too many small changes', __import__('vision').SEGMENTATION_MESSAGES['noisy'])


class DartPlausibility(unittest.TestCase):
    """D-C: scattered specks with no dart were chained into a 'dart' (9 of 30 boards in QA)."""

    def test_scattered_red_specks_are_never_a_dart(self):
        base = board_base()
        rng = np.random.default_rng(9)
        kinds = [segment(specks(base, rng, 20, colour=(40, 40, 200)), base).kind for _ in range(30)]
        self.assertNotIn('dart', kinds)

    def test_scattered_coloured_specks_are_never_a_dart(self):
        base = board_base()
        rng = np.random.default_rng(10)
        for count in (5, 10, 20, 35):
            with self.subTest(count=count):
                kinds = [segment(specks(base, rng, count), base).kind for _ in range(10)]
                self.assertNotIn('dart', kinds)

    def test_a_dart_among_specks_is_still_found(self):
        base = board_base()
        frame = specks(base, np.random.default_rng(12), 10, radius_mm=(0.8, 1.2))
        cv2.line(frame, mm(-120, -60), mm(-40, -60), GREEN, 10)
        self.assertEqual(segment(frame, base).kind, 'dart')

    def test_plausibility_rules(self):
        def blob(draw):
            mask = np.zeros((SIZE, SIZE), np.uint8)
            draw(mask)
            pieces = vision_segment.fragments(mask, 1)
            group = pieces[0]
            for piece in pieces[1:]:
                group = group.merged(piece)
            return group

        dart = blob(lambda m: cv2.line(m, mm(-80, 0), mm(0, 0), 255, 12))
        short = blob(lambda m: cv2.circle(m, mm(0, 0), int(5 * SCALE), 255, -1))
        no_core = blob(lambda m: [cv2.circle(m, mm(x, 0), int(2.5 * SCALE), 255, -1) for x in range(-60, 0, 8)])
        thin = blob(lambda m: (cv2.circle(m, mm(0, 0), int(4.5 * SCALE), 255, -1),
                               cv2.line(m, mm(5, 0), mm(150, 0), 255, 1)))
        self.assertTrue(vision_segment.plausible_dart(dart, SCALE))
        self.assertFalse(vision_segment.plausible_dart(short, SCALE))  # 10 mm long
        self.assertFalse(vision_segment.plausible_dart(no_core, SCALE))  # specks only
        self.assertFalse(vision_segment.plausible_dart(thin, SCALE))  # a long hair-thin chain

    def test_a_dart_shaped_fleck_among_other_flecks_is_noisy(self):
        base = board_base()
        frame = base.copy()
        cv2.line(frame, mm(-100, -60), mm(-80, -60), GREEN, 8)  # short and wide: plausible on its own
        alone = segment(frame, base)
        self.assertEqual(alone.kind, 'dart')
        for y in (40, 110):  # two dart-sized round blobs, not on one axis: too short to be darts
            cv2.circle(frame, mm(40, y), int(4.5 * SCALE), (200, 120, 20), -1)
        result = segment(frame, base)
        self.assertEqual(result.implausible, 2)
        self.assertEqual(result.kind, 'noisy')

    def test_a_rejected_dart_sized_change_is_not_a_silent_ready(self):
        base = board_base()
        frame = base.copy()
        cv2.circle(frame, mm(-60, -60), int(5 * SCALE), GREEN, -1)  # 78 mm2 but only 10 mm long
        result = segment(frame, base)
        self.assertEqual(result.implausible, 1)
        self.assertEqual(result.kind, 'noisy')

    def test_specks_do_not_chain_without_a_core(self):
        grouper = vision_segment.FragmentGrouper(SCALE, foot=None)
        mask = np.zeros((SIZE, SIZE), np.uint8)
        for x in range(-60, 0, 10):  # collinear 3 mm specks, 7 mm apart: once chained by the axis wedge
            cv2.circle(mask, mm(x, 0), int(1.5 * SCALE), 255, -1)
        pieces = vision_segment.fragments(mask, 1)
        self.assertEqual(len(grouper.group(pieces)), len(pieces))


class SpeckleTrialsInTheHarness(unittest.TestCase):
    def test_speckle_false_proposals_are_reported(self):
        from tools import eval_detection
        report = eval_detection.run(['left'], 1, 3, 'realistic', speckle_trials=4)
        result = report['mounts']['left']['speckle_false_proposals']
        self.assertEqual(result['n'], 4)
        self.assertEqual(result['false_proposals'], 0)
        self.assertEqual(report['settings']['speckle_trials_per_mount'], 4)


if __name__ == '__main__':
    unittest.main()
