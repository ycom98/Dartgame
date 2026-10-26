"""Developer regression checks for game rules and camera failure behavior."""
import math
import unittest
from core import Game, score_point, near_wire

class GameRegression(unittest.TestCase):
    def test_straight_out_exact_finish(self):
        g=Game(['A','B'])
        for value,multiplier in [(20,3)]*3: g.throw(value,multiplier)
        g.next_turn()
        for _ in range(3): g.throw(0)
        g.next_turn()
        g.throw(20,3);g.throw(20,3);g.throw(1)
        self.assertEqual(g.data['scores'][0],0)
        self.assertEqual(g.data['winner'],0)
        with self.assertRaises(ValueError):g.next_turn()
    def test_bust_restores_entire_turn_and_undo(self):
        g=Game(['A','B'])
        g.data['scores'][0]=50;g.data['turn_start']=50
        g.throw(20);g.throw(20);g.throw(20)
        self.assertTrue(g.data['bust']);self.assertEqual(g.data['scores'][0],50)
        g.undo();self.assertFalse(g.data['bust']);self.assertEqual(g.data['scores'][0],10)
    def test_double_bull_finishes(self):
        g=Game(['A','B'],double_out=True)
        g.data['scores'][0]=50;g.data['turn_start']=50
        g.throw(25,2)
        self.assertEqual(g.data['winner'],0)
    def test_invalid_dart_does_not_mutate(self):
        g=Game(['A','B']);before=g.snapshot()
        for value,mult in [(25,3),(0,2),(True,1),(20,False),(21,1),(20,4),('20',1)]:
            with self.assertRaises(ValueError):g.throw(value,mult)
            self.assertEqual(g.snapshot(),before)
    def test_distinct_clean_names(self):
        with self.assertRaises(ValueError):Game([' Alice ','alice'])
    def test_manual_ring_points(self):
        self.assertEqual(score_point(0,-103)['score'],60)
        self.assertEqual(score_point(166,0)['score'],12)
        self.assertEqual(score_point(0,166)['score'],6)
        self.assertEqual(score_point(-166,0)['score'],22)
        self.assertEqual(score_point(171,0)['score'],0)
    def test_radial_wire_flag(self):
        self.assertTrue(near_wire(103*math.sin(math.radians(9)),-103*math.cos(math.radians(9))))
        self.assertFalse(near_wire(0,-130))

if __name__=='__main__':unittest.main()
