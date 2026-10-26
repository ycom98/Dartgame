"""Independent public-CA bootstrap route checks; never installs trust or restarts the live app."""
import hashlib
import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import local_https

pki = root / '.local/pki'
info = json.loads((pki / 'info.json').read_text())
active = [root / '.local/certificate.pem', root / '.local/private-key.pem']
before = [hashlib.sha256(path.read_bytes()).digest() for path in active]
public = (pki / local_https.PUBLIC_CERTIFICATE).read_bytes()
results = []
def check(name, condition):
    results.append({'name': name, 'pass': bool(condition)})
    if not condition:
        raise AssertionError(name)
httpd = ThreadingHTTPServer(('127.0.0.1', 0), local_https.bootstrap_handler(root, info))
worker = threading.Thread(target=httpd.serve_forever, daemon=True)
worker.start()
def request(route, method='GET'):
    connection = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1], timeout=5)
    connection.request(method, route, body=b'{}' if method == 'POST' else None)
    response = connection.getresponse()
    status, body = response.status, response.read()
    headers = dict(response.getheaders())
    connection.close()
    return status, body, headers
try:
    status, body, headers = request('/')
    check('bootstrap identity page shows the exact CA and manual trust explanation',
          status == 200 and info['sha256_fingerprint'].encode() in body and
          info['ca_subject'].encode() in body and b'cannot install or trust anything automatically' in body)
    status, body, headers = request('/' + local_https.PUBLIC_CERTIFICATE)
    check('only the exact public DER certificate is downloadable',
          status == 200 and body == public and b'PRIVATE KEY' not in body and
          headers.get('Content-Type') == 'application/x-x509-ca-cert' and
          'attachment' in headers.get('Content-Disposition', ''))
    status, body, headers = request('/fingerprint')
    check('fingerprint route matches independent DER SHA256',
          status == 200 and body.decode().strip() == local_https.fingerprint(public) ==
          info['sha256_fingerprint'])
    for route in ('/.local/pki/ca-key.pem', '/.local/pki/server-key.pem', '/private-key.pem',
                  '/api/state', '/phone', '/server.py', '/../.local/pki/ca-key.pem',
                  '/%2e%2e/.local/pki/ca-key.pem'):
        check('non-allowlisted route is not served: ' + route, request(route)[0] == 404)
    check('POST cannot access public download or mutate state',
          request('/' + local_https.PUBLIC_CERTIFICATE, 'POST')[0] == 404)
finally:
    httpd.shutdown()
    httpd.server_close()
    worker.join()
after = [hashlib.sha256(path.read_bytes()).digest() for path in active]
check('bootstrap QA leaves active certificate and private key unchanged', before == after)
evidence = {'testOnly': True, 'scope': 'Own ephemeral bootstrap handler; no trust changes or live8443 restart',
            'results': results}
(root / 'qa-artifacts/ca-bootstrap-results.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))

