"""Malformed authorization must return controlled401 without changing a game."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
import server

class ManualAuthorizationRegression(unittest.TestCase):
    def setUp(self):
        self.previous=server.app,server.vision,server.vision_error
        server.app=server.App('manual-auth-test');server.vision=None;server.vision_error='Camera intentionally unavailable'
        server.app.game=server.Game(['A','B']);server.app.game.throw(20,3)
        self.before=server.app.game.snapshot()
        self.httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join()
        server.app,server.vision,server.vision_error=self.previous
    def request(self,method,path,body=None,authorization='Bearer café'):
        c=http.client.HTTPConnection('127.0.0.1',self.httpd.server_port,timeout=3)
        c.request(method,path,json.dumps(body) if body is not None else None,{'Authorization':authorization})
        r=c.getresponse();status=r.status;data=json.loads(r.read());c.close();return status,data
    def test_non_ascii_get_token_returns401_and_retains_manual_game(self):
        status,data=self.request('GET','/api/state')
        self.assertEqual(status,401);self.assertIn('error',data)
        self.assertEqual(server.app.game.snapshot(),self.before)
        self.assertEqual(self.request('GET','/api/state',authorization='Bearer manual-auth-test')[0],200)
    def test_non_ascii_post_token_returns401_without_scoring_or_replacement(self):
        for path,body in [('/api/throw',{'value':20}),('/api/game',{'names':['C','D'],'camera':False})]:
            status,data=self.request('POST',path,body)
            self.assertEqual(status,401);self.assertIn('error',data)
            self.assertEqual(server.app.game.snapshot(),self.before)
            self.assertEqual(len(server.app.game.history),1)

if __name__=='__main__':unittest.main()
