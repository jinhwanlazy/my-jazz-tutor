"""Synthetic MIDI only; no production data or model calls."""
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

import review as r
import publish
import git_fixture
from attempts import AttemptStore
from recommendation import context_for
from sessions import FRAME
from webapp import Application


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.data = r.curriculum()
        (self.root / 'profile.json').write_text('{"daily_minutes":30,"timezone":"UTC"}')
        self.app = Application(self.root, self.data)
        self.task = r.assign(self.root, self.data, 'E01')['task_id']

    def current(self, task=None):
        return next(t for t in self.app.state()['history'] if t['id'] == (task or self.task))

    def start(self, task=None, **values):
        return self.app.post('/api/attempts/start', {'task_id':task or self.task,
            'attempt_id':'A-'+uuid.uuid4().hex, 'bpm':self.current(task)['target']['bpm'], **values})

    def seal(self, started, wrong=False, interrupted=False, aborted=False, no_midi=False):
        contract=started['attempt']['contract']; sid=started['session']['id']; origin=1000
        notes=[]; beat=60000/contract['bpm']
        if not no_midi:
            for note in contract['expected']:
                pitch=note['pitch']+(1 if wrong else 0); at=origin+note['at']*beat
                notes += [(at,[0x90,pitch,95 if note['accent'] else 75]),
                          (at+note['duration']*beat*.95,[0x80,pitch,0])]
        blob=b''.join(FRAME.pack(at,0,len(data))+bytes(data) for at,data in sorted(notes))
        end=origin+contract['duration_ms']
        events=[{'type':'play','at_ms':origin,'bpm':contract['bpm']},
                {'type':'attempt_end','at_ms':end},{'type':'pause','at_ms':end}]
        if aborted: events.append({'type':'aborted','at_ms':end})
        self.app.store.append(sid, {'sequence':0,'midi':base64.b64encode(blob).decode(),
                                   'events':events,'elapsed_ms':end+beat})
        return self.app.post('/api/sessions/finish',{'session_id':sid,'expected_chunks':1,'interrupted':interrupted})

    def complete(self, **values):
        return self.app.post('/api/complete',{'task_id':self.task,
            'expected_event_id':self.current()['lifecycle_event_id'], **values})

    def test_multiple_active_tasks_and_global_recording_guard(self):
        second=r.assign(self.root,self.data,'E02')['task_id']
        self.assertEqual(sum(t['pending'] for t in self.app.state()['history']),2)
        self.assertEqual(self.app.state()['status']['next']['action'],'choose')
        started=self.start()
        with self.assertRaisesRegex(ValueError,'current recording'):self.start(second)
        with self.assertRaises(ValueError):self.app.store.start(second)
        self.seal(started);self.seal(self.start(second))
        self.assertEqual(len(self.app.attempts.list()),2)

    def test_success_gate_and_current_cycle_completion_are_atomic_and_idempotent(self):
        with self.assertRaisesRegex(ValueError,'successful'):self.complete()
        failed=self.seal(self.start(),wrong=True)['attempt']
        self.assertEqual(failed['result'],'needs_work');self.assertFalse(self.current()['assessment']['eligible'])
        with self.assertRaises(ValueError):self.complete(manual_confirmed=True)
        success=self.seal(self.start())['attempt'];self.assertTrue(success['qualified_pass'])
        original=json.loads(json.dumps(success)); raw=self.app.store.export(success['session_id'])
        event_id=self.current()['lifecycle_event_id']; saved=self.complete()
        self.assertEqual(self.app.post('/api/complete',{'task_id':self.task,'expected_event_id':event_id}),saved)
        self.assertTrue(self.current()['completed']);self.assertIsNone(self.current()['report'])
        self.assertEqual(self.app.attempts.details(success['id']),original)
        completion=r.read_events(self.root)[-1];self.assertEqual(completion['checks_json'],'{}')
        self.assertEqual(r.reflection_observations(completion)['attempt_completion']['basis'],'midi-analysis')
        reopened=self.app.post('/api/reopen',{'task_id':self.task,'expected_event_id':saved['event_id']})
        self.assertEqual(self.app.post('/api/reopen',{'task_id':self.task,'expected_event_id':saved['event_id']}),reopened)
        self.assertTrue(self.current()['pending']);self.assertFalse(self.current()['completed'])
        self.assertFalse(self.current()['assessment']['eligible'])
        with self.assertRaises(ValueError):self.complete()
        self.assertEqual(self.app.store.export(success['session_id']),raw)
        self.seal(self.start());self.complete()
        self.assertEqual(len(self.current()['completions']),2)
        self.assertEqual(self.app.state()['status']['reported_attempts'],2)
        self.assertEqual(self.app.state()['status']['today']['reported_attempts'],2)

    def test_new_analysis_saves_individual_notes_with_the_original_completion_rules(self):
        attempt=self.seal(self.start())['attempt']
        self.assertEqual(attempt['analysis_version'],'midi-analysis-2')
        self.assertEqual(len(attempt['analysis']['notes']),attempt['counts']['expected'])
        self.assertTrue(all(note['state']=='correct' for note in attempt['analysis']['notes']))
        self.assertEqual(attempt['analysis']['extra_notes'],[])
        self.assertTrue(self.current()['assessment']['eligible'])
        self.assertNotIn('analysis',self.current()['attempts'][0])
        self.complete()
        saved=r.reflection_observations(r.read_events(self.root)[-1])['attempt_completion']
        self.assertEqual(saved['analysis_version'],'midi-analysis-2')

    def test_older_analysis_is_never_rematched_on_save_retry_or_completion(self):
        attempt=self.seal(self.start())['attempt'];legacy=dict(attempt['analysis'])
        legacy['version']='midi-analysis-1'
        for field in ('notes','extra_notes','final'):legacy.pop(field,None)
        with self.app.attempts.database() as db:
            db.execute('UPDATE attempt_analyses SET version=?,result=? WHERE attempt_id=?',
                       ('midi-analysis-1',r.jdump(legacy),attempt['id']))
            before=tuple(db.execute('SELECT * FROM attempt_analyses WHERE attempt_id=?',(attempt['id'],)).fetchone())
        original=self.app.store.export(attempt['session_id'])
        with patch('attempts.js',side_effect=AssertionError('A saved analysis was recomputed')):
            retry=self.app.post('/api/sessions/finish',{'session_id':attempt['session_id'],'expected_chunks':1})
            self.assertEqual(retry['attempt']['analysis'],legacy)
            self.assertEqual(retry['attempt']['analysis_version'],'midi-analysis-1')
            self.complete()
        with self.app.attempts.database() as db:
            rows=db.execute('SELECT * FROM attempt_analyses WHERE attempt_id=?',(attempt['id'],)).fetchall()
            self.assertEqual([tuple(row) for row in rows],[before])
        self.assertEqual(self.app.store.export(attempt['session_id']),original)
        saved=r.reflection_observations(r.read_events(self.root)[-1])['attempt_completion']
        self.assertEqual(saved['analysis_version'],'midi-analysis-1')

    def test_manual_requires_full_uninterrupted_target_bpm_pass_and_explicit_confirmation(self):
        self.seal(self.start(manual=True,bpm=40),no_midi=True)
        self.assertFalse(self.current()['assessment']['manual_available'])
        self.seal(self.start(manual=True),interrupted=True,no_midi=True)
        self.assertFalse(self.current()['assessment']['manual_available'])
        result=self.seal(self.start(manual=True),no_midi=True)['attempt']
        self.assertFalse(result['qualified_pass']);self.assertEqual(result['result'],'unknown')
        self.assertTrue(self.current()['assessment']['manual_available'])
        with self.assertRaises(ValueError):self.complete()
        self.complete(manual_confirmed=True)
        measured=self.current()['observations'];self.assertEqual(measured['attempt_completion']['basis'],'user-confirmation')
        self.assertNotIn('actual_bpm',measured)

    def test_aborted_interrupted_and_analysis_failure_preserve_raw_and_never_unlock_completion(self):
        for values in ({'aborted':True},{'interrupted':True}):
            result=self.seal(self.start(),**values)['attempt']
            self.assertIn(result['state'],('aborted','interrupted'));self.assertFalse(result['qualified_pass'])
        started=self.start()
        with patch('attempts.js',side_effect=ValueError('synthetic analysis failure')):
            result=self.seal(started)['attempt']
        self.assertEqual(result['result'],'unknown');self.assertTrue(self.app.store.export(result['session_id'])[0].startswith(b'JPM1'))
        self.assertFalse(self.current()['assessment']['eligible']);self.assertEqual(len(self.app.attempts.list()),3)

    def test_attempt_identity_contract_and_sealed_analysis_cannot_be_overwritten(self):
        started=self.start(); aid=started['attempt']['id']; before=started['attempt']['contract']
        retry=self.app.post('/api/attempts/start',{'task_id':self.task,'attempt_id':aid,'bpm':before['bpm']})
        self.assertEqual(retry['session'],started['session'])
        with self.assertRaises(ValueError):self.app.attempts.start(self.task,aid,before['bpm'],True)
        result=self.seal(started)['attempt']
        self.assertEqual(self.app.attempts.finish_session(result['session_id']),result)
        self.assertEqual(self.app.attempts.details(aid)['contract'],before)
        self.assertEqual(len(before['target_hash']),64)
        with self.app.attempts.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempt_analyses').fetchone()[0],1)

    def test_additive_migration_and_legacy_completion_are_not_reanalyzed(self):
        sid=self.app.store.start(self.task)['id']
        self.app.store.append(sid,{'sequence':0,'midi':'','events':[{'type':'play','at_ms':0,'bpm':60}], 'elapsed_ms':1000})
        self.app.store.finish(sid,1)
        self.app.store.complete(self.data,self.task)
        before=(self.root/'practice.csv').read_bytes(); archive=self.app.store.export(sid)
        state=self.app.state();self.assertEqual(state['history'][0]['attempts'],[])
        self.assertTrue(state['history'][0]['completed']);self.assertEqual((self.root/'practice.csv').read_bytes(),before)
        self.assertEqual(self.app.store.export(sid),archive)
        with sqlite3.connect(self.root/'sessions.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_feedback_edit_after_reopen_does_not_lose_prior_timing_or_reclose_active_task(self):
        self.seal(self.start());self.complete()
        first=self.app.post('/api/reflection',{'task_id':self.task,'rating':'challenging','note':'Synthetic original note'})
        original=self.current()['report']; completed=self.current()['lifecycle_event_id']
        self.app.post('/api/reopen',{'task_id':self.task,'expected_event_id':completed})
        with self.assertRaises(ValueError):self.app.post('/api/reflection',{'task_id':self.task,'rating':'good','expected_event_id':first['event_id']})
        self.seal(self.start());self.complete()
        self.assertEqual(len(r.practice_records(r.records(r.read_events(self.root))[0])),2)
        latest=self.app.post('/api/reflection',{'task_id':self.task,'rating':'good','expected_event_id':first['event_id']})
        self.assertNotEqual(first['event_id'],latest['event_id'])
        self.assertEqual(self.current()['completions'][0]['actual_minutes'],original['actual_minutes'])
        self.assertEqual(self.app.state()['status']['reported_attempts'],2)

    def test_new_skips_need_reason_but_legacy_empty_skip_still_reads(self):
        with self.assertRaises(ValueError):self.app.post('/api/discard',{'task_id':self.task})
        r.discard(self.root,self.data,self.task,'Synthetic duplicate task','already_practiced')
        self.assertFalse(self.current()['completed']);self.assertEqual(self.app.state()['status']['reported_attempts'],0)
        event=r.read_events(self.root)[-1];event['reason']=r.jdump({'choice':'','note':''})
        self.assertTrue(r.records(r.read_events(self.root)[:-1]+[event])[0]['discarded'])

    def test_recent_attempt_context_is_bounded_citable_and_contains_no_midi(self):
        before=context_for(self.root,self.data)
        with self.app.attempts.database():pass
        self.assertEqual(before['fingerprint'],context_for(self.root,self.data)['fingerprint'])
        self.seal(self.start())
        after=context_for(self.root,self.data)
        self.assertNotEqual(before['fingerprint'],after['fingerprint'])
        from coaching_context import evidence_ids
        self.assertTrue(any(i.startswith('attempt:A-') for i in evidence_ids(after)))
        source=next(s for s in after['sources'] if s['id']=='attempts-summary')
        self.assertNotIn('messages',r.jdump(source));self.assertNotIn('matches',r.jdump(source))
        with patch.object(AttemptStore,'list',return_value=self.app.attempts.list()*100):
            summary=AttemptStore(self.root).context_summary()
        self.assertEqual(len(summary['recent']),5);self.assertEqual(summary['recorded_attempts'],100)

    def test_release_rejects_an_old_recording_reader_before_changing_the_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            source,revision=git_fixture.copy_source(Path(temp))
            root=Path(temp)/'practice';root.mkdir()
            (root/'AGENTS.md').write_text('Synthetic workspace');(root/'profile.json').write_text('{}')
            publish.publish(source,root,ref=revision)
            app=Application(root,self.data);task=r.assign(root,self.data,'E01')['task_id']
            sid=app.store.start(task)['id'];app.store.finish(sid,0);app.state()
            code=source/'sessions.py';code.write_text(code.read_text().replace('SUPPORTED_DATABASE_VERSIONS = (0, 1, 2)','SUPPORTED_DATABASE_VERSIONS = (0, 1)'))
            old_reader=git_fixture.commit(source)
            before={n:(root/n).read_bytes() for n in ('practice.csv','runtime.json','sessions.sqlite3')}
            with self.assertRaises(ValueError):publish.publish(source,root,ref=old_reader)
            self.assertEqual({n:(root/n).read_bytes() for n in before},before)

    def test_cli_uses_the_same_analysis_completion_gate_and_reopen_event(self):
        result=self.seal(self.start())['attempt']
        def run(*args):
            output=io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(r.main(['--practice-root',str(self.root),*args]),0)
            return json.loads(output.getvalue())
        detail=run('attempts','--attempt-id',result['id'])
        self.assertTrue(detail['qualified_pass'])
        saved=run('complete',self.task,'--expected-event-id',self.current()['lifecycle_event_id'])
        run('reopen',self.task,'--expected-event-id',saved['event_id'])
        self.assertTrue(self.current()['pending']);self.assertFalse(self.current()['assessment']['eligible'])

    def test_release_rejects_a_reader_that_cannot_preserve_saved_note_analyses(self):
        with tempfile.TemporaryDirectory() as temp:
            source,revision=git_fixture.copy_source(Path(temp))
            (self.root/'AGENTS.md').write_text('Synthetic workspace')
            publish.publish(source,self.root,ref=revision)
            self.seal(self.start())
            code=source/'attempts.py';original=code.read_text()
            code.write_text(original.replace("SUPPORTED_ANALYSIS_VERSIONS = ('midi-analysis-1', 'midi-analysis-2')", "SUPPORTED_ANALYSIS_VERSIONS = ('midi-analysis-1',)"))
            self.assertNotEqual(code.read_text(),original)
            old_reader=git_fixture.commit(source)
            before={name:(self.root/name).read_bytes() for name in ('practice.csv','runtime.json','active-version','sessions.sqlite3')}
            with self.assertRaises(ValueError):publish.publish(source,self.root,ref=old_reader)
            self.assertEqual({name:(self.root/name).read_bytes() for name in before},before)

    def test_legacy_feedback_correction_during_reopen_does_not_count_another_completion(self):
        self.seal(self.start());self.complete()
        first=self.app.store.reflect(self.data,self.task,'challenging','Synthetic original note')
        self.app.post('/api/reopen',{'task_id':self.task,'expected_event_id':self.current()['lifecycle_event_id']})
        self.app.store.reflect(self.data,self.task,'good','Synthetic correction',first['event_id'])
        self.assertTrue(self.current()['pending']);self.assertEqual(self.app.state()['status']['reported_attempts'],1)
        self.assertEqual(self.app.state()['status']['today']['reported_attempts'],1)
        self.seal(self.start());self.complete();self.assertEqual(self.app.state()['status']['reported_attempts'],2)


if __name__=='__main__': unittest.main()
