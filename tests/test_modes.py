"""M1-15: game-mode interface. x01 is the first registered mode and behaves exactly as before."""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402

import modes  # noqa: E402
from core import Game  # noqa: E402
from modes.base import GameMode  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / 'golden' / 'x01_states.json'
TOKEN = 'modes-token'


def play(script):
    out = []
    for step in script:
        kind = step[0]
        if kind == 'game': g = Game(step[1], step[2], step[3])
        elif kind == 'throw': g.throw(step[1], step[2])
        elif kind == 'next': g.next_turn()
        elif kind == 'undo': g.undo()
        elif kind == 'fill': g.fill_misses()
        elif kind == 'correct': g.correct(*step[1:])
        out.append((g.snapshot(), len(g.history)))
    return out


class FirstTo(GameMode):
    """Test-only mode: score points, first to `target` wins; any number of darts per turn up to 3."""
    id = 'first_to'
    display_name = 'First to N'
    min_players = 2
    max_players = 3

    def validate_options(self, options):
        target = (options or {}).get('target', 40)
        if type(target) is not int or not 1 <= target <= 1000: raise ValueError('target must be 1-1000')
        return {'target': target}

    def new_state(self, names, options):
        return {'names': names, 'player': 0, 'turn': 1, 'darts': [], 'winner': None,
                'points': [0] * len(names), 'target': options['target']}

    def throw(self, state, value, multiplier):
        dart = self.score_dart(state, value, multiplier)
        state['darts'].append(dart)
        state['points'][state['player']] += dart['score']
        if state['points'][state['player']] >= state['target']:
            state['winner'] = state['player']

    def presentation_hints(self, state):
        return {'kind': 'first_to', 'target': state['target'], 'points': list(state['points'])}


class X01Unchanged(unittest.TestCase):
    def test_snapshots_and_undo_history_match_the_pre_refactor_golden_file(self):
        golden = json.loads(GOLDEN.read_text())['runs']
        import importlib.util
        spec = importlib.util.spec_from_file_location('make_golden', GOLDEN.parent / 'make_x01_golden.py')
        make_golden = importlib.util.module_from_spec(spec); spec.loader.exec_module(make_golden)
        for run, script in zip(golden, (make_golden.SCRIPT, make_golden.SCRIPT2)):
            for expected, (snapshot, history) in zip(run, play(script)):
                with self.subTest(step=expected['step']):
                    self.assertEqual(snapshot.pop('mode'), 'x01')
                    self.assertEqual(snapshot, expected['snapshot'])
                    self.assertEqual(history, expected['history'])

    def test_registry_and_options(self):
        self.assertIn('x01', modes.MODES)
        self.assertEqual(modes.catalog()[0]['id'], 'x01')
        with self.assertRaises(ValueError):
            modes.get('cricket')
        self.assertEqual(Game(['A', 'B'], mode='x01', options={'start': 501, 'double_out': True}).data['start'], 501)
        for options in ({'start': 501.0}, {'start': 401}, {'double_out': 1}, {'legs': 3}, []):
            with self.subTest(options=options), self.assertRaises(ValueError):
                Game(['A', 'B'], mode='x01', options=options)
        g = Game(['A', 'B'], 501, True)
        self.assertEqual(g.hints(), {'kind': 'x01', 'start': 501, 'double_out': True})

    def test_save_and_restore_round_trip(self):
        g = Game(['A', 'B', 'C'], 501, True)
        for value, multiplier in ((20, 3), (19, 3), (0, 1)):
            g.throw(value, multiplier)
        g.next_turn(); g.throw(25, 2)
        restored = Game.from_json(json.loads(json.dumps(g.to_json())))
        self.assertEqual(restored.snapshot(), g.snapshot())
        restored.undo(); g.undo()
        self.assertEqual(restored.snapshot(), g.snapshot())


class NewModeNeedsNoServerChanges(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        modes.register(FirstTo())
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = None
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        modes.unregister('first_to')
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

    def test_a_registered_mode_plays_through_the_api(self):
        self.assertIn('first_to', [m['id'] for m in self.request('/api/modes')[1]['modes']])
        status, state = self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'mode': 'first_to',
                                                   'options': {'target': 50}})
        self.assertEqual(status, 200, state)
        self.assertEqual(state['game']['mode'], 'first_to')
        self.assertEqual(state['display'], {'kind': 'first_to', 'target': 50, 'points': [0, 0]})
        for value, multiplier in ((20, 1), (5, 1), (1, 1)):
            self.assertEqual(self.request('/api/throw', {'value': value, 'multiplier': multiplier})[0], 200)
        self.assertEqual(self.request('/api/throw', {'value': 1})[0], 400)  # three darts per turn
        self.assertEqual(self.request('/api/correct', {'dart_index': 1, 'value': 5, 'multiplier': 2})[0], 200)
        self.assertEqual(self.request('/api/next', {})[0], 200)
        self.assertEqual(self.request('/api/turn/fill_misses', {})[1]['game']['darts'][2]['filled'], True)
        self.assertEqual(self.request('/api/next', {})[0], 200)
        status, state = self.request('/api/throw', {'value': 20})
        self.assertEqual(state['game']['winner'], 0)  # 31 + 20 >= 50
        self.assertEqual(state['display']['points'], [51, 0])
        self.assertEqual(self.request('/api/undo', {})[1]['game']['winner'], None)
        self.assertEqual(self.request('/api/game', {'names': ['A', 'B'], 'camera': False, 'mode': 'nope'})[0], 400)


if __name__ == '__main__':
    unittest.main()
