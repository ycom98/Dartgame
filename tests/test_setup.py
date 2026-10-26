"""Regression checks for frozen calibration and readiness gates."""
import time
import unittest
import cv2
import numpy as np
from vision import Vision, TARGETS

POINTS = [[400,150],[650,400],[400,650],[150,400]]

class CalibrationSetupRegression(unittest.TestCase):
    def fresh_vision(self):
        rng=np.random.default_rng(149)
        frame=np.full((800,800,3),80,np.uint8)
        for _ in range(1600):
            x,y=rng.integers(155,646,2)
            if (x-400)**2+(y-400)**2<240**2:
                cv2.circle(frame,(int(x),int(y)),int(rng.integers(2,6)),tuple(int(v) for v in rng.integers(0,256,3)),-1)
        v=Vision();v.frame=frame;v.timestamp=time.time();return v
    def test_snapshot_points_follow_the_frozen_reference(self):
        v=self.fresh_vision();original=v.frame.copy();snap=v.begin_calibration()
        translation=np.float32([[1,0,13],[0,1,-11]])
        v.frame=cv2.warpAffine(original,translation,(800,800));v.timestamp=time.time()
        v.calibrate(POINTS,snap['snapshot_id'])
        self.assertTrue(np.array_equal(v.reference,original))
        self.assertFalse(np.array_equal(v.frame,original))
        expected=np.float32(POINTS)+[13,-11]
        self.assertLess(float(np.max(np.linalg.norm(v.overlay()-expected,axis=1))),3)
        self.assertEqual(v.state()['phase'],'review_overlay')
        v.verify(v.version);self.assertEqual(v.state()['phase'],'ready')
    def test_replaced_and_expired_snapshots_are_rejected(self):
        v=self.fresh_vision();first=v.begin_calibration();second=v.begin_calibration()
        with self.assertRaises(ValueError):v.calibrate(POINTS,first['snapshot_id'])
        v.calibration_started-=301
        with self.assertRaises(ValueError):v.calibrate(POINTS,second['snapshot_id'])
        self.assertIsNone(v.calibration_id);self.assertFalse(v.aligned)
    def test_frozen_image_does_not_substitute_for_live_camera(self):
        v=self.fresh_vision();snap=v.begin_calibration();v.timestamp-=6
        with self.assertRaises(ValueError):v.calibrate(POINTS,snap['snapshot_id'])
        self.assertFalse(v.aligned)
    def test_verification_is_bound_to_alignment_version(self):
        v=self.fresh_vision();v.calibrate(POINTS);old=v.version;v.verify(old)
        v.align();self.assertFalse(v.verified())
        with self.assertRaises(ValueError):v.verify(old)
        v.verify(v.version);self.assertTrue(v.verified())
    def test_stale_reconnect_requires_alignment_and_verification(self):
        v=self.fresh_vision();v.calibrate(POINTS);v.verify(v.version)
        ok,jpeg=cv2.imencode('.jpg',v.frame);self.assertTrue(ok)
        v.timestamp-=6;self.assertEqual(v.state()['phase'],'camera_disconnected')
        v.ingest(jpeg.tobytes());self.assertFalse(v.aligned);self.assertFalse(v.verified())
        self.assertEqual(v.state()['phase'],'needs_alignment')
    def test_startup_recheck_preserves_only_unchanged_verified_overlay(self):
        v=self.fresh_vision();v.calibrate(POINTS);v.verify(v.version)
        v.align(preserve_verification=True);self.assertTrue(v.verified())
        v.frame=cv2.warpAffine(v.frame,np.float32([[1,0,13],[0,1,-11]]),(800,800));v.timestamp=time.time()
        v.align(preserve_verification=True);self.assertFalse(v.verified())
    def test_setup_phases_and_cancel(self):
        v=Vision();self.assertEqual(v.state()['phase'],'waiting_camera')
        v=self.fresh_vision();self.assertEqual(v.state()['phase'],'ready_to_calibrate')
        v.begin_calibration();self.assertEqual(v.state()['phase'],'calibrating')
        v.cancel_calibration();self.assertEqual(v.state()['phase'],'ready_to_calibrate')

class SetupApiRegression(unittest.TestCase):
    def setUp(self):
        import server,threading
        from http.server import ThreadingHTTPServer
        from core import Game
        self.module=server;self.previous=(server.app,server.vision)
        server.app=server.App('setup-test-token');server.vision=CalibrationSetupRegression().fresh_vision()
        server.vision.calibrate(POINTS);server.vision.verify(server.vision.version)
        server.app.game=Game(['A','B']);server.app.camera_game=True
        self.server=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.module.app,self.module.vision=self.previous
    def post(self,path,body):
        import http.client,json
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=3)
        c.request('POST',path,json.dumps(body),{'Authorization':'Bearer setup-test-token'})
        r=c.getresponse();data=json.loads(r.read());status=r.status;c.close();return status,data
    def test_camera_proposal_requires_current_verified_alignment(self):
        v=self.module.vision;v.align();v.proposal={'value':20,'multiplier':3}
        self.assertEqual(self.post('/api/throw',{'proposal':True})[0],400)
        self.assertEqual(self.module.app.game.snapshot()['scores'][0],301)
        v.verify(v.version)
        self.assertEqual(self.post('/api/throw',{'proposal':True})[0],200)
        self.assertEqual(self.module.app.game.snapshot()['scores'][0],241)
    def test_camera_restart_invalidates_snapshot_and_verification_immediately(self):
        v=self.module.vision;snapshot=v.begin_calibration()
        status,body=self.post('/api/camera/reset',{})
        self.assertEqual(status,200);self.assertFalse(body['vision']['fresh'])
        self.assertFalse(v.verified());self.assertFalse(v.aligned)
        with self.assertRaises(ValueError):v.snapshot_frame(snapshot['snapshot_id'])

if __name__=='__main__':unittest.main()
