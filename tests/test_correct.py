"""M1-12: correcting a committed dart (2 taps) and filling in misses (owner decisions #5 and #6)."""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402
from core import Game  # noqa: E402

TOKEN = 'correct-token'


class CoreCorrection(unittest.TestCase):
    def game_at(self, score):
        g = Game(['A', 'B'])
        g.data['scores'][0] = g.data['turn_start'] = score
        return g

    def test_correcting_the_first_of_three_replays_the_rest(self):
        g = self.game_at(301)
        for value, multiplier in ((20, 1), (19, 3), (5, 1)):
            g.throw(value, multiplier)
        self.assertEqual(g.correct(0, 20, 3), 0)
        self.assertEqual([d['score'] for d in g.data['darts']], [60, 57, 5])
        self.assertEqual(g.data['scores'][0], 301 - 122)
        g.undo()  # one undo step restores the turn before the correction
        self.assertEqual([d['score'] for d in g.data['darts']], [20, 57, 5])

    def test_a_correction_can_turn_a_bust_into_a_win_or_a_bust_into_no_bust(self):
        g = self.game_at(50)
        for value, multiplier in ((20, 1), (20, 1), (20, 3)):
            g.throw(value, multiplier)
        self.assertTrue(g.data['bust'])
        g.correct(2, 5, 1)
        self.assertFalse(g.data['bust'])
        self.assertEqual(g.data['scores'][0], 5)
        g.correct(2, 10, 1)
        self.assertEqual(g.data['winner'], 0)

    def test_a_correction_that_busts_drops_the_later_darts(self):
        g = self.game_at(60)
        g.throw(20); g.throw(20)
        g.throw(20)
        self.assertEqual(g.correct(0, 25, 2), 1)  # 60 - 50 = 10; the replayed 20 busts, so the third dart is dropped
        self.assertTrue(g.data['bust'])
        self.assertEqual(len(g.data['darts']), 2)

    def test_invalid_corrections_change_nothing(self):
        g = self.game_at(301)
        g.throw(20)
        before = g.snapshot()
        for args in ((1, 20, 1), (-1, 20, 1), (0, 21, 1), (0, 25, 3), ('0', 20, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                g.correct(*args)
            self.assertEqual(g.snapshot(), before)

    def test_fill_misses_is_one_undo_step_and_marked(self):
        g = self.game_at(301)
        g.throw(20)
        self.assertEqual(g.fill_misses(), 2)
        self.assertEqual([d.get('filled', False) for d in g.data['darts']], [False, True, True])
        g.next_turn()
        g.undo(); g.undo()
        self.assertEqual(len(g.data['darts']), 1)


class CorrectionApi(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = None
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close()
        self.server.app, self.server.vision = self.previous

    def request(self, path, body=None):
        port = self.httpd.server_address[1]
        if body is not None:
            body = with_revision(port, TOKEN, path, body)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def test_correct_committed_dart_once_and_logged(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': False})
        for value in (20, 19, 18):
            self.request('/api/throw', {'value': value})
        revision = self.request('/api/state')[1]['revision']
        status, state = self.request('/api/correct', {'dart_index': 0, 'value': 20, 'multiplier': 3})
        self.assertEqual(status, 200, state)
        self.assertEqual([d['score'] for d in state['game']['darts']], [60, 19, 18])
        self.assertEqual(state['revision'], revision + 1)
        events = self.request('/api/events')[1]['events']
        correction = [e for e in events if e['type'] == 'correct']
        self.assertEqual(len(correction), 1)
        self.assertEqual((correction[0]['before']['score'], correction[0]['after']['score']), (20, 60))
        self.assertEqual(self.request('/api/correct', {'dart_index': 3, 'value': 1})[0], 400)

    def test_fill_misses_endpoint(self):
        self.request('/api/game', {'names': ['A', 'B'], 'camera': False})
        self.request('/api/throw', {'value': 20})
        status, state = self.request('/api/turn/fill_misses', {})
        self.assertEqual(status, 200, state)
        self.assertEqual([d.get('filled', False) for d in state['game']['darts']], [False, True, True])
        self.assertEqual(self.request('/api/next', {})[0], 200)
        self.assertIn('fill_misses', [e['type'] for e in self.request('/api/events')[1]['events']])


if __name__ == '__main__':
    unittest.main()
