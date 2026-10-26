"""Managed local CA/leaf and public-download regression checks."""
import http.client
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from http.server import HTTPServer
from local_https import prepare,activate,bootstrap_handler,PUBLIC_CERTIFICATE,fingerprint,openssl

class LocalHttpsRegression(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.info=prepare(self.root,'192.168.4.112')
    def tearDown(self):self.temporary.cleanup()
    def test_ca_persists_when_leaf_ip_changes_and_has_signing_constraints(self):
        ca=(self.root/'.local/pki/ca.pem').read_bytes()
        key=(self.root/'.local/pki/ca-key.pem').read_bytes()
        second=prepare(self.root,'192.168.4.113')
        self.assertEqual(ca,(self.root/'.local/pki/ca.pem').read_bytes())
        self.assertEqual(key,(self.root/'.local/pki/ca-key.pem').read_bytes())
        self.assertEqual(self.info['sha256_fingerprint'],second['sha256_fingerprint'])
        details=openssl('x509','-in',self.root/'.local/pki/ca.pem','-noout','-text').stdout.decode()
        self.assertIn('CA:TRUE',details);self.assertIn('Certificate Sign',details)
        leaf=openssl('x509','-in',self.root/'.local/pki/server.pem','-noout','-text').stdout.decode()
        self.assertIn('CA:FALSE',leaf);self.assertIn('TLS Web Server Authentication',leaf)
        self.assertIn('IP Address:192.168.4.113',leaf)
    def test_preparation_preserves_active_certificate_and_activation_backs_it_up(self):
        config=self.root/'.local';(config/'certificate.pem').write_text('old certificate')
        (config/'private-key.pem').write_text('old key')
        prepare(self.root,'192.168.4.112')
        self.assertEqual((config/'certificate.pem').read_text(),'old certificate')
        cert,key,info=activate(self.root,'192.168.4.112')
        self.assertEqual((config/'legacy-self-signed/certificate.pem').read_text(),'old certificate')
        self.assertEqual((config/'legacy-self-signed/private-key.pem').read_text(),'old key')
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        self.assertEqual(key.stat().st_mode&0o777,0o600)
        self.assertEqual((config/'pki/ca-key.pem').stat().st_mode&0o777,0o600)
    def test_public_download_exports_only_exact_public_certificate_routes(self):
        server=HTTPServer(('127.0.0.1',0),bootstrap_handler(self.root,self.info))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,method='GET'):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            connection.request(method,path);response=connection.getresponse();body=response.read()
            status=response.status;connection.close();return status,body
        try:
            status,public=request('/'+PUBLIC_CERTIFICATE)
            self.assertEqual(status,200);self.assertEqual(fingerprint(public),self.info['sha256_fingerprint'])
            self.assertEqual(public,(self.root/'.local/pki'/PUBLIC_CERTIFICATE).read_bytes())
            self.assertNotIn(b'PRIVATE KEY',public)
            for path in ('/.local/pki/ca-key.pem','/ca-key.pem','/private-key.pem','/api/state','/api/frame','/static/','/../ca-key.pem','/%2e%2e/ca-key.pem'):
                self.assertEqual(request(path)[0],404,path)
            self.assertEqual(request('/','POST')[0],404)
            self.assertIn(self.info['sha256_fingerprint'].encode(),request('/')[1])
        finally:server.shutdown();server.server_close();thread.join()
    def test_missing_half_of_ca_is_not_silently_replaced(self):
        (self.root/'.local/pki/ca-key.pem').unlink()
        with self.assertRaisesRegex(RuntimeError,'incomplete'):prepare(self.root,'192.168.4.112')

if __name__=='__main__':unittest.main()
