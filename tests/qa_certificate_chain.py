"""Independent checks of staged local CA/leaf material. Never installs trust or generates certificates."""
import argparse
import hashlib
import http.client
import json
import re
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--ca', type=Path, required=True)
parser.add_argument('--certificate', type=Path, required=True)
parser.add_argument('--private-key', type=Path, required=True)
parser.add_argument('--public-ca', type=Path)
parser.add_argument('--lan-ip', required=True)
parser.add_argument('--output', type=Path, default=Path('qa-artifacts/certificate-chain-results.json'))
args = parser.parse_args()
results = []

def check(name, condition, detail=None):
    results.append({'name': name, 'pass': bool(condition), 'detail': detail})
    if not condition:
        raise AssertionError(name)

def openssl(*arguments):
    return subprocess.run(['openssl', *map(str, arguments)], check=True,
                          capture_output=True, text=True).stdout

def certificate_der(data):
    if data.lstrip().startswith(b'-----BEGIN CERTIFICATE-----'):
        return ssl.PEM_cert_to_DER_cert(data.decode())
    return data

ca_text = openssl('x509', '-in', args.ca, '-noout', '-text')
leaf_text = openssl('x509', '-in', args.certificate, '-noout', '-text')
check('CA has critical CA basic constraints and signing key usage',
      bool(re.search(r'Basic Constraints: critical\s+CA:TRUE', ca_text)) and
      bool(re.search(r'Key Usage: critical\s+[^\n]*Certificate Sign[^\n]*CRL Sign', ca_text)))
check('server certificate includes local and actual LAN subject alternative names',
      all(item in leaf_text for item in ('DNS:localhost', 'IP Address:127.0.0.1', 'IP Address:' + args.lan_ip)))
check('server certificate verifies against project public CA',
      ': OK' in openssl('verify', '-CAfile', args.ca, args.certificate))
fingerprint = ':'.join(re.findall('..', hashlib.sha256(certificate_der(args.ca.read_bytes())).hexdigest().upper()))
if args.public_ca:
    check('exported public CA is exactly the trusted CA certificate',
          certificate_der(args.public_ca.read_bytes()) == certificate_der(args.ca.read_bytes()))
    check('exported public CA contains no private key',
          b'PRIVATE KEY' not in args.public_ca.read_bytes())

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        content = b'independent-certificate-qa-only'
        self.send_response(200)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_context.load_cert_chain(args.certificate, args.private_key)
client_context = ssl.create_default_context(cafile=str(args.ca))
httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
httpd.socket = server_context.wrap_socket(httpd.socket, server_side=True)
thread = threading.Thread(target=httpd.serve_forever, daemon=True)
thread.start()
try:
    for hostname in ('localhost', '127.0.0.1', args.lan_ip):
        with socket.create_connection(('127.0.0.1', httpd.server_address[1]), timeout=5) as connection:
            with client_context.wrap_socket(connection, server_hostname=hostname) as secure:
                secure.sendall(('GET / HTTP/1.1\r\nHost: ' + hostname + '\r\nConnection: close\r\n\r\n').encode())
                response = secure.recv(4096)
                check('TLS verifies certificate chain and hostname for ' + hostname,
                      response.startswith(b'HTTP/1.0 200') or response.startswith(b'HTTP/1.1 200'))
    wrong_host_rejected = False
    try:
        with socket.create_connection(('127.0.0.1', httpd.server_address[1]), timeout=5) as connection:
            with client_context.wrap_socket(connection, server_hostname='wrong-host.invalid'):
                pass
    except ssl.SSLCertVerificationError:
        wrong_host_rejected = True
    check('TLS rejects an unrelated hostname', wrong_host_rejected)
finally:
    httpd.shutdown()
    httpd.server_close()
    thread.join()
evidence = {'testOnly': True, 'trustScope': 'Python SSLContext only; no system or phone trust changes',
            'caSha256Fingerprint': fingerprint, 'results': results}
args.output.parent.mkdir(exist_ok=True, parents=True)
args.output.write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))

