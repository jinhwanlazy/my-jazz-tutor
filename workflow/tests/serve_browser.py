"""Explicit test harness. Only synthetic records; no Codex call or production fallback."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review as r
from webapp import make_server
from recommendation import RecommendationError
from recommendation_fixture import SyntheticRunner, SyntheticTranslator, abc_result
from materials import MaterialStore, catalog
import coaching_materials


class BrowserRunner(SyntheticRunner):
    def plan(self, context, **kwargs):
        value, provenance = super().plan(context, **kwargs)
        if context['request'].startswith('simulate:source'):
            value['material_requests'] = [{'source_id': catalog()[0]['id'], 'query': 'synthetic', 'pages': []}]
        return value, provenance

    def generate(self, context, **kwargs):
        time.sleep(1)
        if context['request'] == 'simulate:auth':
            raise RecommendationError('auth')
        result, provenance = super().generate(context)
        if context['request'].startswith('simulate:abc'):
            result = abc_result(12 if '12' in context['request'] else 8, 3 if '3/4' in context['request'] else 4)
        if context['request'].startswith('simulate:source'):
            packet = context['preparation']['materials'][0]
            original = context['request'] == 'simulate:source-original'
            result['references'] = [{'source_id': packet['source_id'], 'excerpt_id': packet['excerpt_id'],
                                     'example_id': packet['verified_examples'][0]['id'] if original else None,
                                     'role': 'exercise_source' if original else 'teaching_reference',
                                     'mode': 'source_original' if original else 'generated_original',
                                     'changes': [], 'source_excerpt': None}]
            if original: result['exercise']['notation'] = None
        if context['request'] == 'simulate:translation-auth':
            result['exercise']['instructions'] = 'Synthetic translation authentication failure; retry this fixture.'
        if context['request'] == 'simulate:translation-repair':
            result['exercise']['instructions'] = 'Synthetic translation repair case. Keep eighth-note rests silent.'
        if context['request'] == 'simulate:no-pad':
            result['exercise']['accompaniment'] = None
            result['exercise']['rhythm'] = 'Two half notes per bar in 4/4.'
            result['exercise']['instructions'] = 'Play each chord twice per bar, holding each for two beats. Connect the two bars.'
            abc = result['exercise']['notation']['abc']
            for notes in ('[FA]', '[GB]', 'D,', 'G,,'):
                abc = abc.replace(notes + '8', notes + '4 ' + notes + '4')
            result['exercise']['notation']['abc'] = abc
        return result, provenance


class BrowserTranslator(SyntheticTranslator):
    def translate(self, context, schema):
        time.sleep(.5)
        instructions = context['strings'].get('exercise.instructions', '')
        if 'Synthetic translation authentication failure' in instructions and not getattr(self, 'failed_once', False):
            self.failed_once = True
            raise RecommendationError('auth')
        result, provenance = super().translate(context, schema)
        if 'Synthetic translation repair case' in instructions and 'repair' not in context:
            result['strings']['exercise.instructions'] += ' 99 BPM'
        return result, provenance


root = Path(sys.argv[1]).resolve()
if not root.name.startswith('jazz-browser-'):
    raise ValueError('Browser tests require their own temporary directory.')

class BrowserMaterials(MaterialStore):
    def __init__(self):
        source = {**catalog()[0], 'title': 'Synthetic source lesson', 'author': 'Synthetic teacher',
                  'publisher': 'Synthetic publisher', 'url': 'https://example.test/lesson', 'format': 'html'}
        super().__init__(root / 'source-cache', [source], lambda url, headers, deadline:
                         {'status': 200, 'url': url, 'headers': {}, 'body': b'<h1>Synthetic lesson</h1><p>Synthetic chord connection.</p>'})

    def retrieve(self, requests, **kwargs):
        if requests:
            source_id = requests[0]['source_id']
            manifest = self.fetch(source_id)
            locator = self.extract(manifest)['chunks'][0]['locator']
            self.import_example(source_id, locator, abc_result()['exercise']['notation'],
                {'source_sha256': manifest['sha256'], 'method': 'symbolic_source_comparison',
                 'reviewer': 'Synthetic verifier', 'scope': 'Synthetic two-bar example',
                 'notes': 'Synthetic fixture only; not a claim about a real lesson.',
                 'checked': ['pitches', 'durations', 'spelling', 'voices', 'expression']})
        return super().retrieve(requests, **kwargs)

coaching_materials.MaterialStore = BrowserMaterials
server = make_server(root, r.curriculum(), 0, recommender=BrowserRunner(), translator=BrowserTranslator(), host=sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1')
print(f'http://127.0.0.1:{server.server_port}', flush=True)
server.serve_forever()
