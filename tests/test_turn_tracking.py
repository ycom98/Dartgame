"""M4-01: multi-dart turns on the camera (PLAN M1-08). Synthetic scenes (sim/), ceiling-1.5ft mount.

Darts 2 and 3 are detected while earlier darts are still pending; a dart that falls out is retracted; pulling
the darts restarts the turn reference; the controller flow commits pending darts in throw order.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402

from camera_flow import CameraFlow  # noqa: E402
from core import score_point  # noqa: E402
from vision import Vision  # noqa: E402

# Three darts away from wires, in throw order.
SPOTS = [(30.0, -100.0), (-75.0, 40.0), (60.0, 75.0)]


class TurnTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim import camera_for_mount
        from sim.scene import Dart, calibration_points
        cls.camera = camera_for_mount('ceiling-1.5ft')
        cls.points = calibration_points(cls.camera).tolist()
        cls.darts = [Dart(x=x, y=y, tilt=12.0) for x, y in SPOTS]
        cls.labels = [score_point(x, y)['label'] for x, y in SPOTS]

    def frame(self, darts):
        from sim.scene import render_clean
        return cv2.imencode('.bmp', render_clean(self.camera, darts))[1].tobytes()

    def show(self, vision, darts, frames=4):
        data = self.frame(darts)
        for _ in range(frames):
            vision.ingest(data)

    def calibrated(self):
        vision = Vision()
        empty = self.frame([])
        vision.ingest(empty)
        vision.calibrate(self.points)
        self.show(vision, [], 3)
        vision.reset_base()
        return vision

    def test_three_darts_without_commits_are_three_pending_darts_in_order(self):
        vision = self.calibrated()
        for k in range(1, 4):
            self.show(vision, self.darts[:k])
            self.assertEqual([p['label'] for p in vision.pending], self.labels[:k], vision.message)
        self.assertEqual(vision.proposal['label'], self.labels[0])  # the oldest is the one a commit applies to
        self.assertEqual(len({p['id'] for p in vision.pending}), 3)

    def test_committed_darts_stay_in_the_reference(self):
        vision = self.calibrated()
        self.show(vision, self.darts[:1])
        vision.commit_dart(vision.proposal['id'])
        self.assertEqual(vision.pending, [])
        self.show(vision, self.darts[:1])  # still there: not proposed again
        self.assertEqual(vision.pending, [])
        self.show(vision, self.darts[:2])
        self.assertEqual([p['label'] for p in vision.pending], self.labels[1:2])

    def test_bounce_out_retracts_the_pending_dart(self):
        vision = self.calibrated()
        self.show(vision, self.darts[:1])
        vision.commit_dart(vision.proposal['id'])
        self.show(vision, self.darts[:2])
        self.assertEqual(len(vision.pending), 1)
        self.show(vision, self.darts[:1])  # dart 2 fell out
        self.assertEqual(vision.pending, [])
        self.assertEqual(vision.counters['retracted'], 1)
        self.assertIn('fell out', vision.message)
        self.show(vision, self.darts[:1])  # and nothing comes back
        self.assertEqual(vision.pending, [])

    def test_pulling_every_dart_clears_the_board_and_a_partial_pull_is_no_proposal(self):
        vision = self.calibrated()
        for k in range(1, 4):
            self.show(vision, self.darts[:k])
            vision.commit_dart(vision.proposal['id'])
        self.show(vision, [self.darts[0], self.darts[2]])  # dart 2 pulled on its own
        self.assertEqual(vision.pending, [])
        self.assertEqual(vision.counters['pulled'], 1)
        self.show(vision, [])
        self.assertEqual(vision.counters['board_cleared'], 1)
        self.assertEqual(vision.tracked, [])
        self.show(vision, self.darts[:1])  # the next turn's first dart
        self.assertEqual([p['label'] for p in vision.pending], self.labels[:1])

    def test_end_turn_drops_pending_darts_without_proposing_them_again(self):
        vision = self.calibrated()
        self.show(vision, self.darts[:2])
        vision.end_turn()
        self.show(vision, self.darts[:2])
        self.assertEqual(vision.pending, [])


class PendingOrder(unittest.TestCase):
    """CameraFlow with several pending darts: the head commits first; each later dart gets a full countdown."""

    class FakeVision:
        aligned = True
        def __init__(self): self.turn_base = object(); self.base = self.turn_base; self.pending = []
        def fresh(self): return True

    @staticmethod
    def dart(dart_id, label):
        return {'id': dart_id, 'value': int(label[1:]), 'multiplier': 1, 'label': label, 'score': int(label[1:]),
                'x': 0.0, 'y': -60.0, 'confidence': 'high', 'check': []}

    def test_head_first_and_countdown_restarts_on_promotion(self):
        flow, vision = CameraFlow(delay=0.3), self.FakeVision()
        vision.pending = [self.dart('a-1', 'S20'), self.dart('a-2', 'S1')]
        self.assertEqual(flow.observe(vision)['id'], 'a-1')
        view = flow.view()
        self.assertEqual([d['id'] for d in view['pending_darts']], ['a-1', 'a-2'])
        self.assertIsNone(view['pending_darts'][1]['commit_in'])
        self.assertTrue(view['pending_darts'][1]['queued'])
        time.sleep(0.35)
        self.assertEqual(flow.due()['id'], 'a-1')
        flow.close('a-1')
        vision.pending = vision.pending[1:]
        self.assertEqual(flow.observe(vision)['id'], 'a-2')
        self.assertIsNone(flow.due())  # promoted just now: a fresh countdown, not committed at once
        time.sleep(0.35)
        self.assertEqual(flow.due()['id'], 'a-2')


if __name__ == '__main__':
    unittest.main()
