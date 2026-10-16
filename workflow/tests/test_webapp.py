"""Synthetic input in temporary workspaces, never production practice evidence."""
import base64
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import review as r
import publish
import git_fixture
from sessions import FRAME, SessionStore, measurements, midi_messages
from webapp import Application, make_server


def raw(*messages):
    return b''.join(FRAME.pack(at, port, len(data)) + bytes(data) for at, port, data in messages)


def chunk(blob=b'', events=None, elapsed=10000, seq=0):
    return {'sequence': seq, 'midi': base64.b64encode(blob).decode(),
            'events': events or [], 'elapsed_ms': elapsed}


def measure(blob=b'', events=None, interrupted=False):
    return measurements([{'midi': blob, 'events': events or [], 'elapsed_ms': 10000}], interrupted)


class MeasurementTests(unittest.TestCase):
    def test_trim_ignores_clock_controls_and_preserves_tempo_at_last_note(self):
        blob = raw((100, 0, [0xf8]), (2000, 0, [0x90, 60, 100]),
                   (3000, 0, [0x80, 60, 0]), (5000, 0, [0x91, 64, 90]),
                   (7000, 0, [0x91, 64, 0]), (9000, 0, [0xb0, 1, 127]))
        result = measure(blob, [{'type': 'play', 'at_ms': 0, 'bpm': 60},
                                {'type': 'tempo', 'at_ms': 4000, 'bpm': 80},
                                {'type': 'tempo', 'at_ms': 8000, 'bpm': 100}])
        self.assertEqual(result['input_span_ms'], 5000)
        self.assertEqual(result['note_ons'], 2)
        self.assertEqual(result['midi_messages'], 6)
        self.assertEqual(result['last_note_bpm'], 80)
        self.assertEqual(result['last_setting_bpm'], 100)
        self.assertNotIn('notes_correct', result)

    def test_sustain_tracks_each_input_and_channel(self):
        blob = raw((1000, 0, [0x90, 60, 100]), (1500, 0, [0xb0, 64, 127]),
                   (2000, 0, [0x80, 60, 0]), (3000, 1, [0xb0, 64, 0]),
                   (4000, 0, [0xb1, 64, 0]), (6000, 0, [0xb0, 64, 0]))
        self.assertEqual(measure(blob)['input_span_ms'], 5000)
        self.assertIsNone(measure(blob[:-15])['input_span_ms'])

    def test_missing_note_off_or_disconnect_is_not_exact_time(self):
        held = raw((1000, 0, [0x90, 60, 90]))
        self.assertIsNone(measure(held)['input_span_ms'])
        self.assertIn('held_notes', measure(held)['capture_warnings'])
        complete = held + raw((2000, 0, [0x80, 60, 0]))
        self.assertIsNone(measure(complete, [{'type': 'disconnect', 'at_ms': 3000}])['input_span_ms'])
        self.assertIsNone(measure(complete, interrupted=True)['input_span_ms'])

    def test_all_notes_off_respects_sustain_and_controller_reset_releases_it(self):
        prefix = raw((1000, 0, [0x90, 60, 100]), (1500, 0, [0xb0, 64, 127]),
                     (2000, 0, [0xb0, 123, 0]))
        self.assertIsNone(measure(prefix)['input_span_ms'])
        self.assertEqual(measure(prefix + raw((4000, 0, [0xb0, 121, 0])))['input_span_ms'], 3000)
        self.assertEqual(measure(prefix + raw((3000, 0, [0xb0, 120, 0])))['input_span_ms'], 2000)

    def test_no_midi_remains_unknown_and_active_time_excludes_pause(self):
        result = measure(events=[{'type': 'play', 'at_ms': 500, 'bpm': 60},
                                 {'type': 'pause', 'at_ms': 3000},
                                 {'type': 'play', 'at_ms': 6000, 'bpm': 72},
                                 {'type': 'pause', 'at_ms': 8000}])
        self.assertEqual(result['active_ms'], 4500)
        self.assertIsNone(result['input_span_ms'])
        self.assertIsNone(result['last_note_bpm'])
        self.assertEqual(result['last_setting_bpm'], 72)

    def test_truncated_or_nonfinite_binary_is_rejected(self):
        for blob in [b'bad', FRAME.pack(1, 0, 3) + b'\x90', FRAME.pack(float('nan'), 0, 1) + b'\xf8']:
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                list(midi_messages(blob))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = r.curriculum()
        self.app = Application(self.root, self.data)
        self.store = self.app.store
        self.task = self.app.post('/api/assign', {'exercise_id': 'E01'})['task_id']

    def start(self):
        return self.store.start(self.task)['id']

    def test_language_switch_preserves_reports_and_names_missing_conditions(self):
        note = 'Original user wording: 한국어 and English.'
        self.app.post('/api/report', {'task_id': self.task, 'result': {
            'raw_note': note, 'actual': {'bpm': 72},
            'checks': dict.fromkeys(r.CHECKS, True)}})
        before = (self.root / 'practice.csv').read_bytes()
        english, korean = self.app.state('en'), self.app.state('ko')
        for state in (english, korean):
            self.assertEqual(state['history'][0]['report']['raw_note'], note)
            self.assertEqual(state['history'][0]['outcome'], 'unknown')
            self.assertEqual(state['status']['reported_attempts'], 1)
            self.assertEqual(state['status']['goals'][0]['state'], 'attempted')
        self.assertEqual(english['history'][0]['feedback']['title'], 'Practice saved · assessment pending')
        self.assertIn('연속 성공 횟수', ' '.join(korean['history'][0]['feedback']['details']))
        self.assertIn('손 구성', ' '.join(korean['history'][0]['feedback']['details']))
        self.assertIn('Bar count', ' '.join(english['history'][0]['feedback']['details']))
        self.assertEqual(korean['exercises'][0]['title'], self.data['exercises'][0]['title'])
        self.assertEqual(english['status']['goals'], korean['status']['goals'])
        self.assertEqual((self.root / 'practice.csv').read_bytes(), before)

    def test_missing_run_count_is_not_a_failure_or_an_inferred_success(self):
        saved = self.app.post('/api/report', {'task_id': self.task, 'result': {
            'raw_note': 'Synthetic check', 'followed_target': True,
            'checks': dict.fromkeys(r.CHECKS, True)}}, 'ko')
        self.assertEqual(saved['outcome'], 'unknown')
        details = ' '.join(saved['feedback']['details'])
        self.assertIn('연속 성공 횟수', details)
        self.assertNotIn('아직 확인되지 않은 조건', details)
        self.assertIn('판정 보류', saved['feedback']['title'])
        self.assertEqual(r.read_events(self.root)[-1]['clean_runs'], '')

    def test_english_presentation_preserves_snapshots_notes_and_progress(self):
        canonical = copy.deepcopy(self.data)
        assignment = r.read_events(self.root)[0]
        before = (self.root / 'practice.csv').read_bytes()
        state = self.app.state()
        self.assertNotRegex(json.dumps(state['exercises'], ensure_ascii=False), r'[가-힣]')
        self.assertNotRegex(json.dumps(state['history'][0]['target'], ensure_ascii=False), r'[가-힣]')
        self.assertNotRegex(json.dumps(state['status']['next'], ensure_ascii=False), r'[가-힣]')
        self.assertEqual((self.root / 'practice.csv').read_bytes(), before)
        self.assertEqual(self.data, canonical)
        # A user note that happens to match a built-in label must stay verbatim.
        note = self.data['exercises'][0]['title']
        saved = self.app.post('/api/report', {'task_id': self.task, 'result': {
            'raw_note': note, 'followed_target': True,
            'checks': dict.fromkeys(r.CHECKS, True), 'clean_runs': 2}})
        state = self.app.state()
        self.assertEqual(state['history'][0]['report']['raw_note'], note)
        self.assertEqual(r.read_events(self.root)[0], assignment)
        self.assertEqual(saved['outcome'], 'success')
        self.assertNotRegex(json.dumps(saved['feedback'], ensure_ascii=False), r'[가-힣]')
        self.assertEqual(state['status']['goals'][0]['state'], 'success')
        self.assertEqual(len(r.goal_successes(self.data, r.records(r.read_events(self.root)),
                                             'E01', 'C', 60)), 1)
        self.assertNotIn('C', state['exercises'][2]['eligible_keys'])

    def test_start_is_idempotent_but_only_one_capture_can_be_open(self):
        sid = self.start()
        self.assertEqual(self.store.start(self.task, sid)['id'], sid)
        with self.assertRaises(ValueError):
            self.start()
        self.store.finish(sid, 0)
        self.assertNotEqual(self.start(), sid)

    def test_retry_packets_and_finished_archive_are_immutable(self):
        sid = self.start()
        blob = raw((1000, 2, [0x92, 61, 127]), (2000, 2, [0x82, 61, 0]))
        packet = chunk(blob, [{'type': 'play', 'at_ms': 0, 'bpm': 70}])
        self.assertFalse(self.store.append(sid, packet)['duplicate'])
        self.assertTrue(self.store.append(sid, packet)['duplicate'])
        with self.assertRaises(ValueError):
            self.store.append(sid, packet | {'elapsed_ms': 11000})
        with self.assertRaises(ValueError):
            self.store.finish(sid, 2)
        summary = self.store.finish(sid, 1)
        self.assertEqual(self.store.finish(sid, 1, True), summary)
        self.assertTrue(self.store.append(sid, packet)['duplicate'])
        with self.assertRaises(ValueError):
            self.store.append(sid, chunk(seq=1))
        exported, metadata = self.store.export(sid)
        self.assertEqual(exported, b'JPM1' + blob)
        self.assertEqual(metadata['target']['bpm'], 60)
        self.assertEqual(metadata['summary']['last_note_bpm'], 70)
        self.assertEqual(len(r.read_events(self.root)), 1)

    def test_reopening_store_keeps_chunks_without_inventing_a_report(self):
        sid = self.start()
        self.store.append(sid, chunk(raw((1200, 0, [0x90, 60, 100]))))
        reopened = SessionStore(self.root)
        self.assertEqual(reopened.list()[0]['next_sequence'], 1)
        result = reopened.finish(sid, 1, True)
        self.assertEqual(result['status'], 'interrupted')
        self.assertIsNone(result['summary']['input_span_ms'])
        self.assertEqual(r.status(self.root, self.data)['reported_attempts'], 0)

    def test_out_of_order_and_future_messages_do_not_mutate_store(self):
        sid = self.start()
        for packet in [chunk(seq=1), chunk(raw((20000, 0, [0xf8]))), chunk(elapsed=True)]:
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                self.store.append(sid, packet)
        self.assertEqual(self.store.list()[0]['next_sequence'], 0)

    def test_recording_requires_finish_and_played_capture_cannot_be_cancelled(self):
        sid = self.start()
        report = {'task_id': self.task, 'result': {'raw_note': '테스트 노트'}}
        with self.assertRaises(ValueError):
            self.app.post('/api/report', report)
        self.store.append(sid, chunk(events=[{'type': 'play', 'at_ms': 0, 'bpm': 60}]))
        self.store.finish(sid, 1)
        with self.assertRaises(ValueError):
            self.app.post('/api/cancel', {'task_id': self.task, 'reason': '취소 테스트'})
        result = self.app.post('/api/report', report)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(result['feedback']['evidence'], 'self-report')

    def test_feedback_and_correction_preserve_raw_notes_and_original_recording(self):
        sid = self.start()
        self.store.finish(sid, 0)
        before = self.store.export(sid)
        note = '테스트 원문, "인용"\n<script>literal</script>'
        self.app.post('/api/report', {'task_id': self.task, 'result': {'raw_note': note}})
        result = {'raw_note': '정정 테스트', 'followed_target': True,
                  'checks': dict.fromkeys(r.CHECKS, True), 'clean_runs': 2, 'actual_minutes': 3}
        self.app.post('/api/report', {'task_id': self.task, 'result': result, 'correction': True})
        state = self.app.state()
        self.assertEqual(state['history'][0]['revisions'][0]['raw_note'], note)
        self.assertEqual(state['history'][0]['outcome'], 'success')
        self.assertEqual(state['status']['today']['reported_attempts'], 1)
        self.assertEqual(self.store.export(sid), before)

    def test_web_prerequisites_and_same_day_skip_use_existing_rules(self):
        self.app.post('/api/cancel', {'task_id': self.task, 'reason': '테스트: 오늘 보류'})
        self.assertEqual(self.app.state()['status']['next']['exercise_id'], 'E02')
        with self.assertRaises(ValueError):
            self.app.post('/api/assign', {'exercise_id': 'E03'})
        self.assertEqual(len(r.read_events(self.root)), 2)

    def test_playback_does_not_invalidate_compatible_legacy_success(self):
        legacy = copy.deepcopy(self.data)
        legacy.pop('playback')
        legacy_root = self.root / 'legacy'
        legacy_root.mkdir()
        task = r.assign(legacy_root, legacy, 'E01')['task_id']
        r.record_result(legacy_root, legacy, task, {'raw_note': '테스트', 'followed_target': True,
                        'checks': dict.fromkeys(r.CHECKS, True), 'clean_runs': 2})
        self.assertTrue(r.goal_successes(self.data, r.records(r.read_events(legacy_root)), 'E01', 'C', 60))

    def test_production_preview_is_rejected_before_writing(self):
        for root in [r.HERE.parent / 'practice', r.HERE.parent / 'practice' / 'reports']:
            with self.assertRaises(ValueError):
                Application(root, self.data)

    def test_installed_web_assets_are_hashed_and_stale_server_cannot_mutate(self):
        (self.root / 'AGENTS.md').write_text('temporary test workspace')
        (self.root / 'profile.json').write_text('{}')
        source, revision = git_fixture.copy_source(self.root)
        release = publish.publish(source, self.root)['installed']
        manifest = json.loads((Path(release) / 'manifest.json').read_text())
        for asset in ['sessions.py', 'webapp.html', 'webapp.js', 'audio.mjs', 'capture.mjs', 'i18n.mjs', 'translations.json']:
            self.assertIn(asset, manifest['sha256'])
        publish.runtime.activate(self.root, manifest)
        installed = Application(self.root, self.data, source=release)
        pin = publish.runtime.read_pin(self.root)
        pin['revision'] = '0' * 40
        (self.root / 'runtime.json').write_text(json.dumps(pin))
        before = (self.root / 'practice.csv').read_bytes()
        with self.assertRaises(ValueError):
            installed.post('/api/cancel', {'task_id': self.task, 'reason': 'stale tab'})
        self.assertEqual((self.root / 'practice.csv').read_bytes(), before)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = make_server(self.root, r.curriculum(), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            client.request(method, path, body, headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def test_load_is_read_only_and_static_paths_are_allowlisted(self):
        for path in ['/', '/webapp.js', '/audio.mjs', '/api/state', '/i18n.mjs', '/translations.json']:
            status, headers, body = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn('Content-Security-Policy', headers)
        self.assertFalse((self.root / 'practice.csv').exists())
        self.assertFalse((self.root / 'sessions.sqlite3').exists())
        self.assertEqual(self.request('GET', '/../practice.csv')[0], 404)

    def test_language_queries_localize_builtins_without_creating_evidence(self):
        for language in ['en', 'ko', 'invalid']:
            status, _, body = self.request('GET', '/api/state?lang=' + language)
            self.assertEqual(status, 200)
            state = json.loads(body)
            self.assertEqual(state['language'], 'ko' if language == 'ko' else 'en')
            if language == 'ko':
                self.assertRegex(state['exercises'][0]['title'], r'[가-힣]')
                self.assertRegex(state['status']['next']['reason'], r'[가-힣]')
            else:
                self.assertNotRegex(json.dumps(state['exercises'], ensure_ascii=False), r'[가-힣]')
        self.assertFalse((self.root / 'practice.csv').exists())
        self.assertFalse((self.root / 'sessions.sqlite3').exists())

    def test_origin_host_token_and_nonfinite_json_are_rejected(self):
        headers = {'Content-Type': 'application/json', 'X-Jazz-Token': self.server.app.token}
        body = json.dumps({'exercise_id': 'E01'})
        attempts = [headers | {'Origin': 'https://other.example'},
                    headers | {'Host': 'other.example'}, headers | {'X-Jazz-Token': ''}]
        for bad in attempts:
            status, _, response = self.request('POST', '/api/assign', body, bad)
            self.assertEqual(status, 400)
            self.assertNotRegex(json.loads(response)['error'], r'[가-힣]')
        self.assertEqual(self.request('POST', '/api/assign', '{"bpm":NaN}', headers)[0], 400)
        self.assertFalse((self.root / 'practice.csv').exists())
        self.assertEqual(self.request('POST', '/api/assign', body, headers)[0], 200)


if __name__ == '__main__':
    unittest.main()
