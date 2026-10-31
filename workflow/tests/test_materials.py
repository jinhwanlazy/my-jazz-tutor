"""Source retrieval/fidelity boundaries, using temporary caches and synthetic bytes."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import materials as m
import coaching_materials as cm
import recommendation as rec
import review
from recommendation_fixture import abc_result, plan, SyntheticRunner


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.practice = self.root / 'practice'
        self.practice.mkdir()
        self.source = {'id': m.catalog()[0]['id'], 'title': 'Synthetic piano lesson', 'author': 'Synthetic author',
                       'publisher': 'Synthetic publisher', 'format': 'html', 'url': 'https://example.test/lesson', 'topics': ['comping']}
        self.body = b'<html><nav>Ignore this menu</nav><h1>Shell voicings</h1><p>Connect thirds and sevenths.</p><h2>Charleston comping</h2><p>Use an offbeat response after the first chord.</p><script>evil()</script></html>'
        self.calls = []
        self.response_status = 200
        self.store = m.MaterialStore(self.cache, [self.source], self.fetch)
        self.data = review.curriculum()

    def fetch(self, url, headers, deadline):
        self.calls.append((url, headers))
        return {'status': self.response_status, 'url': url, 'body': self.body,
                'headers': {'ETag': 'synthetic-etag', 'Content-Type': 'text/html'}}

    def requests(self, **kwargs):
        return [{'source_id': self.source['id'], 'query': 'Charleston offbeat response', 'pages': [], **kwargs}]

    def prepare(self):
        context = rec.context_for(self.practice, self.data)
        goal = plan(); goal['material_requests'] = self.requests()
        return cm.prepare_context(self.practice, self.data, context, goal, store=self.store)

    def review_record(self, manifest):
        return {'source_sha256': manifest['sha256'], 'method': 'symbolic_source_comparison',
                'scope': 'The two-bar synthetic fixture',
                'reviewer': 'Synthetic verifier', 'checked': ['pitches', 'durations', 'spelling', 'voices', 'expression'],
                'notes': 'Synthetic comparison receipt for a fixture; not real publication evidence.'}

    def test_lazy_download_cache_hit_conditional_refresh_and_content_versions(self):
        self.assertFalse(self.cache.exists())
        first = self.store.retrieve(self.requests())
        self.assertEqual(len(self.calls), 1)
        packet = first['materials'][0]
        self.assertEqual(packet['locator']['label'], 'Charleston comping')
        self.assertNotIn('evil()', packet['text'])
        self.assertNotIn('Ignore this menu', packet['text'])
        self.assertEqual(self.store.retrieve(self.requests()), first)
        self.assertEqual(len(self.calls), 1)
        self.response_status = 304
        self.store.fetch(self.source['id'], refresh=True)
        self.assertEqual(self.calls[-1][1], {'If-None-Match': 'synthetic-etag'})
        self.response_status = 200
        self.body += b'<p>New edition</p>'
        newer = self.store.fetch(self.source['id'], refresh=True)
        self.assertNotEqual(newer['sha256'], packet['source']['sha256'])
        self.assertTrue((self.cache / 'objects' / packet['source']['sha256'] / 'original').exists())

    def test_partial_invalid_download_does_not_poison_cache_and_failures_are_explicit(self):
        self.body = b''
        result = self.store.retrieve(self.requests())
        self.assertFalse(result['materials'])
        self.assertTrue(result['material_failures'])
        self.assertFalse(list((self.cache / 'sources').glob('*.json')))
        self.source['format'] = 'pdf'
        self.store = m.MaterialStore(self.cache, [self.source], self.fetch)
        self.body = b'<html>Access denied</html>'
        self.assertIn('PDF', self.store.retrieve(self.requests())['material_failures'][0]['reason'])
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            self.store.retrieve(self.requests(source_id='invented-source'))

    def test_untrusted_urls_are_rejected_before_download(self):
        for url in ('file:///etc/passwd', 'http://example.com', 'https://user:password@example.com'):
            with self.subTest(url=url), self.assertRaises(m.MaterialError): m.public_url(url)
        with patch.object(m.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(m.MaterialError): m.public_url('https://example.com')

    def test_cache_lock_wait_respects_the_request_deadline(self):
        with self.store.lock(self.source['id'], time.monotonic() + 1):
            started = time.monotonic()
            result = self.store.retrieve(self.requests(), deadline=started + .05)
        self.assertLess(time.monotonic() - started, .5)
        self.assertFalse(result['materials'])
        self.assertIn('time limit', result['material_failures'][0]['reason'])
        self.assertEqual(self.calls, [])

    def test_pdf_text_and_selected_images_are_cached_without_claiming_ocr_verification(self):
        from PIL import Image, ImageDraw
        path = self.root / 'synthetic.pdf'
        image = Image.new('RGB', (500, 250), 'white')
        ImageDraw.Draw(image).text((10, 10), 'Synthetic score page', fill='black')
        image.save(path, 'PDF'); image.close()
        self.body = path.read_bytes()
        self.source['format'] = 'pdf'
        self.store = m.MaterialStore(self.cache, [self.source], self.fetch)
        result = self.store.retrieve(self.requests(pages=[1]))
        self.assertFalse(result['material_failures'])
        self.assertEqual(len(result['images']), 1)
        self.assertTrue(Path(result['images'][0]).is_file())
        packet = result['materials'][0]
        self.assertEqual(packet['locator']['page'], 1)
        self.assertEqual(packet['image_number'], 1)
        self.assertEqual(packet['verified_examples'], [])
        self.assertTrue(self.store.retrieve(self.requests(pages=[2]))['material_failures'])

    def test_reviewed_example_is_inserted_exactly_and_survives_source_cache_removal(self):
        manifest = self.store.fetch(self.source['id'])
        locator = self.store.extract(manifest)['chunks'][1]['locator']
        notation = abc_result()['exercise']['notation']
        with self.assertRaisesRegex(ValueError, 'comparison record'):
            self.store.import_example(self.source['id'], locator, notation, {})
        asset = self.store.import_example(self.source['id'], locator, notation, self.review_record(manifest))
        context = self.prepare()
        packet = context['preparation']['materials'][0]
        value = abc_result()
        value['exercise']['notation'] = None
        value['references'] = [{'source_id': self.source['id'], 'excerpt_id': packet['excerpt_id'],
                                'example_id': asset['id'], 'role': 'exercise_source', 'mode': 'source_original', 'source_excerpt': None, 'changes': []}]
        hydrated = cm.hydrate_result(value, context)
        self.assertEqual(hydrated['exercise']['notation'], notation)
        self.assertIsNone(value['exercise']['notation'])
        changed = copy.deepcopy(value); changed['exercise']['notation'] = copy.deepcopy(notation)
        changed['exercise']['notation']['abc'] = notation['abc'].replace('[FA]', '[GA]')
        with self.assertRaisesRegex(ValueError, 'cannot change'): cm.hydrate_result(changed, context)
        saved = rec.accept_conversation(self.practice, self.data, context, value)
        target = saved['target']
        self.assertEqual(target['source_references'][0]['source']['sha256'], manifest['sha256'])
        import shutil
        shutil.rmtree(self.cache)
        rec.validate_target(target)
        self.assertEqual(target['exercise']['notation'], notation)

    def test_only_read_material_can_be_cited_and_receipts_cannot_be_edited(self):
        context = self.prepare()
        cm.verify_preparation(self.practice, context)
        changed = copy.deepcopy(context)
        changed['preparation']['materials'][0]['locator']['label'] = 'An unread page'
        with self.assertRaisesRegex(ValueError, 'receipt'): cm.verify_preparation(self.practice, changed)
        value = abc_result()
        packet = context['preparation']['materials'][0]
        ref = {'source_id': self.source['id'], 'excerpt_id': packet['excerpt_id'], 'example_id': None,
               'role': 'teaching_reference', 'mode': 'generated_original', 'source_excerpt': None, 'changes': []}
        value['references'] = [ref]
        rec.validate_result(value, context)
        value['evidence'].append({'source_ids': [packet['excerpt_id']], 'interpretation': 'A synthetic teaching reference describes a comping idea.', 'confidence': 'low'})
        rec.validate_result(value, context)
        value['difficulty']['prediction']['source_ids'] = [packet['excerpt_id']]
        with self.assertRaisesRegex(ValueError, 'not supplied'):
            rec.validate_result(value, context)
        value['difficulty']['prediction']['source_ids'] = ['profile']
        ref['excerpt_id'] = 'invented-page'
        with self.assertRaisesRegex(ValueError, 'not supplied'): cm.hydrate_result(value, context)
        ref['excerpt_id'] = packet['excerpt_id']; ref.update(role='exercise_source', mode='source_adapted', source_excerpt='First example', changes=['Invented voicings'])
        with self.assertRaisesRegex(ValueError, 'Text alone'): cm.hydrate_result(value, context)

    def test_goal_must_cite_evidence_and_context_is_stale_if_records_change(self):
        context = rec.context_for(self.practice, self.data)
        goal = plan(); goal['evidence_ids'] = ['invented']
        with self.assertRaisesRegex(ValueError, 'not supplied'): cm.validate_plan(goal, context)
        (self.practice / 'profile.json').write_text('{"goal":"Changed synthetic goal"}')
        with self.assertRaises(rec.RecommendationError) as error:
            cm.prepare_context(self.practice, self.data, context, plan(), store=self.store)
        self.assertEqual(error.exception.code, 'stale')

    def test_pipeline_saves_plan_and_candidate_and_has_no_network_without_requested_source(self):
        with patch.object(m, 'download', side_effect=AssertionError('Unexpected download')):
            manager = rec.Recommendations(self.practice, self.data, SyntheticRunner())
            job = manager.start('R-' + 'a' * 32, asynchronous=False)
        self.assertEqual(job['state'], 'completed')
        artifact = json.loads(manager._path(job['id']).read_text())
        self.assertEqual(artifact['attempts'][0]['phase'], 'planning')
        self.assertEqual(artifact['context']['preparation']['materials'], [])
        self.assertEqual(artifact['result']['schema_version'], 3)
        self.assertEqual(len(review.read_events(self.practice)), 1)

    def test_only_music_validation_gets_one_repair_and_failures_do_not_create_tasks(self):
        for message, repairs in [('ABC: wrong chord degree', 1), ('Evidence was not supplied.', 0)]:
            class Failing(SyntheticRunner):
                repair_calls = 0
                def generate(self, context, **kwargs):
                    error = rec.RecommendationError('invalid_output')
                    error.invalid_result = abc_result()
                    error.validation_error = message
                    raise error
                def repair(self, candidate, error, context, **kwargs):
                    self.repair_calls += 1
                    failure = rec.RecommendationError('invalid_output')
                    failure.invalid_result = candidate
                    failure.validation_error = 'ABC: still invalid'
                    raise failure
            runner = Failing()
            manager = rec.Recommendations(self.practice, self.data, runner)
            job = manager.start('R-' + str(repairs + 1) * 32, asynchronous=False)
            self.assertEqual(job['state'], 'failed')
            self.assertEqual(runner.repair_calls, repairs)
            artifact = json.loads(manager._path(job['id']).read_text())
            self.assertEqual(len(artifact['attempts']), 2 + repairs)
            self.assertEqual(review.read_events(self.practice), [])

    def test_music_repair_cannot_rewrite_coaching_or_drop_claims(self):
        context = self.prepare()
        candidate = abc_result()
        runner = rec.CodexRunner()
        for field in ('prose', 'claims'):
            changed = copy.deepcopy(candidate)
            if field == 'prose': changed['exercise']['objective'] = 'A different goal'
            else: changed['music_claims'] = []
            def complete(prompt, schema, validate, **kwargs):
                validate(changed)
            with patch.object(runner, 'complete', side_effect=complete), self.assertRaisesRegex(ValueError, 'Music repair'):
                runner.repair(candidate, 'ABC: synthetic error', context)


if __name__ == '__main__': unittest.main()
