"""Local tombstones and recording provenance; all evidence is synthetic/temporary."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import git_fixture
import publish
import review as r
from recommendation import context_for, repeat
from test_webapp import chunk, raw
from webapp import Application


class PracticeRemovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.root = self.directory / 'practice'; self.root.mkdir()
        (self.root/'profile.json').write_text('{"daily_minutes":30}')
        (self.root/'AGENTS.md').write_text('Synthetic practice workspace')
        self.data = r.curriculum(); self.app = Application(self.root, self.data)

    def assign(self, release=None):
        tid = 'T-'+uuid.uuid4().hex[:10]
        event = r.new_event('assigned', tid, self.data, 'E01')
        event['target_json'] = r.jdump(r.target_for(self.data, 'E01', 'C', 60))
        if release: event['release'] = release
        r.append_event(self.root, event)
        return tid

    def entry(self, tid):
        return next(t for t in self.app.state()['history'] if t['id'] == tid)

    def legacy(self, tid):
        sid = self.app.store.start(tid)['id']
        self.app.store.append(sid, chunk(raw((100, 0, [0x90,60,80]),(1100,0,[0x80,60,0])),
                                          [{'type':'play','at_ms':0,'bpm':60}]))
        self.app.store.finish(sid, 1); self.app.store.complete(self.data, tid)
        self.app.store.reflect(self.data, tid, 'challenging', 'Synthetic legacy memo')
        return sid

    def finite(self, tid):
        take = self.app.attempts.start(tid, 'A-'+uuid.uuid4().hex, 60, True)
        sid = take['session']['id']; end = take['attempt']['contract']['duration_ms']
        self.app.store.append(sid, {'sequence':0,'midi':base64.b64encode(b'').decode(),
            'events':[{'type':'play','at_ms':0,'bpm':60},{'type':'attempt_end','at_ms':end}], 'elapsed_ms':end+1000})
        self.app.post('/api/sessions/finish', {'session_id':sid,'expected_chunks':1})
        self.app.attempts.complete(self.data,tid,self.entry(tid)['lifecycle_event_id'],True)
        return sid

    def remove(self, tid, expected=None):
        return self.app.post('/api/delete', {'task_id':tid,
            'expected_event_id':expected or self.entry(tid)['revision_event_id']})

    def test_delete_excludes_task_and_attempt_evidence_but_preserves_originals(self):
        tid = self.assign(); sid = self.finite(tid)
        self.app.store.reflect(self.data,tid,'good','Synthetic removed memo, never send again')
        before = (self.root/'practice.csv').read_bytes(); archive = self.app.store.export(sid)
        analysis = self.app.attempts.list(tid); context = context_for(self.root,self.data)
        token = self.entry(tid)['revision_event_id']; result = self.remove(tid,token)
        self.assertEqual(self.remove(tid,token),result)
        self.assertTrue((self.root/'practice.csv').read_bytes().startswith(before))
        self.assertEqual(self.app.store.export(sid),archive)
        self.assertEqual(self.app.attempts.list(tid),analysis)
        self.assertEqual(self.app.state()['history'],[]);self.assertEqual(self.app.state()['sessions'],[])
        self.assertEqual(self.app.state()['status']['reported_attempts'],0)
        fresh = context_for(self.root,self.data)
        self.assertNotEqual(fresh['fingerprint'],context['fingerprint'])
        self.assertNotIn(tid,json.dumps(fresh)); self.assertNotIn('Synthetic removed memo',json.dumps(fresh))
        self.assertFalse(any(s['id']=='attempts-summary' for s in fresh['sources']))
        tombstone = r.records(r.read_events(self.root))[0]
        self.assertTrue(tombstone['deleted']);self.assertFalse(tombstone['cancelled'])
        for action in (lambda:self.app.store.start(tid),lambda:r.reopen(self.root,self.data,tid,result['event_id']),
                       lambda:self.app.store.reflect(self.data,tid,'good','Changed'),
                       lambda:repeat(self.root,self.data,tid,'T-123456789a')):
            with self.assertRaises(ValueError):action()

    def test_delete_rejects_stale_feedback_revision_and_open_capture(self):
        tid = self.assign(); sid = self.legacy(tid);token = self.entry(tid)['revision_event_id']
        previous = self.entry(tid)['report']['event_id']
        self.app.store.reflect(self.data,tid,'too_easy','Synthetic corrected note',previous)
        before = (self.root/'practice.csv').read_bytes()
        with self.assertRaisesRegex(ValueError,'changed'):self.remove(tid,token)
        self.assertEqual((self.root/'practice.csv').read_bytes(),before)
        self.remove(tid)
        other = self.assign();open_sid = self.app.store.start(other)['id']
        with self.assertRaisesRegex(ValueError,'Finish'):self.remove(other)
        self.assertTrue(self.entry(other)['pending']);self.app.store.finish(open_sid,0,True)
        self.remove(other);self.assertEqual(self.app.state()['history'],[])

    def test_skipped_and_unstarted_items_can_be_removed_without_a_practice_result(self):
        for skipped in (False,True):
            tid = self.assign()
            if skipped:r.discard(self.root,self.data,tid,'Synthetic skip')
            self.remove(tid)
            task = next(t for t in r.records(r.read_events(self.root)) if t['assignment']['task_id']==tid)
            self.assertIsNone(r.practice_record(task));self.assertFalse(r.is_pending(task))

    def test_legacy_unknown_counts_are_shared_by_web_and_coaching_context(self):
        old = self.assign('0.6.9');sid = self.legacy(old)
        current = self.assign();modern = self.assign();self.finite(modern)
        old_view = self.entry(old)['recording_coverage']
        self.assertEqual(old_view['mode'],'legacy');self.assertIsNone(old_view['recorded_attempts'])
        self.assertEqual(old_view['legacy_session_count'],1)
        self.assertEqual(self.entry(current)['recording_coverage']['recorded_attempts'],0)
        context = context_for(self.root,self.data)
        source = next(s for s in context['sources'] if s['id']=='task:'+old)
        self.assertEqual(source['data']['recording_coverage'],old_view)
        self.assertEqual(source['data']['state'],'completed')
        self.assertIn('Synthetic legacy memo',json.dumps(context))
        self.assertTrue(any(s['id']=='session:'+sid for s in context['sources']))
        self.assertEqual(self.entry(modern)['recording_coverage']['mode'],'finite_attempts')
        r.reopen(self.root,self.data,old,self.entry(old)['lifecycle_event_id']);self.finite(old)
        mixed = self.entry(old)['recording_coverage']
        self.assertEqual(mixed['mode'],'mixed');self.assertEqual(mixed['recorded_attempts'],1)

    def test_release_that_cannot_read_tombstones_cannot_replace_active_pin(self):
        (self.directory/'releases').mkdir()
        source,revision = git_fixture.copy_source(self.directory/'releases')
        publish.publish(source,self.root,ref=revision)
        tid = self.assign();self.remove(tid)
        pin = (self.root/'runtime.json').read_bytes();ledger = (self.root/'practice.csv').read_bytes()
        path = source/'review.py'
        path.write_text(path.read_text().replace('def records(events):\n',
            "def records(events):\n    if any(e['event_type']=='deleted' for e in events): raise ValueError('Unsupported deleted event')\n"))
        unsupported = git_fixture.commit(source)
        with self.assertRaisesRegex(ValueError,'선택한 런타임'):
            publish.publish(source,self.root,ref=unsupported)
        self.assertEqual((self.root/'runtime.json').read_bytes(),pin)
        self.assertEqual((self.root/'practice.csv').read_bytes(),ledger)
