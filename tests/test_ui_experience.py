"""M3 UI-02 / UI-03: checkout suggestions, match statistics, the lobby and recent player names."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_helper import with_revision  # noqa: E402  (M1-10: writes carry expected_revision)

import persistence  # noqa: E402
import server  # noqa: E402
from core import Game  # noqa: E402
from modes import checkout  # noqa: E402

# Scores with no three-dart double-out finish.
NO_DOUBLE_OUT_FINISH = {159, 162, 163, 165, 166, 168, 169}
SEGMENT_POINTS = {label: points for label, _, _, points in checkout.SEGMENTS}


def is_double(label):
    return label == 'BULL' or label.startswith('D')


class CheckoutTable(unittest.TestCase):
    def assert_route(self, score, darts_left, double_out, route):
        self.assertIsNotNone(route, f'{score} with {darts_left} darts')
        self.assertLessEqual(len(route), darts_left, f'{score}: {route}')
        self.assertTrue(all(label in SEGMENT_POINTS for label in route), route)
        self.assertEqual(sum(SEGMENT_POINTS[label] for label in route), score, f'{score}: {route}')
        if double_out:
            self.assertTrue(is_double(route[-1]), f'{score} must finish on a double: {route}')

    def test_every_double_out_score_2_to_170_with_three_darts(self):
        for score in range(2, 171):
            route = checkout.suggest(score, 3, True)
            if score in NO_DOUBLE_OUT_FINISH:
                self.assertIsNone(route, score)
            else:
                self.assert_route(score, 3, True, route)

    def test_every_double_out_score_with_two_and_one_dart(self):
        for score in range(2, 171):
            two, one = checkout.suggest(score, 2, True), checkout.suggest(score, 1, True)
            two_possible = any(SEGMENT_POINTS[a] + SEGMENT_POINTS[b] == score and is_double(b)
                               for a in SEGMENT_POINTS for b in SEGMENT_POINTS) or (score <= 40 and score % 2 == 0) \
                or score == 50
            one_possible = score == 50 or (score <= 40 and score % 2 == 0)
            self.assertEqual(two is not None, two_possible, f'{score} two darts: {two}')
            self.assertEqual(one is not None, one_possible, f'{score} one dart: {one}')
            if two is not None:
                self.assert_route(score, 2, True, two)
            if one is not None:
                self.assert_route(score, 1, True, one)

    def test_one_and_over_170_have_no_double_out_finish(self):
        for score in (0, 1, 171, 180, 301):
            self.assertIsNone(checkout.suggest(score, 3, True), score)

    def test_every_straight_out_score(self):
        for score in range(1, 181):
            route = checkout.suggest(score, 3, False)
            possible = any(SEGMENT_POINTS[a] + SEGMENT_POINTS[b] + SEGMENT_POINTS[c] == score
                           for a in SEGMENT_POINTS for b in SEGMENT_POINTS for c in SEGMENT_POINTS) or score <= 60
            self.assertEqual(route is not None, possible, f'{score}: {route}')
            if route is not None:
                self.assert_route(score, 3, False, route)
        for score in range(1, 121):
            for darts in (1, 2):
                route = checkout.suggest(score, darts, False)
                if route is not None:
                    self.assert_route(score, darts, False, route)
        self.assertEqual(checkout.suggest(20, 1, False), ['S20'])  # a fat single, not D10
        self.assertEqual(checkout.suggest(180, 3, False), ['T20', 'T20', 'T20'])

    def test_fewest_darts_first(self):
        self.assertEqual(checkout.suggest(40, 3, True), ['D20'])
        self.assertEqual(checkout.suggest(50, 3, True), ['BULL'])
        self.assertEqual(checkout.suggest(100, 3, True), ['T20', 'D20'])
        self.assertEqual(len(checkout.suggest(110, 3, True)), 2)

    def test_standard_chart_routes(self):
        chart = {170: ['T20', 'T20', 'BULL'], 167: ['T20', 'T19', 'BULL'], 164: ['T20', 'T18', 'BULL'],
                 161: ['T20', 'T17', 'BULL'], 160: ['T20', 'T20', 'D20'], 141: ['T20', 'T19', 'D12'],
                 121: ['T20', 'T11', 'D14'], 101: ['T17', 'BULL'], 81: ['T19', 'D12'], 60: ['S20', 'D20'],
                 36: ['D18'], 32: ['D16'], 3: ['S1', 'D1']}
        for score, route in chart.items():
            self.assertEqual(checkout.suggest(score, 3, True), route, score)


def play(game, *turns):
    """Throw each turn's darts, moving on between turns."""
    for index, darts in enumerate(turns):
        for value, multiplier in darts:
            game.throw(value, multiplier)
        if index < len(turns) - 1:
            game.next_turn()


