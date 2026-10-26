"""Independent presentation concurrency and read-only route regression checks."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
import server

class PresentationQA(unittest.TestCase):
    def setUp(self):
        self.previous = server.app, server.vision, server.vision_error
        server.app = server.App('presentation-qa')
        server.vision = None
        server.vision_error = 'QA: no camera'
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join()
        server.app, server.vision, server.vision_error = self.previous
    def request(self, path, body=None, auth="presentation-qa"):
        c = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        c.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body),
                  {'Authorization':'Bearer '+auth, 'Content-Type':'application/json'})
        r=c.getresponse(); data=r.read(); status=r.status; c.close()
        return status, json.loads(data) if path.startswith('/api/') else data
    def begin(self):
        s,d=self.request('/api/game', {'names':['QA A','QA B'],'camera':False})
        self.assertEqual(s,200); return d['revision']
    def test_public_presenter_routes_and_assets_do_not_mutate(self):
        rev=self.begin(); before=server.app.game.snapshot()
        for p in ['/play','/control','/showcase','/static/presentation.css','/static/presentation.js','/static/control.js','/static/showcase.js','/','/phone']:
            status,data=self.request(p); self.assertEqual(status,200,p); self.assertTrue(data,p)
        self.assertEqual(server.app.revision,rev); self.assertEqual(server.app.game.snapshot(),before)
    def test_spectator_token_reads_state_but_cannot_access_media_or_mutate(self):
        self.begin(); before=self.request('/api/state')[1]
        token=server.app.display_token
        self.assertNotEqual(token,server.app.token)
        status,state=self.request('/api/state',auth=token)
        self.assertEqual(status,200)
        self.assertEqual(state['presentation_path'],'/play?t='+token)
        self.assertNotIn(server.app.token,json.dumps(state))
        for path in ['/api/image','/api/calibration/image']:
            self.assertEqual(self.request(path,auth=token)[0],401)
        for action in ['throw','next','undo','game','frame','camera/reset','baseline','align']:
            self.assertEqual(self.request('/api/'+action,{'value':20,'names':['C','D'],'camera':False},auth=token)[0],401)
        self.assertEqual(self.request('/api/state')[1],before)
    def test_two_controller_same_revision_accepts_exactly_one_throw(self):
        rev=self.begin(); barrier=threading.Barrier(3); results=[]
        def score():
            barrier.wait(); results.append(self.request('/api/throw', {'value':20,'multiplier':3,'expected_revision':rev}))
        ts=[threading.Thread(target=score) for _ in range(2)]
        for t in ts:t.start()
        barrier.wait()
        for t in ts:t.join()
        self.assertEqual(sorted(s for s,d in results),[200,409])
        state=self.request('/api/state')[1]
        self.assertEqual(state['game']['scores'],[241,301]); self.assertEqual(len(state['game']['darts']),1)
        self.assertEqual(state['revision'],rev+1)
    def test_stale_handoff_and_undo_cannot_modify_replacement_game(self):
        rev=self.begin()
        for _ in range(3): rev=self.request('/api/throw',{'value':0,'expected_revision':rev})[1]['revision']
        self.begin(); before=self.request('/api/state')[1]
        for action in ['next','undo','throw']:
            status,state=self.request('/api/'+action,{'value':20,'expected_revision':rev})
            self.assertEqual(status,409); self.assertEqual(state['revision'],before['revision'])
            self.assertEqual(state['game'],before['game'])
    def test_legacy_calls_remain_compatible_and_bad_revision_controlled(self):
        rev=self.begin()
        for value in ['1',True,None,1.1]:
            self.assertEqual(self.request('/api/throw',{'value':20,'expected_revision':value})[0],400)
        self.assertEqual(server.app.revision,rev)
        self.assertEqual(self.request('/api/throw',{'value':20})[0],200)
        self.assertEqual(server.app.game.data['scores'],[281,301])

if __name__=='__main__': unittest.main()
