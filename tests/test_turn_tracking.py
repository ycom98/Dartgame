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


class RecoveryWithDartsInTheBoard(unittest.TestCase):
    """QA M4 H1: after a realign, a stream drop or a restart mid-turn, and for a dart scored by hand, pulling
    darts the camera is not tracking must never propose them, and the cleared board must still be seen."""
    setUpClass = classmethod(TurnTracking.setUpClass.__func__)
    frame, show, calibrated = TurnTracking.frame, TurnTracking.show, TurnTracking.calibrated

    def two_committed(self):
        vision = self.calibrated()
        for k in (1, 2):
            self.show(vision, self.darts[:k])
            vision.commit_dart(vision.proposal['id'])
        return vision

    def pull_and_clear(self, vision):
        """Pull dart 1, then dart 2: nothing is proposed, and the board counts as cleared."""
        cleared = vision.counters['board_cleared']
        self.show(vision, self.darts[1:2])
        self.assertEqual(vision.pending, [], vision.message)
        self.show(vision, [])
        self.assertEqual(vision.pending, [], vision.message)
        self.assertEqual(vision.counters['board_cleared'], cleared + 1)
        self.show(vision, self.darts[2:3])  # the next player's first dart is proposed as usual
        self.assertEqual([p['label'] for p in vision.pending], self.labels[2:3])

    def test_check_realign_mid_turn(self):
        vision = self.two_committed()
        vision.align()
        self.pull_and_clear(vision)

    def test_stream_drop_mid_turn_keeps_the_pending_dart(self):
        vision = self.calibrated()
        self.show(vision, self.darts[:1])
        vision.commit_dart(vision.proposal['id'])
        self.show(vision, self.darts[:2])
        pending = vision.proposal['id']
        vision.timestamp = time.time() - 6  # the stream was lost for 6 s
        self.show(vision, self.darts[:2], 1)
        self.assertFalse(vision.aligned)
        vision.align(preserve_verification=True)  # what the server's board re-check does
        self.assertEqual(vision.proposal['id'], pending)
        vision.commit_dart(pending)
        self.pull_and_clear(vision)

    def test_restart_mid_turn(self):
        import tempfile
        import persistence
        before = self.two_committed()
        with tempfile.TemporaryDirectory() as folder:
            persistence.save_calibration(before, folder)
            vision = Vision()
            vision.ingest(self.frame(self.darts[:2]))
            persistence.load_calibration(vision, folder)
        vision.align()  # the restart re-check: the darts already in the board become the reference
        self.show(vision, self.darts[:2])
        self.assertEqual(vision.pending, [])
        self.pull_and_clear(vision)

    def test_a_hand_scored_dart_pulled_on_its_own(self):
        vision = self.calibrated()
        self.show(vision, self.darts[:1])
        vision.commit_dart(vision.proposal['id'])
        self.show(vision, self.darts[:2], 1)  # the camera has not settled when the host taps dart 2 by hand
        vision.absorb()
        self.show(vision, self.darts[:2])
        self.assertEqual(vision.pending, [])
        self.show(vision, self.darts[:1])  # dart 2 pulled on its own
        self.assertEqual(vision.pending, [], vision.message)
        self.show(vision, self.darts[:1])
        self.assertEqual(vision.pending, [])


class OcclusionConfidence(unittest.TestCase):
    """M4-02: a dart whose visible part ends at an earlier dart (camera side) is flagged and not auto-committed."""
    setUpClass = classmethod(TurnTracking.setUpClass.__func__)
    frame, show, calibrated = TurnTracking.frame, TurnTracking.show, TurnTracking.calibrated

    def test_dart_below_an_earlier_dart_is_flagged_and_one_beside_it_is_not(self):
        from sim.scene import Dart
        from tools.eval_occlusion import visibility
        upper = Dart(10.0, -60.0, length=125.0, tilt=10.0, azimuth=0.0)
        below = Dart(10.0, -25.0, length=125.0, tilt=10.0, azimuth=0.0)  # its tip is behind the upper dart
        self.assertTrue(visibility(self.camera, [upper, below], 1)['hidden_by_earlier'])
        for second, flagged in ((below, True), (self.darts[1], False)):
            with self.subTest(flagged=flagged):
                vision = self.calibrated()
                self.show(vision, [upper])
                vision.commit_dart(vision.proposal['id'])
                self.show(vision, [upper, second])
                proposal = vision.proposal
                self.assertIsNotNone(proposal, vision.message)
                self.assertEqual('possibly hidden tip — check' in proposal['check'], flagged, proposal)
                self.assertEqual(proposal['confidence'] == 'low', flagged)

    def test_low_confidence_head_waits_for_accept(self):
        flow, vision = CameraFlow(delay=0.05), PendingOrder.FakeVision()
        dart = PendingOrder.dart('a-1', 'S20')
        vision.pending = [{**dart, 'confidence': 'low', 'check': ['possibly hidden tip — check']}]
        flow.observe(vision)
        time.sleep(0.1)
        self.assertIsNone(flow.due())
        view = flow.view()['pending']
        self.assertTrue(view['needs_check'])
        self.assertIsNone(view['commit_in'])


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

    def test_next_player_drops_pending_darts_at_once(self):
        # QA M4 M1: vision drops them later, on the worker; the flow must never commit them meanwhile.
        flow, vision = CameraFlow(delay=0.01), self.FakeVision()
        vision.pending = [self.dart('a-1', 'S20')]
        flow.observe(vision)
        time.sleep(0.02)
        self.assertTrue(flow.is_head('a-1'))
        flow.drop_pending()
        self.assertFalse(flow.is_head('a-1'))
        self.assertIsNone(flow.due())
        self.assertIsNone(flow.observe(vision))  # still in vision.pending: not shown again


if __name__ == '__main__':
    unittest.main()
