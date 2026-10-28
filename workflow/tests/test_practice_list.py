"""Temporary evidence only: task completion, feedback, reminders and optional skips."""
import copy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import git_fixture
import publish
import review as r
from test_webapp import chunk, raw
from webapp import Application


class PracticeListTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = r.curriculum()
        self.app = Application(self.root, self.data)

    def assign(self, exercise="E01", **values):
        return self.app.post('/api/assign', {'exercise_id': exercise, **values})['task_id']

    def play(self, task, interrupted=False):
        sid = self.app.store.start(task)['id']
        self.app.store.append(sid, chunk(raw((1000, 0, [0x90, 60, 80]), (7000, 0, [0x80, 60, 0])),
                                        [{'type': 'play', 'at_ms': 0, 'bpm': 75}]))
        self.app.store.finish(sid, 1, interrupted)
        return sid

    def complete(self, task):
        return self.app.post('/api/complete', {'task_id': task})

    def tasks(self):
        return r.records(r.read_events(self.root))

    def test_creating_and_reading_do_not_start_or_complete_practice(self):
        task = self.assign(task_id='T-123456789a')
        self.assertEqual(self.assign(task_id=task), task)
        self.assertEqual(len(r.read_events(self.root)), 1)
        with self.assertRaises(ValueError):
            self.assign('E02', task_id=task)
        entry = self.app.state()['history'][0]
        self.assertTrue(entry['pending'])
        self.assertFalse(entry['started'])
        self.assertFalse(entry['completed'])
        self.assertEqual(self.app.store.list(), [])
        self.assertEqual(self.app.state()['status']['reported_attempts'], 0)
        with self.assertRaises(ValueError):
            self.complete(task)

    def test_completion_releases_task_without_feedback_and_counts_time_once(self):
        task = self.assign()
        sid = self.play(task)
        archive = self.app.store.export(sid)
        saved = self.complete(task)
        self.assertEqual(self.complete(task), saved)
        entry = self.app.state()['history'][0]
        self.assertTrue(entry['completed'])
        self.assertIsNone(entry['report'])
        self.assertFalse(entry['pending'])
        self.assertEqual(r.outcome(self.tasks()[0]), 'unknown')
        self.assertEqual(entry['completion']['checks_json'], '{}')
        self.assertEqual(entry['completion']['clean_runs'], '')
        self.assertEqual(self.app.state()['status']['reported_attempts'], 1)
        self.assertAlmostEqual(self.app.state()['status']['known_minutes'], .1)
        self.assertEqual(len(r.read_events(self.root)), 2)
        with self.assertRaises(ValueError):
            self.app.store.start(task)
        for operation in (lambda: r.discard(self.root, self.data, task), lambda: r.cancel(self.root, self.data, task, 'Synthetic reason')):
            with self.assertRaises(ValueError):
                operation()
        next_task = self.assign('E02')
        report = self.app.post('/api/reflection', {'task_id': task, 'rating': 'good'})
        self.app.post('/api/reflection', {'task_id': task, 'rating': 'too_easy', 'note': 'Synthetic later memo', 'expected_event_id': report['event_id']})
        latest = self.tasks()[0]['report']
        for field in ('practice_date', 'reason', 'actual_minutes', 'actual_json', 'checks_json', 'release'):
            self.assertEqual(latest[field], entry['completion'][field])
        self.assertEqual(self.app.store.export(sid), archive)
        self.assertEqual(self.app.state()['status']['reported_attempts'], 1)
        self.assertAlmostEqual(self.app.state()['status']['known_minutes'], .1)
        self.assertEqual(self.app.state()['status']['next']['task_id'], next_task)

    def test_open_recordings_must_be_saved_before_completion_or_discard(self):
        task = self.assign()
        sid = self.app.store.start(task)['id']
        for operation in (lambda: self.complete(task), lambda: r.discard(self.root, self.data, task)):
            with self.assertRaisesRegex(ValueError, 'Finish'):
                operation()
        self.app.store.append(sid, chunk(raw((1000, 0, [0x90, 60, 80])), [{'type': 'play', 'at_ms': 0, 'bpm': 60}]))
        self.app.store.finish(sid, 1, True)
        self.complete(task)
        self.assertEqual(self.tasks()[0]['completion']['actual_minutes'], '')
        self.assertEqual(self.app.state()['status']['minutes_unknown'], 1)

    def test_discard_is_optional_and_preserves_input_without_counting_a_result(self):
        task = self.assign()
        sid = self.play(task)
        archive = self.app.store.export(sid)
        result = self.app.post('/api/discard', {'task_id': task})
        self.assertEqual(result, self.app.post('/api/discard', {'task_id': task}))
        entry = self.app.state()['history'][0]
        self.assertTrue(entry['discarded'])
        self.assertEqual(entry['reason'], '')
        self.assertFalse(entry['completed'])
        self.assertEqual(self.app.state()['status']['reported_attempts'], 0)
        self.assertEqual(self.app.store.export(sid), archive)
        self.assertNotEqual(self.app.state()['status']['next'].get('exercise_id'), 'E01')
        self.assertFalse(r.practice_ready(self.data, self.tasks(), 'E01', 'C'))
        self.assertEqual(r.suggestion(self.data, self.tasks(), date.today()+timedelta(days=1))['exercise_id'], 'E01')
        with self.assertRaises(ValueError):
            self.app.post('/api/discard', {'task_id': task, 'reason': 'Changed reason'})
        with self.assertRaises(ValueError):
            self.app.post('/api/reflection', {'task_id': task, 'rating': 'good'})

    def test_familiarity_choice_opens_practice_but_never_passes_a_goal(self):
        note = 'Synthetic reason, "quoted"\n원문'
        first = self.assign()
        self.app.post('/api/discard', {'task_id': first, 'choice': 'already_practiced', 'reason': note})
        self.app.post('/api/discard', {'task_id': self.assign('E02'), 'choice': 'too_easy'})
        self.assertEqual(self.app.state()['status']['next']['exercise_id'], 'E03')
        self.assertEqual(r.discard_details(self.tasks()[0])['note'], note)
        self.assertTrue(r.practice_ready(self.data, self.tasks(), 'E01', 'C'))
        self.assertFalse(r.practice_ready(self.data, self.tasks(), 'E01', 'F'))
        self.assertTrue(all(g['state'] == 'unknown' for g in self.app.state()['status']['goals']))
        with self.assertRaises(ValueError):
            r.assign(self.root, self.data, 'E03', purpose='review')
        incompatible = copy.deepcopy(self.data)
        incompatible['exercises'][0]['instructions'] += ' Changed assignment.'
        self.assertFalse(r.practice_ready(incompatible, self.tasks(), 'E01', 'C'))
        self.assign('E03')

    def test_invalid_discard_fields_never_write_an_event(self):
        task = self.assign()
        for payload in ({'choice': 'guessed'}, {'reason': None}, {'choice': []}, {'actual_minutes': 10}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.app.post('/api/discard', {'task_id': task, **payload})
        self.assertEqual(len(r.read_events(self.root)), 1)

    def old_success(self):
        old = date.today()-timedelta(days=5)
        original = r.new_event
        def dated(*args, **kwargs):
            return original(*args, **kwargs) | {'recorded_at': datetime.combine(old, datetime.min.time(), timezone.utc).isoformat()}
        with patch.object(r, 'new_event', side_effect=dated):
            task = self.assign()
            r.record_result(self.root, self.data, task, {'raw_note': 'Synthetic legacy success', 'practice_date': old.isoformat(),
                'followed_target': True, 'checks': dict.fromkeys(r.CHECKS, True), 'clean_runs': 2})

    def test_completed_review_and_too_easy_feedback_stop_the_repeat_loop(self):
        self.old_success()
        self.assertEqual(self.app.state()['status']['next']['action'], 'review')
        task = self.assign()
        self.play(task)
        self.complete(task)
        self.assertNotEqual(self.app.state()['status']['next']['action'], 'review')
        self.app.post('/api/reflection', {'task_id': task, 'rating': 'too_easy'})
        self.assertEqual(self.app.state()['status']['next']['exercise_id'], 'E02')
        self.assertEqual(len(r.goal_successes(self.data, self.tasks(), 'E01', 'C', 60)), 1)
        self.assertFalse(r.retained(r.goal_successes(self.data, self.tasks(), 'E01', 'C', 60), 2))
        tomorrow = r.suggestion(self.data, self.tasks(), date.today()+timedelta(days=1))
        self.assertEqual(tomorrow['exercise_id'], 'E02')
        later = r.suggestion(self.data, self.tasks(), date.today()+timedelta(days=self.data['retention_days']))
        self.assertEqual(later['action'], 'review')

    def test_unrelated_key_does_not_satisfy_due_review(self):
        self.old_success()
        task = self.assign(key='F')
        self.play(task)
        self.complete(task)
        self.assertEqual(self.app.state()['status']['next']['action'], 'review')
        self.assertEqual(self.app.state()['status']['next']['key'], 'C')


class ListReleaseTests(unittest.TestCase):
    def test_incompatible_reader_cannot_replace_active_release_after_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source, current = git_fixture.copy_source(base)
            code = source/'review.py'
            code.write_text(code.read_text().replace('elif kind in ("reported", "corrected", "completed"):',
                                                     'elif kind in ("reported", "corrected"):'))
            older = git_fixture.commit(source)
            root = base/'practice'; root.mkdir()
            (root/'AGENTS.md').write_text('Synthetic workspace')
            (root/'profile.json').write_text('{}')
            publish.publish(source, root, ref=current)
            data = r.curriculum()
            app = Application(root, data)
            task = r.assign(root, data, 'E01')['task_id']
            sid = app.store.start(task)['id']
            app.store.append(sid, chunk(events=[{'type':'play','at_ms':0,'bpm':60}]))
            app.store.finish(sid, 1)
            app.store.complete(data, task)
            before = {name: (root/name).read_bytes() for name in ('practice.csv', 'runtime.json')}
            with self.assertRaises(ValueError):
                publish.publish(source, root, ref=older)
            for name, content in before.items():
                self.assertEqual((root/name).read_bytes(), content)

    def test_completion_and_discard_survive_upgrade_without_retirement_or_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source, revision = git_fixture.copy_source(base)
            root = base/'practice'; root.mkdir()
            (root/'AGENTS.md').write_text('Synthetic workspace')
            (root/'profile.json').write_text('{}')
            publish.publish(source, root, ref=revision)
            data = r.curriculum(source/'curriculum.yaml')
            app = Application(root, data)
            task = r.assign(root, data, 'E01')['task_id']
            sid = app.store.start(task)['id']
            app.store.append(sid, chunk(events=[{'type':'play','at_ms':0,'bpm':60}]))
            app.store.finish(sid, 1)
            app.store.complete(data, task)
            r.discard(root, data, r.assign(root, data, 'E02')['task_id'])
            before = (root/'practice.csv').read_bytes()
            after_version = '9.9.9'
            new_revision = git_fixture.bump(source, data['version'], after_version)
            new_data = r.curriculum(source/'curriculum.yaml')
            new_data['exercises'][0]['instructions'] += ' Changed exercise.'
            (source/'curriculum.yaml').write_text(r.yaml.safe_dump(new_data, allow_unicode=True))
            new_revision = git_fixture.commit(source)
            published = publish.publish(source, root, ref=new_revision)
            self.assertEqual(published['retired_tasks'], [])
            self.assertEqual(published['carried_tasks'], [])
            self.assertEqual((root/'practice.csv').read_bytes(), before)
            app.store.reflect(new_data, task, 'good')
            record = r.records(r.read_events(root))[0]
            self.assertEqual(record['report']['release'], data['version'])
            self.assertEqual(record['target']['instructions'], data['exercises'][0]['instructions'])
            self.assertEqual(r.outcome(record), 'unknown')
