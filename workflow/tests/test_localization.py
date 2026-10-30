"""Translation provenance, cache, immutable conditions and async HTTP boundaries."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import localization as loc
import recommendation as rec
import review as r
from recommendation_fixture import result, SyntheticRunner, SyntheticTranslator
from test_webapp import chunk
from webapp import Application, make_server


class TranslationTests(unittest.TestCase):
    def test_korean_music_terms_may_use_digits_only_for_same_source_concept(self):
        self.assertFalse(loc.introduced_number('4분음표, 장3화음, 7음', 'quarter notes, major triads, sevenths', 'ko'))
        self.assertFalse(loc.introduced_number('8분쉼표와 4분 음표', 'eighth-note rests and quarter notes', 'ko'))
        self.assertFalse(loc.introduced_number('2분 쉼표', 'half-note rests', 'ko'))
        self.assertFalse(loc.introduced_number('[KEEP_0] BPM에서 4분음표', 'quarter notes at [KEEP_0] BPM', 'ko'))
        for text, source in [('8분음표', 'quarter notes'), ('7화음', 'major triads'),
                             ('99 BPM', 'quarter notes'), ('4마디', 'four bars'),
                             ('14분음표', 'quarter notes'), ('C7', 'seventh chords'),
                             ('8분쉼표', 'quarter-note rests'), ('8분쉼표', 'eighth notes'),
                             ('8분쉼표', 'quarter-note rests between eighth notes'),
                             ('18분쉼표', 'eighth-note rests')]:
            with self.subTest(text=text):self.assertTrue(loc.introduced_number(text,source,'ko'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = r.curriculum()
        (self.root/'profile.json').write_text('{"language":"ko","daily_minutes":20}')
        self.runner = SyntheticTranslator()
        self.app = Application(self.root, self.data, recommender=SyntheticRunner(), translator=self.runner)
        self.task_id = self.app.recommendations.start('R-'+'a'*32, 'ko', asynchronous=False)['task_id']
        self.target = r.records(r.read_events(self.root))[0]['target']
        self.before = (self.root/'practice.csv').read_bytes()

    def translate(self, **kwargs):
        return self.app.translations.start(self.task_id, 'ko', asynchronous=False, **kwargs)

    def test_written_counts_and_positions_are_protected_without_changing_original(self):
        candidate=result()
        candidate['exercise']['instructions']='Repeat two bars four times. Start on the third beat at seventy-two BPM.'
        target=rec.make_target(candidate,self.data,{'source_language':'en'})
        before=copy.deepcopy(target)
        context,tokens=loc.translation_input(target,'ko','en')
        field='exercise.instructions'
        self.assertEqual(list(tokens[field].values()),['2','4','3','72'])
        translated={'strings':dict(context['strings'])}
        translated['strings'][field]='[KEEP_0]마디를 [KEEP_1]회 반복하세요. [KEEP_3] BPM에서 [KEEP_2]번째 박에 시작하세요.'
        display=loc.translated_target(target,'ko','en',translated)
        self.assertEqual(display['instructions'],'2마디를 4회 반복하세요. 72 BPM에서 3번째 박에 시작하세요.')
        self.assertEqual(target,before)
        translated['strings'][field]=translated['strings'][field].replace('[KEEP_3]','80')
        with self.assertRaises(loc.TranslationValidationError):loc.translated_target(target,'ko','en',translated)
        self.assertEqual(loc.numeric_conditions('thirds and sevenths; four quarter-note beats'),
                         'thirds and sevenths; 4 quarter-note beats')

    def test_valid_legacy_cache_is_read_with_original_tokenization_without_model_calls(self):
        context,_=loc.translation_input(self.target,'ko','en',protocol=1)
        translated={'strings':{k:'번역: '+v for k,v in context['strings'].items()}}
        manager=self.app.translations; manager.directory.mkdir()
        job=manager.identity(self.target,'ko') | {'state':'completed','result':translated}
        manager._write(job)
        before=manager._path(job).read_bytes()
        view,state=manager.view(self.target,'ko')
        self.assertEqual(state['state'],'completed')
        self.assertTrue(view['title'].startswith('번역: '))
        self.assertEqual(manager._path(job).read_bytes(),before)
        self.assertEqual(self.runner.calls,0)
        self.assertEqual(view['exercise']['notation'],self.target['exercise']['notation'])

    def test_invalid_field_gets_one_targeted_repair_and_preserves_valid_fields(self):
        contexts=[]
        def translate(context,schema):
            contexts.append(copy.deepcopy(context))
            translated={'strings':{k:'번역: '+v for k,v in context['strings'].items()}}
            if len(contexts)==1:
                translated['strings']['exercise.instructions']+=' 99 BPM'
            return translated,{'provider':'synthetic-repair','usage':{'input_tokens':10}}
        with patch.object(self.runner,'translate',side_effect=translate):
            self.assertEqual(self.translate()['state'],'completed')
        self.assertEqual(len(contexts),2)
        self.assertEqual(set(contexts[1]['strings']),{'exercise.instructions'})
        self.assertEqual(set(contexts[1]['protected_values']),{'exercise.instructions'})
        self.assertEqual(contexts[1]['repair'],[{'field':'exercise.instructions','code':'unexpected_number'}])
        job=json.loads(self.app.translations._path(self.app.translations.identity(self.target,'ko')).read_text())
        self.assertEqual(job['protocol'],2)
        self.assertEqual(len(job['attempts']),2)
        self.assertEqual(job['result']['strings']['exercise.title'],job['attempts'][0]['result']['strings']['exercise.title'])
        self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)

    def test_missing_placeholder_is_repaired_but_repeated_failure_is_bounded_and_diagnosable(self):
        def broken(context,schema):
            translated={'strings':dict(context['strings'])}
            translated['strings']['exercise.notes']=translated['strings']['exercise.notes'].replace('[KEEP_0]','')
            return translated,{'provider':'synthetic-invalid'}
        with patch.object(self.runner,'translate',side_effect=broken) as run:
            self.assertEqual(self.translate()['error_code'],'invalid_output')
            self.assertEqual(run.call_count,2)
            self.app.state('ko');self.translate()
            self.assertEqual(run.call_count,2)
        job=json.loads(self.app.translations._path(self.app.translations.identity(self.target,'ko')).read_text())
        self.assertEqual(job['validation_issues'],[{'field':'exercise.notes','code':'protected_value_mismatch'}])
        self.assertEqual(len(job['attempts']),2)
        self.assertIn('result',job['attempts'][0])
        self.assertIn('result',job['attempts'][1])
        self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)

    def test_repair_auth_error_does_not_retry_again_or_publish_partial_translation(self):
        def translate(context,schema):
            if 'repair' in context:raise rec.RecommendationError('auth')
            return {'strings':{k:v+' 999' for k,v in context['strings'].items()}},{}
        with patch.object(self.runner,'translate',side_effect=translate) as run:
            self.assertEqual(self.translate()['error_code'],'auth')
            self.assertEqual(run.call_count,2)
        view,state=self.app.translations.view(self.target,'ko')
        self.assertEqual(view,self.target)
        self.assertEqual(state['state'],'failed')

    def test_invalid_provider_response_is_saved_privately_without_exposing_it_in_state(self):
        error=rec.RecommendationError('invalid_output');error.invalid_result={'unexpected':'synthetic rejected output'}
        with patch.object(self.runner,'translate',side_effect=error) as run:
            self.assertEqual(self.translate()['error_code'],'invalid_output')
            self.assertEqual(run.call_count,1)
        job=json.loads(self.app.translations._path(self.app.translations.identity(self.target,'ko')).read_text())
        self.assertEqual(job['attempts'][0]['result'],error.invalid_result)
        self.assertNotIn('synthetic rejected output',json.dumps(self.app.state('ko')))

    def test_malformed_output_repair_cannot_raise_an_unrelated_connection_error(self):
        with patch.object(self.runner,'translate',return_value=({'strings':[]},{})) as run:
            self.assertEqual(self.translate()['error_code'],'invalid_output')
            self.assertEqual(run.call_count,2)

    def test_english_source_is_independent_of_display_language_and_retries(self):
        context = rec.context_for(self.root, self.data, 'ko')
        self.assertEqual(context['language'], 'en')
        self.assertEqual(context['display_language'], 'ko')
        self.assertEqual(self.target['generation']['source_language'], 'en')
        self.assertEqual(self.target['title'], result()['exercise']['title'])
        # A UI language switch cannot turn a response-loss retry into a new request.
        self.assertEqual(self.app.recommendations.start('R-'+'a'*32, 'en')['task_id'], self.task_id)
        bad = result(); bad['exercise']['instructions'] = '영어로 먼저 생성되어야 하는 과제'
        with self.assertRaises(ValueError): rec.validate_result(bad, context)
        self.assertEqual((self.root/'practice.csv').read_bytes(), self.before)

    def test_state_reads_do_not_generate_and_cache_preserves_music_evidence_and_notes(self):
        state = self.app.state('ko')
        self.assertEqual(state['history'][0]['target']['translation']['state'], 'missing')
        self.assertFalse((self.root/'.translations').exists())
        self.assertEqual(self.runner.calls, 0)
        sid = self.app.store.start(self.task_id)['id']
        self.app.store.append(sid, chunk(events=[{'type':'play','at_ms':0,'bpm':72},{'type':'pause','at_ms':5000}]))
        self.app.store.finish(sid,1); self.app.store.complete(self.data,self.task_id)
        self.app.store.reflect(self.data,self.task_id,'good','Synthetic original note / 원문')
        before = (self.root/'practice.csv').read_bytes(); archive = self.app.store.export(sid)
        self.assertEqual(self.translate()['state'], 'completed')
        display = self.app.state('ko')['history'][0]
        self.assertTrue(display['target']['title'].startswith('번역: '))
        self.assertTrue(display['target']['analysis']['evidence'][0]['interpretation'].startswith('번역: '))
        self.assertEqual(display['report']['raw_note'], 'Synthetic original note / 원문')
        for field in ('key','bpm','bars','minutes','notation','accompaniment'):
            self.assertEqual(display['target']['exercise'][field], self.target['exercise'][field])
        self.assertEqual(display['target']['analysis']['evidence'][0]['source_ids'], ['profile'])
        self.assertEqual(display['target']['analysis']['evidence'][0]['confidence'], 'low')
        self.assertIn('F#4+A4', display['target']['exercise']['right_hand'])
        self.assertEqual((self.root/'practice.csv').read_bytes(), before)
        self.assertEqual(self.app.store.export(sid), archive)
        fresh = loc.Translations(self.root, self.runner)
        self.assertEqual(fresh.view(self.target,'en')[0], self.target)
        self.assertEqual(fresh.view(self.target,'ko')[1]['state'], 'completed')
        repeated = rec.repeat(self.root,self.data,self.task_id,'T-'+'b'*10)
        self.assertEqual(fresh.start(repeated['task_id'],'ko',asynchronous=False)['state'], 'completed')
        self.assertEqual(self.runner.calls,1)

    def test_model_cannot_change_notes_numbers_ids_or_shape(self):
        context, _ = loc.translation_input(self.target, 'ko', 'en')
        good, _ = self.runner.translate(context, loc.output_schema(context))
        cases = []
        bad=copy.deepcopy(good);bad['strings']['exercise.notes']=bad['strings']['exercise.notes'].replace('[KEEP_0]','[KEEP_99]');cases.append(bad)
        bad=copy.deepcopy(good);bad['strings']['exercise.instructions']+=' Use 99 BPM.';cases.append(bad)
        bad=copy.deepcopy(good);bad['bpm']=99;cases.append(bad)
        bad=copy.deepcopy(good);bad['strings']['exercise.bpm']='99';cases.append(bad)
        bad=copy.deepcopy(good);bad['strings'].pop('exercise.objective');cases.append(bad)
        bad=copy.deepcopy(good);bad['strings']['exercise.title']='';cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), patch.object(self.runner,'translate',return_value=(bad,{})):
                self.assertEqual(self.translate(retry=True)['error_code'],'invalid_output')
                self.assertEqual(self.app.state('ko')['history'][0]['target']['title'],self.target['title'])
                self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)

    def test_protected_values_may_reorder_but_never_disappear_or_duplicate(self):
        context, _ = loc.translation_input(self.target,'ko','en')
        translated, _ = self.runner.translate(context,loc.output_schema(context))
        field='exercise.left_hand'
        tokens=loc.TOKEN.findall(translated['strings'][field])
        translated['strings'][field]='왼손 '+', '.join(reversed(tokens))
        self.assertIn('D3',loc.translated_target(self.target,'ko','en',translated)['exercise']['left_hand'])
        translated['strings'][field]+=' '+tokens[0]
        with self.assertRaises(ValueError): loc.translated_target(self.target,'ko','en',translated)

    def test_failure_requires_explicit_retry_and_uses_translation_error_text(self):
        for code in ('auth','quota','timeout','connection','invalid_output'):
            with patch.object(self.runner,'translate',side_effect=rec.RecommendationError(code)) as run:
                self.assertEqual(self.translate(retry=True)['error_code'],code)
                self.translate();self.app.state('ko')
                self.assertEqual(run.call_count,1)
            self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)
        self.assertNotIn('No practice was added',loc.ERRORS['timeout'])
        self.assertEqual(self.translate(retry=True)['state'],'completed')

    def test_single_worker_across_instances_and_stale_runtime(self):
        started, release = threading.Event(), threading.Event()
        translate = self.runner.translate
        def delayed(context,schema):
            started.set();release.wait(5);return translate(context,schema)
        other=loc.Translations(self.root,self.runner)
        with patch.object(self.runner,'translate',side_effect=delayed):
            job=self.app.translations.start(self.task_id,'ko')
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(other.start(self.task_id,'ko')['id'],job['id'])
                self.assertEqual(other.view(self.target,'ko')[1]['state'],'running')
            finally: release.set()
            for _ in range(100):
                if other.view(self.target,'ko')[1]['state']!='running':break
                threading.Event().wait(.02)
        self.assertEqual(self.runner.calls,1)
        self.assertEqual(other.view(self.target,'ko')[1]['state'],'completed')
        other._path(other.identity(self.target,'ko')).unlink()
        with patch.object(rec,'assert_active',side_effect=[None,rec.RecommendationError('stale')]):
            self.assertEqual(self.translate()['error_code'],'stale')
        self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)

    def test_restart_and_corrupt_cache_leave_original_available(self):
        manager=self.app.translations; identity=manager.identity(self.target,'ko')
        manager.directory.mkdir()
        manager._write(identity | {'state':'running'})
        self.assertEqual(loc.Translations(self.root).view(self.target,'ko')[1]['error_code'],'interrupted')
        self.assertEqual(self.translate(retry=True)['state'],'completed')
        job=json.loads(manager._path(identity).read_text())
        job['result']['strings']['exercise.notes']='Changed C9 at 999 BPM'
        manager._write(job)
        display,state=manager.view(self.target,'ko')
        self.assertEqual(display,self.target)
        self.assertEqual(state['error_code'],'invalid_output')
        self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)

    def test_old_language_is_read_from_original_job_without_rewriting_snapshot(self):
        old=copy.deepcopy(self.target);old['generation'].pop('source_language')
        path=self.root/old['generation']['context_file']
        job=json.loads(path.read_text());job['context']['language']='ko';path.write_text(json.dumps(job))
        self.assertEqual(self.app.translations.view(old,'ko')[1]['state'],'original')
        self.assertEqual(self.app.translations.view(old,'en')[1]['state'],'missing')
        self.assertNotIn('source_language',old['generation'])
        path.unlink()
        self.assertIsNone(self.app.translations.view(old,'en')[1]['source_language'])

    def test_translation_snapshot_cache_does_not_follow_different_conditions(self):
        self.translate()
        changed=copy.deepcopy(self.target);changed['exercise']['instructions']='A different synthetic exercise.'
        changed=rec.make_target(loc.original_result(changed),self.data,changed['generation'],changed['exercise_id'])
        self.assertEqual(self.app.translations.view(changed,'ko')[1]['state'],'missing')
        self.assertEqual(self.runner.calls,1)

    def test_http_translation_requires_token_and_does_not_write_practice_records(self):
        server=make_server(self.root,self.data,0,translator=self.runner)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,headers=None,body=None):
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            try:
                client.request(method,path,body,headers or {})
                response=client.getresponse();return response.status,json.loads(response.read())
            finally:client.close()
        try:
            code,state=request('GET','/api/state?lang=ko')
            self.assertEqual(code,200);self.assertEqual(self.runner.calls,0)
            payload=json.dumps({'task_id':self.task_id})
            self.assertEqual(request('POST','/api/translate?lang=ko',{'Content-Type':'application/json'},payload)[0],400)
            headers={'Content-Type':'application/json','X-Jazz-Token':state['csrf_token']}
            self.assertEqual(request('POST','/api/translate?lang=ko',headers,payload)[0],200)
            for _ in range(100):
                state=request('GET','/api/state?lang=ko')[1]
                if state['history'][0]['target']['translation']['state']=='completed':break
                threading.Event().wait(.02)
            self.assertEqual(state['history'][0]['target']['translation']['state'],'completed')
            self.assertEqual(self.runner.calls,1)
            self.assertEqual((self.root/'practice.csv').read_bytes(),self.before)
        finally:server.shutdown();server.server_close();thread.join()
