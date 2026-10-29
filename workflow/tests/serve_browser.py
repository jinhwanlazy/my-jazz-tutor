"""Explicit test harness. Only synthetic records; no Codex call or production fallback."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review as r
from webapp import make_server
from recommendation import RecommendationError
from recommendation_fixture import SyntheticRunner, SyntheticTranslator


class BrowserRunner(SyntheticRunner):
    def generate(self, context):
        time.sleep(1)
        if context['request'] == 'simulate:auth':
            raise RecommendationError('auth')
        result, provenance = super().generate(context)
        if context['request'] == 'simulate:translation-auth':
            result['exercise']['instructions'] = 'Synthetic translation authentication failure; retry this fixture.'
        if context['request'] == 'simulate:no-pad':
            result['exercise']['accompaniment'] = None
            result['exercise']['rhythm'] = 'Two half notes per bar in 4/4.'
            result['exercise']['instructions'] = 'Play each chord twice per bar, holding each for two beats. Connect the two bars.'
            for bar in result['exercise']['notation']['bars']:
                for hand in ('left', 'right'):
                    notes = bar[hand][0]['notes']
                    bar[hand] = [{'beat':0,'duration':2,'notes':notes}, {'beat':2,'duration':2,'notes':notes}]
        return result, provenance


class BrowserTranslator(SyntheticTranslator):
    def translate(self, context, schema):
        time.sleep(.5)
        if 'Synthetic translation authentication failure' in context['strings']['exercise.instructions'] and not getattr(self, 'failed_once', False):
            self.failed_once = True
            raise RecommendationError('auth')
        return super().translate(context, schema)


root = Path(sys.argv[1]).resolve()
if not root.name.startswith('jazz-browser-'):
    raise ValueError('Browser tests require their own temporary directory.')
server = make_server(root, r.curriculum(), 0, recommender=BrowserRunner(), translator=BrowserTranslator(), host=sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1')
print(f'http://127.0.0.1:{server.server_port}', flush=True)
server.serve_forever()
