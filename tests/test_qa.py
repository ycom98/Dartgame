"""Independent acceptance checks; synthetic vision is not hardware validation."""
import math
import time
import unittest

from core import Game, SECTORS, score_point, near_wire
from vision import Vision, TARGETS
import cv2
import numpy as np


class RulesQA(unittest.TestCase):
    def test_all_sector_centers_and_rings(self):
        for i, sector in enumerate(SECTORS):
            a=math.radians(i*18)
            for radius,multiplier in [(55,1),(103,3),(130,1),(166,2)]:
                with self.subTest(sector=sector,radius=radius):
                    p=score_point(radius*math.sin(a),-radius*math.cos(a))
                    self.assertEqual((p['value'],p['multiplier']),(sector,multiplier))
        self.assertEqual(score_point(0,0)['score'],50)
        self.assertEqual(score_point(0,10)['score'],25)
        self.assertEqual(score_point(0,180)['score'],0)
        self.assertTrue(near_wire(0,-103.0+4))
        self.assertFalse(near_wire(0,-130))

    def test_validation_does_not_change_game(self):
        game=Game(['A','B'])
        old=game.snapshot()
        for v,m in [(21,1),(25,3),(0,2),(20.0,1),(True,1),(20,False),(-1,1)]:
            with self.subTest(v=v,m=m):
                with self.assertRaises(ValueError): game.throw(v,m)
                self.assertEqual(old,game.snapshot())
        for names in [[],['A'],['A']*5,['A','a'],['A',' ']]:
            with self.assertRaises(ValueError): Game(names)

    def test_bust_rolls_back_whole_turn_and_undo(self):
        game=Game(['A','B'])
        for _ in range(3): game.throw(20,3)
        game.next_turn()
        for _ in range(3):game.throw(0)
        game.next_turn()
        self.assertEqual(game.snapshot()['scores'][0],121)
        game.throw(20,3); game.throw(20,3)
        before=game.snapshot()
        bust=game.throw(2)
        self.assertEqual(bust['scores'][0],121)
        self.assertTrue(bust['bust'])
        with self.assertRaises(ValueError):game.throw(0)
        self.assertEqual(game.undo(),before)
        self.assertEqual(game.throw(1)['winner'],0)
        with self.assertRaises(ValueError): game.next_turn()

    def test_double_out_one_is_bust(self):
        game=Game(['A','B'],301,True)
        for _ in range(3):game.throw(20,3)
        game.next_turn()
        for _ in range(3):game.throw(0)
        game.next_turn()
        game.throw(20,3)
        bust=game.throw(20,3)
        self.assertTrue(bust['bust'])
        self.assertEqual(bust['scores'][0],121)

    def test_four_players_and_next_undo(self):
        game=Game(['A','B','C','D'],501)
        with self.assertRaises(ValueError):game.next_turn()
        for _ in range(3):game.throw(0)
        before=game.snapshot()
        nextstate=game.next_turn()
        self.assertEqual(nextstate['player'],1)
        self.assertEqual(game.undo(),before)


