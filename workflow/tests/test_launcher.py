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
import git_fixture


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='piano-launcher-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'piano coach'
        self.root.mkdir()
        self.source, self.revision = git_fixture.copy_source(Path(self.temp.name))
        git_fixture.git(self.source.parent, 'tag', 'v' + r.curriculum()['version'])
        (self.root / 'AGENTS.md').write_text('temporary test workspace')
        (self.root / 'profile.json').write_text('{"daily_minutes":30}')
        result = publish.publish(self.source, self.root, activate=True)
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
        version = r.curriculum()['version']
        git_fixture.bump(self.source, version, '9.9.9')
        publish.publish(self.source, self.root, activate=False)
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['version'], version)
        self.assertEqual(publish.runtime.read_pin(self.root)['revision'], self.revision)
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_uv_command_preserves_release_hash_validation(self):
        with (self.release / 'webapp.js').open('a') as stream:
            stream.write('\n// deliberate test-only corruption\n')
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 2)
        self.assertIn('실행 캐시가 수정되었습니다', result.stderr)
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
        files = [self.root / 'practice.csv', self.root / 'active-version', self.root / 'runtime.json',
                 *self.release.iterdir()]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}
        install_launcher.install(self.root)
        self.assertTrue(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items()))
        for name in install_launcher.FILES:
            self.assertEqual((self.root / name).read_bytes(), (install_launcher.SOURCE / name).read_bytes())

    def test_deleted_cache_rebuilds_pinned_commit_after_tag_and_source_change(self):
        original = (self.release / 'COACH.md').read_bytes()
        git_fixture.bump(self.source, r.curriculum()['version'], '9.9.9')
        git_fixture.git(self.source.parent, 'tag', '-f', 'v' + r.curriculum()['version'])
        (self.source / 'COACH.md').write_text('uncommitted development change')
        shutil.rmtree(self.release)
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['version'], r.curriculum()['version'])
        self.assertEqual((self.release / 'COACH.md').read_bytes(), original)
        self.assertEqual(publish.runtime.read_pin(self.root)['revision'], self.revision)

    def test_first_launch_initializes_pin_from_default_ref_without_practice(self):
        (self.root / 'runtime.json').unlink()
        (self.root / 'active-version').unlink()
        shutil.rmtree(self.release)
        result = self.run_uv('runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'], self.revision)
        self.assertEqual(publish.runtime.read_pin(self.root)['revision'], self.revision)
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_missing_pin_does_not_guess_runtime_for_existing_practice(self):
        (self.root / 'runtime.json').unlink()
        (self.root / 'practice.csv').write_text('test-only evidence sentinel')
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('runtime.json이 없습니다', result.stderr)
        self.assertFalse((self.root / 'runtime.json').exists())
        self.assertEqual((self.root / 'practice.csv').read_text(), 'test-only evidence sentinel')

    def test_missing_git_object_does_not_run_current_development_source(self):
        pin = publish.runtime.read_pin(self.root)
        pin['revision'] = '0' * 40
        (self.root / 'runtime.json').write_text(json.dumps(pin))
        result = self.run_uv('status')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Git 커밋을 읽을 수 없습니다', result.stderr)
        self.assertFalse((self.root / 'practice.csv').exists())

    def test_legacy_cli_runtime_explains_missing_web_support(self):
        for name in publish.runtime.WEB:
            (self.source / name).unlink()
        git_fixture.bump(self.source, r.curriculum()['version'], '0.1.2')
        publish.publish(self.source, self.root, activate=True)
        result = self.run_uv()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('활성 런타임 0.1.2은 웹을 지원하지 않습니다', result.stderr)
        self.assertNotIn('invalid choice', result.stderr)
        self.assertFalse((self.root / 'practice.csv').exists())


if __name__ == '__main__':
    unittest.main()
