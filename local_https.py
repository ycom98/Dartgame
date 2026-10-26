"""Project-only HTTPS certificates and temporary public-CA download. Never installs trust."""
import argparse
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PUBLIC_CERTIFICATE = 'DartRoom-Local-CA.crt'


def openssl(*args, check=True):
    result = subprocess.run(['openssl', *map(str,args)],capture_output=True)
    if check and result.returncode:
        raise RuntimeError('OpenSSL '+str(args[0])+' failed: '+result.stderr.decode(errors='replace').strip())
    return result


def fingerprint(der):
    digest=hashlib.sha256(der).hexdigest().upper()
    return ':'.join(digest[i:i+2] for i in range(0,len(digest),2))


def prepare(project, lan_ip):
    """Prepare a stable CA and signed leaf without replacing running certificate files."""
    lan_ip=str(ipaddress.IPv4Address(lan_ip))
    project=Path(project);config=project/'.local';pki=config/'pki'
    previous_umask=os.umask(0o077)
    try:
        config.mkdir(mode=0o700,exist_ok=True);pki.mkdir(mode=0o700,exist_ok=True)
        config.chmod(0o700);pki.chmod(0o700)
        ca=pki/'ca.pem';ca_key=pki/'ca-key.pem'
        if ca.exists() != ca_key.exists():
            raise RuntimeError('Project CA is incomplete. Restore matching ca.pem and ca-key.pem; do not silently replace an installed CA.')
        if not ca.exists():
            ca_name='Dart Room Local CA '+secrets.token_hex(4).upper()
            ca_config=pki/'ca.cnf'
            ca_config.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=v3_ca\n'
                '[dn]\nCN='+ca_name+'\nO=Dart Room\n[v3_ca]\nbasicConstraints=critical,CA:TRUE,pathlen:0\n'
                'keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n')
            openssl('req','-x509','-newkey','rsa:3072','-nodes','-sha256','-days','365',
                    '-keyout',ca_key,'-out',ca,'-config',ca_config)
        ca_key.chmod(0o600)
        if openssl('x509','-checkend','86400','-noout','-in',ca,check=False).returncode:
            raise RuntimeError('Local CA is expired or expires within one day. Replace deliberately and update device trust; automatic CA rotation is disabled.')
        certificate_public=openssl('x509','-in',ca,'-pubkey','-noout').stdout.strip()
        key_public=openssl('pkey','-in',ca_key,'-pubout').stdout.strip()
        if certificate_public != key_public:raise RuntimeError('Project CA certificate and private key do not match.')
        ca_text=openssl('x509','-in',ca,'-noout','-text').stdout.decode()
        if 'CA:TRUE' not in ca_text or 'Certificate Sign' not in ca_text:
            raise RuntimeError('Project ca.pem is not a certificate-signing CA.')
        cert=pki/'server.pem';key=pki/'server-key.pem';ip_file=pki/'server-ip.txt'
        renew=not cert.exists() or not key.exists() or not ip_file.exists() or ip_file.read_text()!=lan_ip
        if not renew:
            renew=bool(openssl('x509','-checkend','86400','-noout','-in',cert,check=False).returncode or
                       openssl('verify','-CAfile',ca,cert,check=False).returncode)
        if renew:
            server_config=pki/'server.cnf';csr=pki/'server.csr'
            server_config.write_text('[req]\nprompt=no\ndistinguished_name=dn\n[dn]\nCN=Dart Room Local Server\n'
                '[v3_server]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                'extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n'
                'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:'+lan_ip+'\n')
            openssl('req','-new','-newkey','rsa:2048','-nodes','-keyout',key,'-out',csr,'-config',server_config)
            openssl('x509','-req','-in',csr,'-CA',ca,'-CAkey',ca_key,'-set_serial','0x'+secrets.token_hex(16),
                    '-days','30','-sha256','-extfile',server_config,'-extensions','v3_server','-out',cert)
            ip_file.write_text(lan_ip)
        key.chmod(0o600)
        public_der=openssl('x509','-in',ca,'-outform','DER').stdout
        (pki/PUBLIC_CERTIFICATE).write_bytes(public_der)
        (pki/'server-chain.pem').write_bytes(cert.read_bytes()+ca.read_bytes())
        subject=openssl('x509','-in',ca,'-noout','-subject','-nameopt','RFC2253').stdout.decode().strip()
        expires=openssl('x509','-in',ca,'-noout','-enddate').stdout.decode().strip().removeprefix('notAfter=')
        info={'ca_subject':subject.removeprefix('subject=').strip(),'sha256_fingerprint':fingerprint(public_der),
              'ca_expires':expires,'lan_ip':lan_ip,'public_certificate':PUBLIC_CERTIFICATE,
              'ca_path':str(ca),'staged_certificate':str(pki/'server-chain.pem'),'staged_private_key':str(key)}
        (pki/'info.json').write_text(json.dumps(info,indent=2)+'\n')
        return info
    finally:os.umask(previous_umask)


def atomic_write(path,content,mode):
    path=Path(path)
    if path.exists() and path.read_bytes()==content:
        path.chmod(mode);return
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.dart-cert-',delete=False) as temporary:
        temporary.write(content);temporary_path=Path(temporary.name)
    temporary_path.chmod(mode);temporary_path.replace(path)


