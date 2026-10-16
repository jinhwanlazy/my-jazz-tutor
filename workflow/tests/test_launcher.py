"""Exercise the installed uv command in disposable practice workspaces."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

import install_launcher
import publish
import review as r


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='piano-launcher-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'piano coach'
        self.root.mkdir()
        (self.root / 'AGENTS.md').write_text('temporary test workspace')
        (self.root / 'profile.json').write_text('{"daily_minutes":30}')
        shutil.copy2(r.HERE.parent / 'practice' / 'jazz', self.root / 'jazz')
        result = publish.publish(r.HERE, self.root, activate=True)
        self.release = Path(result['installed'])
        install_launcher.install(self.root)
        self.env = os.environ.copy()
        self.env.pop('VIRTUAL_ENV', None)
        self.env.pop('UV_PROJECT_ENVIRONMENT', None)
        self.env['UV_OFFLINE'] = '1'

    def run_uv(self, *args):
        return subprocess.run(['uv', 'run', '--frozen', 'jazz', *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=20)

    def test_uv_command_uses_active_release_even_if_newer_is_installed(self):
        older = r.HERE.parent / 'practice' / 'releases' / '0.1.2'
        shutil.copytree(older, self.root / 'releases' / '0.1.2',
                        ignore=shutil.ignore_patterns('.venv', '__pycache__'))
        (self.root / 'active-version').write_text('0.1.2\n')
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['version'], '0.1.2')
        self.assertEqual((self.root / 'active-version').read_text(), '0.1.2\n')
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_uv_command_preserves_release_hash_validation(self):
        with (self.release / 'webapp.js').open('a') as stream:
            stream.write('\n// deliberate test-only corruption\n')
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 2)
        self.assertIn('발행본이 수정되었습니다', result.stderr)
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_no_argument_command_delegates_web_and_browser_flags(self):
        # Probe the bootstrap boundary without opening an actual browser/default port.
        (self.root / 'jazz').write_text('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        result = self.run_uv()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['serve', '--open'])
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_uv_server_accepts_port_and_open_options_without_creating_a_task(self):
        opened = Path(self.temp.name) / 'opened-url'
        browser = Path(self.temp.name) / 'test-browser'
        browser.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\n'
                           f'Path({str(opened)!r}).write_text(sys.argv[1])\n')
        browser.chmod(0o755)
        environment = self.env | {'BROWSER': f'{shlex.quote(str(browser))} %s'}
        process = subprocess.Popen(['uv', 'run', '--frozen', 'jazz', 'serve', '--open', '--port', '0'],
                                   cwd=self.root, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=15), 'server did not start')
            line = process.stdout.readline().strip()
            self.assertIn('http://127.0.0.1:', line)
            url = line.split(' · ')[1]
            connection = http.client.HTTPConnection('127.0.0.1', int(url.rsplit(':', 1)[1]), timeout=5)
            try:
                connection.request('GET', '/api/state')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                state = json.loads(response.read())
            finally:
                connection.close()
            self.assertEqual(state['status']['version'], r.curriculum()['version'])
            self.assertFalse(state['preview'])
            self.assertEqual(state['history'], [])
            deadline = time.monotonic() + 3
            while not opened.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(opened.read_text(), url)
            self.assertFalse((self.root / 'practice.csv').exists())
            self.assertFalse((self.root / 'sessions.sqlite3').exists())
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)

    def test_installer_only_updates_bootstrap_files(self):
        (self.root / 'practice.csv').write_text('test-only evidence sentinel')
        files = [self.root / 'practice.csv', self.root / 'active-version', self.root / 'jazz',
                 *self.release.iterdir()]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}
        install_launcher.install(self.root)
        self.assertTrue(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items()))
        for name in install_launcher.FILES:
            self.assertEqual((self.root / name).read_bytes(), (install_launcher.SOURCE / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
