"""M1-13: plain HTTP on the LAN by default, optional --https, and the camera setup API."""
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
TOKEN = 'setup-page-token'


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def start_server(args, environment=None, code=None):
    command = [sys.executable, '-B'] + (['-c', code] if code else [str(ROOT / 'server.py')]) + args
    process = subprocess.Popen(command, cwd=ROOT, env=environment or os.environ.copy(),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    while not any(line.startswith('Camera source:') for line in lines):
        line = process.stdout.readline()
        if not line:
            process.wait(5)
            raise AssertionError('server did not start:\n' + ''.join(lines))
        lines.append(line)
    return process, ''.join(lines)


def stop(process):
    process.terminate()
    process.wait(5)
    process.stdout.close()


class ServerStartup(unittest.TestCase):
    def test_plain_http_on_all_interfaces_is_the_default_and_needs_no_openssl(self):
        port = free_port()
        with tempfile.TemporaryDirectory() as empty_path:
            process, output = start_server(['--port', str(port)], {**os.environ, 'PATH': empty_path})
            try:
                self.assertIn(f'listening on 0.0.0.0:{port} (HTTP)', output)
                self.assertIn('Setup:        http://localhost:', output)
                self.assertIn('Controller:   http://', output)
                self.assertIn('Presentation: http://', output)
                self.assertNotIn('Phone:', output)
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                connection.request('GET', '/')
                response = connection.getresponse()
                body = response.read().decode()
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertIn('Camera setup', body)
            finally:
                stop(process)

    def test_camera_flag_with_a_sim_folder_serves_on_all_interfaces(self):
        import cv2
        from sim import camera_for_mount
        from sim.scene import render_clean
        port = free_port()
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as empty_path:
            cv2.imwrite(os.path.join(folder, 'board.png'), render_clean(camera_for_mount('left', 1280, 720), []))
            process, output = start_server(['--port', str(port), '--camera', f'dir:{folder}?loop=1&fps=10'],
                                           {**os.environ, 'PATH': empty_path})
            try:
                self.assertIn('0.0.0.0', output)
                self.assertIn('Camera source: dir:', output)
            finally:
                stop(process)

    @unittest.skipUnless(shutil.which('openssl'), 'the optional --https path needs OpenSSL')
    def test_https_is_still_available(self):
        port = free_port()
        with tempfile.TemporaryDirectory() as folder:
            code = f'import pathlib, server; server.HTTPS_ROOT = pathlib.Path({folder!r}); server.main()'
            process, output = start_server(['--https', '--host', '127.0.0.1', '--port', str(port),
                                            '--lan-ip', '127.0.0.1'], code=code)
            try:
                self.assertIn(f'listening on 127.0.0.1:{port} (HTTPS)', output)
                self.assertIn('CA SHA-256:', output)
                context = ssl.create_default_context(cafile=os.path.join(folder, '.local/pki/ca.pem'))
                connection = http.client.HTTPSConnection('127.0.0.1', port, timeout=5, context=context)
                connection.request('GET', '/')
                response = connection.getresponse()
                response.read()
                connection.close()
                self.assertEqual(response.status, 200)
            finally:
                stop(process)


class StaticPages(unittest.TestCase):
    def test_no_browser_camera_code_remains(self):
        for path in (ROOT / 'static').iterdir():
            self.assertNotIn('getUserMedia', path.read_text(encoding='utf-8'), path.name)


class SetupApi(unittest.TestCase):
    def setUp(self):
        import server
        from vision import Vision
        self.server_module = server
        self.previous = (server.app, server.vision)
        server.app = server.App(TOKEN)
        server.vision = Vision()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server_module.set_camera_source(None)
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join()
        self.server_module.app, self.server_module.vision = self.previous

    def request(self, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=15)
        payload = json.dumps(body).encode() if body is not None else None
        connection.request('POST' if payload is not None else 'GET', path, payload, {'Authorization': 'Bearer ' + TOKEN})
        response = connection.getresponse()
        data, status, mime = response.read(), response.status, response.getheader('Content-Type', '')
        connection.close()
        return status, json.loads(data) if 'json' in mime else data

    def test_setup_assets_and_old_phone_link(self):
        for path in ('/', '/phone', '/static/setup.js', '/static/setup.css'):
            status, _ = self.request(path)
            self.assertEqual(status, 200, path)

    def test_connection_test_reports_size_without_switching_source(self):
        from fake_ipwebcam import FakeIPWebcam, sim_frames
        fake = FakeIPWebcam(sim_frames('left', 1280, 720)[1], fps=15).start()
        try:
            status, result = self.request('/api/camera/test', {'uri': fake.url + '/video'})
            self.assertEqual(status, 200)
            self.assertTrue(result['ok'], result)
            self.assertEqual((result['width'], result['height'], result['kind']), (1280, 720, 'mjpeg'))
            self.assertIsNone(self.request('/api/state')[1]['vision']['source'])
        finally:
            fake.stop()
        status, result = self.request('/api/camera/test', {'uri': fake.url + '/video'})
        self.assertFalse(result['ok'])
        self.assertIn('refused', result['error'])
        self.assertFalse(self.request('/api/camera/test', {'uri': 'nonsense address'})[1]['ok'])

    def test_mount_side_override(self):
        status, state = self.request('/api/camera/mount_side', {'mount_side': 'top'})
        self.assertEqual(status, 200, state)
        self.assertEqual(state['vision']['mount_side'], 'top')
        self.assertEqual(self.request('/api/camera/mount_side', {'mount_side': 'ceiling'})[0], 400)
        self.assertIsNone(self.request('/api/camera/mount_side', {'mount_side': None})[1]['vision']['mount_side'])


if __name__ == '__main__':
    unittest.main()