def activate(project,lan_ip):
    """Activate prepared leaf on startup. Stop the old app before invoking this."""
    project=Path(project);info=prepare(project,lan_ip);config=project/'.local'
    cert=config/'certificate.pem';key=config/'private-key.pem';marker=config/'certificate-ca-sha256.txt'
    if not marker.exists() and (cert.exists() or key.exists()):
        backup=config/'legacy-self-signed';backup.mkdir(mode=0o700,exist_ok=True)
        for old in (cert,key):
            destination=backup/old.name
            if old.exists() and not destination.exists():
                shutil.copyfile(old,destination);destination.chmod(0o600)
    atomic_write(cert,Path(info['staged_certificate']).read_bytes(),0o644)
    atomic_write(key,Path(info['staged_private_key']).read_bytes(),0o600)
    atomic_write(config/'certificate-ip.txt',str(lan_ip).encode(),0o600)
    atomic_write(marker,(info['sha256_fingerprint']+'\n').encode(),0o644)
    return cert,key,info


def bootstrap_handler(project,info):
    """Expose exactly the public CA, public identity page and fingerprint."""
    public_der=(Path(project)/'.local/pki'/PUBLIC_CERTIFICATE).read_bytes()
    public_fingerprint=info['sha256_fingerprint']
    page=('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dart Room local certificate setup</title><h1>Dart Room local certificate setup</h1>
<p>This page serves one public certificate. It cannot install or trust anything automatically.</p>
<p>Certificate authority: <strong>'''+html.escape(info['ca_subject'])+'''</strong></p>
<p>Expires: '''+html.escape(info['ca_expires'])+'''</p><p>SHA-256 fingerprint:</p>
<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'''+html.escape(public_fingerprint)+'''</pre>
<p>Before installing, compare this entire fingerprint with the value shown on your Mac or in your trusted setup chat. This download uses local HTTP; the matching fingerprint establishes which certificate you are accepting.</p>
<p><a href="/'''+PUBLIC_CERTIFICATE+'''" download="'''+PUBLIC_CERTIFICATE+'''">Download the Dart Room public CA certificate</a></p>
<p>Installing a CA tells the device to trust certificates signed by its private key. This project's private key stays on your Mac. Install only if you understand and accept that trust.</p>
<ol><li>On the Galaxy S22 (SM-S901U), download the public certificate above.</li>
<li>In Android Settings, search for "Install a certificate" or "CA certificate". Choose <strong>CA certificate</strong>, then select the downloaded file. Samsung menu names can vary. This is a manual device setting, not a website permission.</li>
<li>After installing, close and reopen Chrome, then open the complete current HTTPS Phone link from the Mac. It must show "Connection trusted for camera: Yes" and "Camera access API: Available".</li>
<li>Press Start rear camera and allow camera permission. Keep the entire empty board visible.</li></ol>
<p>To remove this trust later, find this uniquely named Dart Room CA under Android Settings' user-installed/trusted credentials and remove it. Avoid removing unrelated certificates.</p>
<p>No game control, camera image, pairing token, private key or directory listing is available on this temporary server. It shuts down automatically after its setup window.</p></html>''').encode()
    class PublicCaHandler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(3)
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlparse(self.path).path
            if path=='/':payload=page;mime='text/html; charset=utf-8';download=False
            elif path=='/'+PUBLIC_CERTIFICATE:payload=public_der;mime='application/x-x509-ca-cert';download=True
            elif path=='/fingerprint':payload=(public_fingerprint+'\n').encode();mime='text/plain; charset=utf-8';download=False
            else:self.send_error(404,'Not found');return
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'")
            if download:self.send_header('Content-Disposition','attachment; filename="'+PUBLIC_CERTIFICATE+'"')
            self.end_headers();self.wfile.write(payload)
        def do_POST(self):self.send_error(404,'Not found')
    return PublicCaHandler


def serve(project,lan_ip,host='0.0.0.0',port=8765,duration=600):
    info=prepare(project,lan_ip)
    if not 1<=duration<=600:raise ValueError('Certificate download window must be between 1 and 600 seconds')
    server=HTTPServer((host,port),bootstrap_handler(project,info));server.timeout=1
    print('Public CA download: http://'+str(lan_ip)+':'+str(server.server_port)+'/',flush=True)
    print('CA identity: '+info['ca_subject'],flush=True)
    print('SHA-256 fingerprint: '+info['sha256_fingerprint'],flush=True)
    print('Public certificate only. No trust installed. Stops automatically after '+str(duration)+' seconds.',flush=True)
    deadline=time.monotonic()+duration
    try:
        while time.monotonic()<deadline:server.handle_request()
    except KeyboardInterrupt:pass
    finally:server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','serve'))
    parser.add_argument('--lan-ip',required=True,help='Mac Wi-Fi IPv4 address')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--duration',type=int,default=600)
    parser.add_argument('--host',default='0.0.0.0')
    args=parser.parse_args();project=Path(__file__).resolve().parent
    try:
        if args.action=='prepare':print(json.dumps(prepare(project,args.lan_ip),indent=2))
        else:serve(project,args.lan_ip,args.host,args.port,args.duration)
    except (OSError,ValueError,RuntimeError) as error:parser.exit(1,'Local certificate setup failed: '+str(error)+'\n')

if __name__=='__main__':main()
