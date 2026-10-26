"""M1-03: smoke test for the end-to-end detection harness (synthetic only)."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest

from sim.camera import MOUNTS
from tools import eval_detection

METRICS = ('exact_accuracy', 'wrong_sector_rate', 'wrong_ring_rate', 'no_proposal_rate', 'tip_error_mm',
           'near_wire', 'not_near_wire', 'time_per_frame_ms')


class HarnessSmoke(unittest.TestCase):
    def test_ten_darts_every_mount_report_is_complete_and_fast(self):
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, 'report.json')
            with contextlib.redirect_stdout(io.StringIO()):
                code = eval_detection.main(['--darts', '10', '--seed', '3', '--profile', 'ideal', '--out', out])
            self.assertEqual(code, 0)
            with open(out) as handle:
                report = json.load(handle)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 30)
        self.assertIn('not evidence of real-board accuracy', report['disclaimer'])
        self.assertEqual(set(report['mounts']), set(MOUNTS))
        for name, result in report['mounts'].items():
            with self.subTest(mount=name):
                for key in METRICS:
                    self.assertIn(key, result)
                self.assertEqual(len(result['trials']), 10)
                rates = (result['exact_accuracy'] + result['wrong_sector_rate'] + result['wrong_ring_rate']
                         + result['no_proposal_rate'])
                self.assertAlmostEqual(rates, 1.0, places=3)
                self.assertGreater(result['time_per_frame_ms']['frames'], 0)

    def test_same_seed_gives_same_outcomes(self):
        first = eval_detection.run(['top'], 5, 9, 'realistic')
        second = eval_detection.run(['top'], 5, 9, 'realistic')
        self.assertEqual(first['mounts']['top']['trials'], second['mounts']['top']['trials'])

    def test_recording_is_stubbed(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(eval_detection.main(['--recording', 'nowhere']), 2)
        self.assertIn('not implemented', stderr.getvalue())

    def test_classification(self):
        truth = {'label': 'T20', 'value': 20}
        self.assertEqual(eval_detection.classify(truth, None), 'no_proposal')
        self.assertEqual(eval_detection.classify(truth, {'label': 'T20', 'value': 20}), 'exact')
        self.assertEqual(eval_detection.classify(truth, {'label': 'S20', 'value': 20}), 'wrong_ring')
        self.assertEqual(eval_detection.classify(truth, {'label': 'T1', 'value': 1}), 'wrong_sector')


if __name__ == '__main__':
    unittest.main()