class VisionQA(unittest.TestCase):
    @staticmethod
    def textured_board():
        # Deterministic, richly textured fake face for feature-matching checks.
        rng=np.random.default_rng(149)
        frame=np.full((800,800,3),80,np.uint8)
        for _ in range(1600):
            x,y=rng.integers(155,646,2)
            if (x-400)**2+(y-400)**2<240**2:
                color=tuple(int(v) for v in rng.integers(0,256,3))
                cv2.circle(frame,(int(x),int(y)),int(rng.integers(2,6)),color,-1)
        return frame

    def fresh_vision(self):
        vision=Vision()
        vision.frame=self.textured_board()
        vision.timestamp=time.time()
        vision.calibrate([[400,150],[650,400],[400,650],[150,400]])
        return vision

    def test_calibration_rejects_invalid_and_stale(self):
        vision=self.fresh_vision()
        for points in [[],[[0,0]]*4,[[400,150],[400,650],[650,400],[150,400]],[[float('nan'),0]]*4]:
            with self.assertRaises(ValueError):vision.calibrate(points)
        vision.timestamp=time.time()-6
        with self.assertRaises(ValueError): vision.align()
        self.assertFalse(vision.state()['aligned'])
        self.assertIsNone(vision.state()['proposal'])

    def test_pre_game_translation_and_rotation(self):
        for degrees in [0,7,-8]:
            with self.subTest(degrees=degrees):
                vision=self.fresh_vision()
                old=vision.frame.copy()
                transform=cv2.getRotationMatrix2D((400,400),degrees,1)
                transform[:,2]+=[13,-11]
                vision.frame=cv2.warpAffine(old,transform,(800,800))
                vision.timestamp=time.time()
                result=vision.align()
                self.assertTrue(result['ok'])
                corners=cv2.perspectiveTransform(TARGETS.reshape(1,-1,2),np.linalg.inv(vision.H))[0]
                initial=np.float32([[400,150],[650,400],[400,650],[150,400]])
                expected=cv2.transform(initial.reshape(1,-1,2),transform)[0]
                self.assertLess(float(np.max(np.linalg.norm(corners-expected,axis=1))),3)

    def test_no_detail_blocks_alignment(self):
        vision=self.fresh_vision()
        vision.frame=np.full((800,800,3),127,np.uint8)
        vision.timestamp=time.time()
        with self.assertRaises(ValueError):vision.align()
        self.assertFalse(vision.aligned)
        self.assertIsNone(vision.proposal)

    def test_large_scene_change_invalidates_geometry(self):
        vision=self.fresh_vision()
        changed=np.zeros((800,800,3),np.uint8)
        ok,jpeg=cv2.imencode('.jpg',changed)
        self.assertTrue(ok)
        for _ in range(6):vision.ingest(jpeg.tobytes())
        self.assertFalse(vision.aligned)
        self.assertIsNone(vision.proposal)
        self.assertIn('alignment',vision.message)

    def test_dimension_change_requires_recalibration(self):
        vision=self.fresh_vision()
        ok,jpeg=cv2.imencode('.jpg',np.zeros((600,800,3),np.uint8))
        self.assertTrue(ok)
        vision.ingest(jpeg.tobytes())
        self.assertFalse(vision.aligned)
        self.assertIsNone(vision.proposal)

    def test_stationary_board_never_generates_candidate(self):
        vision=self.fresh_vision()
        ok,jpeg=cv2.imencode('.jpg',vision.frame)
        self.assertTrue(ok)
        # JPEG compression settles; reset baseline from exact uploaded image.
        vision.ingest(jpeg.tobytes());vision.reset_base()
        for _ in range(10):vision.ingest(jpeg.tobytes())
        self.assertIsNone(vision.proposal)

class TipRuleQA(unittest.TestCase):
    """M1-05 foot-point tip rule (synthetic scenes; not real-board evidence)."""

    @staticmethod
    def detect(mount, dart, rule):
        from sim import camera_for_mount
        from sim.scene import calibration_points, render_clean
        camera = camera_for_mount(mount)
        vision = Vision()
        vision.rule = rule
        empty = cv2.imencode('.bmp', render_clean(camera, []))[1].tobytes()
        vision.ingest(empty)
        vision.calibrate(calibration_points(camera).tolist())
        for _ in range(3): vision.ingest(empty)
        vision.reset_base()
        scene = cv2.imencode('.bmp', render_clean(camera, [dart]))[1].tobytes()
        for _ in range(4): vision.ingest(scene)
        return vision.proposal

    def test_foot_rule_scores_darts_the_centre_rule_gets_wrong(self):
        from sim.scene import Dart
        cases = [
            ('top', Dart(x=-50.427, y=-142.954, length=112.85, tilt=20.40, azimuth=-42.58, spin=15.42,
                         barrel_colour=(70, 70, 76), shaft_colour=(40, 40, 170), flight_colour=(30, 30, 200))),
            ('left', Dart(x=-48.508, y=129.524, length=122.19, tilt=25.35, azimuth=21.90, spin=15.03,
                          barrel_colour=(70, 70, 76), shaft_colour=(220, 220, 220), flight_colour=(30, 30, 200))),
        ]
        for mount, dart in cases:
            with self.subTest(mount=mount):
                truth = score_point(dart.x, dart.y)['label']
                foot = self.detect(mount, dart, 'foot')
                self.assertEqual((foot['label'], foot['rule'], foot['confidence']), (truth, 'foot', 'high'))
                self.assertLess(math.hypot(foot['x'] - dart.x, foot['y'] - dart.y), 2.0)
                centre = self.detect(mount, dart, 'centre')
                self.assertEqual(centre['rule'], 'centre')
                self.assertNotEqual(centre['label'], truth)

    def round_blob_vision(self, rule):
        vision = VisionQA().fresh_vision()
        vision.rule = rule
        ok, empty = cv2.imencode('.png', vision.frame)
        vision.ingest(empty.tobytes()); vision.reset_base()
        blob = vision.frame.copy()
        cv2.circle(blob, (470, 330), 11, (255, 255, 255), -1)
        ok, data = cv2.imencode('.png', blob)
        for _ in range(4): vision.ingest(data.tobytes())
        return vision

    def test_round_blob_gets_low_confidence_nearest_point_with_foot_rule(self):
        vision = self.round_blob_vision('foot')
        proposal = vision.proposal
        self.assertIsNotNone(proposal)
        self.assertEqual((proposal['confidence'], proposal['rule']), ('low', 'foot'))
        foot = np.asarray(vision.foot_point())
        tip = np.array([proposal['x'], proposal['y']])
        # The chosen pixel is on the blob boundary facing the foot point.
        centre_mm = (np.array(cv2.perspectiveTransform(np.float32([[[470, 330]]]), vision.H)[0, 0]) - 350) / 1.7
        self.assertLess(np.linalg.norm(tip - foot), np.linalg.norm(centre_mm - foot))

    def test_round_blob_is_still_rejected_by_centre_rule(self):
        vision = self.round_blob_vision('centre')
        self.assertIsNone(vision.proposal)
        self.assertIn('not dart-shaped', vision.message)

    def test_default_rule_and_bias_are_configurable(self):
        import vision as vision_module
        self.assertEqual(vision_module.DEFAULT_RULE, 'foot')
        self.assertEqual(Vision().rule, 'foot')
        self.assertIn('centre', vision_module.TIP_RULES)
        self.assertEqual(Vision().tip_bias_mm, vision_module.TIP_BIAS_MM)


class ApiQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        import server
        from http.server import ThreadingHTTPServer
        cls.module=server
        server.app=server.App('qa-secret')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.port=cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,payload=None,token='qa-secret',raw=None):
        import http.client,json
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        headers={'Authorization':'Bearer '+token}
        method='GET' if payload is None and raw is None else 'POST'
        body=raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        conn.request(method,path,body,headers)
        r=conn.getresponse();data=r.read();status=r.status;conn.close()
        return status,json.loads(data)

    def test_confirmed_proposal_commits_once(self):
        module=self.module
        self.request('/api/game',{'names':['A','B'],'camera':False})
        frame=VisionQA.textured_board()
        module.vision.frame=frame
        module.vision.timestamp=time.time()
        module.vision.calibrate([[400,150],[650,400],[400,650],[150,400]])
        module.vision.proposal={'value':20,'multiplier':3}
        status,body=self.request('/api/throw',{'proposal':True})
        self.assertEqual(status,200)
        self.assertEqual(body['game']['scores'][0],241)
        self.assertIsNone(body['vision']['proposal'])
        self.assertEqual(self.request('/api/throw',{'proposal':True})[0],400)

    def test_api_authorization_validation_and_lifecycle(self):
        status,body=self.request('/api/state',token='wrong')
        self.assertEqual(status,401)
        status,body=self.request('/api/game',{'names':['A','B'],'camera':False,'start':301})
        self.assertEqual(status,200)
        old=body['game']
        for payload in [{'value':21},{'value':20,'multiplier':4},{'value':True},{'value':25,'multiplier':3}]:
            status,body=self.request('/api/throw',payload)
            self.assertEqual(status,400)
            self.assertEqual(self.request('/api/state')[1]['game'],old)
        for raw in [b'{',b'[]',b'null']:
            self.assertEqual(self.request('/api/throw',raw=raw)[0],400)
        self.assertEqual(self.request('/api/next',{})[0],400)
        for _ in range(3): self.assertEqual(self.request('/api/throw',{'value':20,'multiplier':3})[0],200)
        self.assertEqual(self.request('/api/throw',{'value':0})[0],400)
        self.assertEqual(self.request('/api/next',{})[1]['game']['player'],1)
        self.assertEqual(self.request('/api/undo',{})[1]['game']['player'],0)
        self.assertEqual(self.request('/api/not-real',{})[0],404)
        self.assertEqual(self.request('/api/frame',raw=b'not-an-image')[0],400)
        self.module.vision.timestamp=0
        self.assertEqual(self.request('/api/game',{'names':['A','B'],'camera':True})[0],400)
        self.assertEqual(self.request('/api/throw',{'proposal':True})[0],400)


if __name__=='__main__':unittest.main()