class MatchStats(unittest.TestCase):
    def test_stats_from_the_turn_history(self):
        game = Game(['Ana', 'Ben'], 301, True)
        play(game,
             [(20, 3), (20, 3), (20, 3)],      # Ana 180 -> 121
             [(20, 1), (1, 1), (5, 1)],        # Ben 26 -> 275
             [(20, 3), (20, 3)],               # Ana: 121 - 120 leaves 1, a bust in double out
             [(19, 3), (19, 3), (8, 3)],       # Ben 138 -> 137
             [(20, 3), (11, 3), (14, 2)])      # Ana 121: T20 T11 D14 = checkout
        self.assertEqual(game.data['winner'], 0)
        stats = game.stats()['players']
        ana, ben = stats
        self.assertEqual(ana['darts'], 8)  # 3 + 2 (bust after two darts) + 3
        self.assertEqual(ana['points'], 301)
        self.assertEqual(ana['average'], round(301 / 8 * 3, 1))
        self.assertEqual(ana['highest'], 180)
        self.assertEqual(ana['maximums'], 1)
        self.assertEqual(ana['busts'], 1)
        self.assertEqual(ana['checkout'], 121)
        self.assertEqual(ana['checkout_darts'], 3)
        self.assertEqual(ben['darts'], 6)
        self.assertEqual(ben['points'], 164)
        self.assertEqual(ben['highest'], 138)
        self.assertEqual(ben['tons'], 1)
        self.assertEqual(ben['ton_forties'], 0)
        self.assertIsNone(ben['checkout'])

    def test_stats_follow_undo_corrections_and_filled_misses(self):
        game = Game(['Ana', 'Ben'], 301, False)
        play(game, [(20, 3), (20, 3), (19, 3)], [(1, 1)])
        game.fill_misses()
        game.next_turn()
        game.throw(20, 1)
        game.undo()  # removes Ana's dart of turn 3
        game.throw(20, 3)
        game.correct(0, 20, 1)  # and that one is corrected to S20
        stats = game.stats()['players']
        self.assertEqual(stats[0]['points'], 177 + 20)
        self.assertEqual(stats[0]['ton_forties'], 1)
        self.assertEqual(stats[0]['darts'], 4)
        self.assertEqual(stats[1]['darts'], 3)
        self.assertEqual(stats[1]['points'], 1)

    def test_turns_survive_save_and_restore(self):
        game = Game(['Ana', 'Ben'], 501, False)
        play(game, [(20, 3)] * 3, [(20, 1)] * 3, [(19, 3)])
        restored = Game.from_json(json.loads(json.dumps(game.to_json())))
        self.assertEqual(restored.stats(), game.stats())
        self.assertEqual(len(restored.turns()), 3)

    def test_checkout_hint_uses_darts_left_and_out_rule(self):
        game = Game(['Ana', 'Ben'], 301, True)
        play(game, [(20, 3), (20, 3), (20, 3)], [(0, 1)] * 3, [])
        self.assertEqual(game.checkout_hint(), {'player': 0, 'remaining': 121, 'darts_left': 3,
                                                'route': ['T20', 'T11', 'D14']})
        game.throw(20, 1)  # 101 with two darts: T17 Bull
        self.assertEqual(game.checkout_hint()['route'], ['T17', 'BULL'])
        game.throw(1, 1)   # 100 with one dart: no finish
        self.assertIsNone(game.checkout_hint())


