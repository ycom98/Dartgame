"""M1-02: synthetic board and dart scene renderer (simulation only, not hardware evidence)."""
import contextlib
import os
import tempfile
import time
import unittest

import cv2
import numpy as np

from core import near_wire, score_point
from sim import camera_for_mount, MOUNTS, PROFILES, random_dart, render_scene
from sim.board import board_texture, mm_to_texture_matrix
from sim.preview import main as preview_main
from sim.scene import Dart, DEFAULT_LIGHT
from vision import SCALE, CENTER, Vision


class CameraGeometry(unittest.TestCase):
    def test_s20_centre_round_trips_through_plane_homography_for_every_mount(self):
        board_point = np.array([0.0, -135.0])
        for name in MOUNTS:
            with self.subTest(mount=name):
                camera = camera_for_mount(name)
                pixel = camera.project_plane([board_point])[0]
                G = camera.plane_homography()
                back = np.linalg.inv(G) @ np.array([pixel[0], pixel[1], 1.0])
                back = back[:2] / back[2]
                self.assertLess(float(np.linalg.norm(back - board_point)), 0.5)

    def test_bull_projects_to_image_centre_and_foot_point_is_position(self):
        for name, position in MOUNTS.items():
            with self.subTest(mount=name):
                camera = camera_for_mount(name)
                centre = camera.project_plane([[0.0, 0.0]])[0]
                self.assertLess(float(np.linalg.norm(centre - [960, 540])), 1e-6)
                self.assertEqual(camera.foot_point, position[:2])
                self.assertAlmostEqual(float(np.linalg.det(camera.R)), 1.0, places=9)

    def test_image_orientation_has_20_at_top_and_6_at_right(self):
        for name in MOUNTS:
            with self.subTest(mount=name):
                points = camera_for_mount(name).project_plane([[0, -170], [170, 0], [0, 170], [-170, 0]])
                top, right, bottom, left = points
                self.assertLess(top[1], bottom[1])
                self.assertLess(left[0], right[0])

    def test_radial_distortion_round_trip(self):
        camera = camera_for_mount('left', k1=-0.08)
        board = np.array([[0.0, -135.0], [120.0, 40.0], [-160.0, 10.0]])
        back = camera.image_to_plane(camera.project_plane(board))
        self.assertLess(float(np.max(np.linalg.norm(back - board, axis=1))), 0.05)


class BoardTexture(unittest.TestCase):
    def test_texture_colours_follow_score_point(self):
        texture = board_texture()
        T = mm_to_texture_matrix()
        # Sample away from wires: segment centres for a few sectors and rings.
        samples = {
            (0.0, -135.0): 'single-dark',   # S20 is a dark sector
            (0.0, -103.0): 'ring-dark',     # T20 red
            (0.0, -166.0): 'ring-dark',     # D20 red
            (0.0, 0.0): 'bull',
        }
        for (x, y), kind in samples.items():
            col, row, _ = T @ np.array([x, y, 1.0])
            b, g, r = texture[int(round(row)), int(round(col))]
            if kind == 'single-dark':
                self.assertLess(int(b) + int(g) + int(r), 120)
            else:
                self.assertGreater(int(r), 150)
                self.assertLess(int(g), 80)
        self.assertGreaterEqual(texture.shape[0], 2000)  # >= 4 px/mm over 500 mm


class SceneLabels(unittest.TestCase):
    def test_labels_equal_score_point_of_tip(self):
        rng = np.random.default_rng(7)
        for name in ('left', 'top', 'steep-topleft'):
            darts = [random_dart(rng) for _ in range(4)]
            result = render_scene(camera_for_mount(name), darts, seed=3)
            self.assertEqual(len(result.labels), 4)
            for dart, label in zip(darts, result.labels):
                with self.subTest(mount=name, dart=(dart.x, dart.y)):
                    expected = score_point(dart.x, dart.y)
                    self.assertEqual(label['label'], expected['label'])
                    self.assertEqual((label['value'], label['multiplier']),
                                     (expected['value'], expected['multiplier']))
                    self.assertEqual(label['near_wire'], near_wire(dart.x, dart.y))
                    self.assertEqual((label['x'], label['y']), (dart.x, dart.y))

    def test_calibration_points_are_accepted_by_vision_and_map_to_targets(self):
        camera = camera_for_mount('right')
        result = render_scene(camera, [], seed=1)
        vision = Vision()
        vision.frame = result.frame
        vision.timestamp = time.time()
        vision.calibrate(result.calibration_points.tolist())
        pixel = camera.project_plane([[0.0, -135.0]])
        warped = cv2.perspectiveTransform(pixel.reshape(1, -1, 2).astype(np.float64), vision.H)[0, 0]
        self.assertLess(float(np.linalg.norm(warped - (np.array([0, -135]) * SCALE + CENTER))), 0.5)

    def test_dart_is_drawn_and_tip_pixel_changes(self):
        camera = camera_for_mount('left')
        empty = render_scene(camera, [], seed=1).frame
        dart = Dart(x=0.0, y=-60.0, length=125, tilt=10, azimuth=0)
        with_dart = render_scene(camera, [dart], seed=1).frame
        changed = np.any(cv2.absdiff(empty, with_dart) > 30, axis=2)
        self.assertGreater(int(changed.sum()), 500)
        tip = camera.project_plane([[0.0, -60.0]])[0]
        col, row = int(round(tip[0])), int(round(tip[1]))
        self.assertTrue(changed[row - 2:row + 3, col - 2:col + 3].any())

    def test_degradations_and_shadow_change_the_frame(self):
        camera = camera_for_mount('top')
        dart = Dart(x=40.0, y=50.0)
        clean = render_scene(camera, [dart], seed=2).frame
        realistic = render_scene(camera, [dart], PROFILES['realistic'], seed=2)
        self.assertIsNotNone(realistic.encoded)
        self.assertGreater(float(cv2.absdiff(clean, realistic.frame).mean()), 1.0)
        shadow = render_scene(camera, [dart], PROFILES['ideal'].with_options(shadow=DEFAULT_LIGHT), seed=2).frame
        self.assertGreater(int((cv2.absdiff(clean, shadow).max(axis=2) > 20).sum()), 200)


class PreviewDeterminism(unittest.TestCase):
    def test_same_seed_gives_byte_identical_png(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [os.path.join(directory, name) for name in ('a.png', 'b.png', 'c.png')]
            args = ['--mount', 'left', '--darts', '3', '--profile', 'realistic', '--seed', '11']
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stdout(devnull):
                    self.assertEqual(preview_main(args + ['--out', paths[0]]), 0)
                    self.assertEqual(preview_main(args + ['--out', paths[1]]), 0)
                    self.assertEqual(preview_main(['--mount', 'left', '--darts', '3', '--profile', 'realistic',
                                                   '--seed', '12', '--out', paths[2]]), 0)
            data = []
            for path in paths:
                with open(path, 'rb') as handle:
                    data.append(handle.read())
            self.assertEqual(data[0], data[1])
            self.assertNotEqual(data[0], data[2])


if __name__ == '__main__':
    unittest.main()