class LobbyAndRecentPlayers(unittest.TestCase):
    def setUp(self):
        self.previous = server.app, server.vision, server.vision_error
        self.directory = tempfile.TemporaryDirectory()
        server.app = server.App('ui-experience')
        server.app.recent_dir = Path(self.directory.name)
        server.vision = None
        server.vision_error = 'QA: no camera'
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        server.app, server.vision, server.vision_error = self.previous
        self.directory.cleanup()

    def request(self, path, body=None, auth='ui-experience'):
        if body is not None and 'expected_revision' not in body:
            body = with_revision(self.httpd.server_port, auth, path, body)
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        connection.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body),
                           {'Authorization': 'Bearer ' + auth, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    def test_lobby_draft_is_shown_without_moving_the_revision(self):
        status, state = self.request('/api/state')
        self.assertEqual(state['lobby'], {'open': False, 'players': [], 'start': 301, 'double_out': False,
                                          'recent': []})
        revision = state['revision']
        status, state = self.request('/api/lobby', {'open': True, 'players': ['Ana', ' '], 'start': 501,
                                                    'double_out': True})
        self.assertEqual(status, 200)
        self.assertEqual(state['revision'], revision)
        self.assertEqual(state['lobby']['players'], ['Ana'])
        self.assertTrue(state['lobby']['open'])
        # A stale revision still updates the draft (last write wins), but the field is required.
        self.assertEqual(self.request('/api/lobby', {'players': ['Ana', 'Ben'], 'expected_revision': -5})[0], 200)
        self.assertEqual(self.request('/api/lobby', {'players': ['Ana']} | {'expected_revision': None})[0], 400)
        # The TV's read-only link sees the lobby but cannot change it.
        display = server.app.display_token
        self.assertEqual(self.request('/api/state', auth=display)[1]['lobby']['players'], ['Ana', 'Ben'])
        self.assertEqual(self.request('/api/lobby', {'open': False, 'expected_revision': 0}, auth=display)[0], 401)
        for bad in ({'players': 'Ana'}, {'players': ['a'] * 5}, {'players': ['x' * 31]}, {'start': 401},
                    {'double_out': 'yes'}, {'open': 1}):
            self.assertEqual(self.request('/api/lobby', bad)[0], 400, bad)

    def test_starting_a_game_closes_the_lobby_and_remembers_the_names(self):
        self.request('/api/lobby', {'open': True, 'players': ['Ana', 'Ben']})
        status, state = self.request('/api/game', {'names': ['Ana', 'Ben'], 'camera': False, 'start': 501})
        self.assertEqual(status, 200)
        self.assertFalse(state['lobby']['open'])
        self.assertEqual(state['lobby']['recent'], ['Ana', 'Ben'])
        self.request('/api/game', {'names': ['Cy', 'ana'], 'camera': False})
        recent = self.request('/api/state')[1]['lobby']['recent']
        self.assertEqual(recent, ['Cy', 'ana', 'Ben'])
        self.assertEqual(persistence.load_recent_players(self.directory.name), recent)

    def test_checkout_and_stats_in_state(self):
        self.request('/api/game', {'names': ['Ana', 'Ben'], 'camera': False, 'start': 301, 'double_out': True})
        state = self.request('/api/state')[1]
        self.assertIsNone(state['checkout'])  # 301 is out of reach
        self.assertIsNone(state['stats'])
        for value, multiplier in [(20, 3), (20, 3), (20, 3)]:
            self.request('/api/throw', {'value': value, 'multiplier': multiplier})
        self.request('/api/next', {})
        for _ in range(3):
            self.request('/api/throw', {'value': 0})
        state = self.request('/api/next', {})[1]
        self.assertEqual(state['checkout']['route'], ['T20', 'T11', 'D14'])
        for value, multiplier in [(20, 3), (11, 3), (14, 2)]:
            state = self.request('/api/throw', {'value': value, 'multiplier': multiplier})[1]
        self.assertEqual(state['game']['winner'], 0)
        self.assertEqual(state['stats']['players'][0]['checkout'], 121)
        self.assertEqual(state['stats']['players'][0]['maximums'], 1)


class RecentPlayersFile(unittest.TestCase):
    def test_damaged_file_gives_no_names(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, persistence.RECENT_PLAYERS_FILE).write_text('{not json')
            self.assertEqual(persistence.load_recent_players(directory), [])
            Path(directory, persistence.RECENT_PLAYERS_FILE).write_text('{"names": ["A", 3, "", "a", "B"]}')
            self.assertEqual(persistence.load_recent_players(directory), ['A', 'B'])

    def test_list_is_capped(self):
        names = persistence.remember_players([f'P{i}' for i in range(20)], ['New'])
        self.assertEqual(len(names), persistence.RECENT_PLAYERS_MAX)
        self.assertEqual(names[0], 'New')


if __name__ == '__main__':
    unittest.main()
