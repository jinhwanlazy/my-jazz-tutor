"""Opt-in real translation and targeted repair, using only synthetic records."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import recommendation as rec
import review as r
from recommendation_fixture import result
from test_webapp import chunk
from webapp import Application, make_server


class SyntheticExercise:
    def generate(self, context):
        value=result();e=value['exercise']
        e.update(title='Synthetic rests and offbeat entries',
                 rhythm='The right hand uses eighth notes and eighth-note rests; the left hand uses half notes. Count four quarter-note beats per bar.',
                 instructions='Follow the written note and rest positions. Keep the eighth-note rests silent.',
                 right_hand='Play F#4 and A4 in the first bar, G4 and B4 in the second bar, at the written onsets.',
                 left_hand='Play D3 twice in the first bar and G2 twice in the second bar, holding each for two beats.',
                 notes='LH: D3 in bar 1 and G2 in bar 2. RH: F#4/A4 then G4/B4, following the written eighth notes and rests.',
                 steps=['Repeat two bars four times at seventy-two BPM.', 'Rest for one minute, then repeat the phrase.'])
        for i,bar in enumerate(e['notation']['bars']):
            bar['left']=[{'beat':beat,'duration':2,'notes':['D3' if i==0 else 'G2']} for beat in (0,2)]
            pitches=['F#4','A4'] if i==0 else ['G4','B4']
            notes=[[],[pitches[0]],[pitches[1]],[],[pitches[0]],[],[pitches[1]],[]]
            bar['right']=[{'beat':j/2,'duration':.5,'notes':n} for j,n in enumerate(notes)]
        value['difficulty']['axes']['rhythm'].update(level=3,anchor_ids=['rhythm-3'],
            reason='Changing eighth-note rests and offbeat entries add rhythmic demands compared with regular quarter notes.')
        return value,{'provider':'synthetic-translation-test'}


class DropOnePlaceholder(rec.CodexRunner):
    """Test-only fault injection after a real response; never a production fallback."""
    def __init__(self):
        super().__init__();self.calls=0;self.repaired_fields=[]

    def translate(self, context, schema):
        result,provenance=super().translate(context,schema)
        self.calls+=1
        if self.calls==1:
            result=copy.deepcopy(result)
            assert '[KEEP_0]' in result['strings']['exercise.notes']
            result['strings']['exercise.notes']=result['strings']['exercise.notes'].replace('[KEEP_0]','')
        else:
            self.repaired_fields=list(context['strings'])
        return result,provenance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if not args.run:parser.error('Use --run to enable real Codex calls with synthetic text.')
    with tempfile.TemporaryDirectory(prefix='jazz-translation-synthetic-') as directory:
        root=Path(directory);data=r.curriculum()
        (root/'profile.json').write_text('{"language":"ko","timezone":"UTC"}')
        app=Application(root,data,recommender=SyntheticExercise())
        tid=app.recommendations.start('R-'+'d'*32,asynchronous=False)['task_id']
        sid=app.store.start(tid)['id'];app.store.append(sid,chunk());app.store.finish(sid,1)
        before=(root/'practice.csv').read_bytes();midi=app.store.export(sid)
        translator=DropOnePlaceholder();server=make_server(root,data,0,translator=translator)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        address=f'http://127.0.0.1:{server.server_port}';start=time.monotonic()
        def state():return json.load(urllib.request.urlopen(address+'/api/state?lang=ko'))
        try:
            initial=state();assert translator.calls==0
            request=urllib.request.Request(address+'/api/translate?lang=ko',data=json.dumps({'task_id':tid}).encode(),
                headers={'Content-Type':'application/json','X-Jazz-Token':initial['csrf_token']})
            json.load(urllib.request.urlopen(request))
            while time.monotonic()-start<500:
                current=state()['history'][0]['target']
                if current['translation']['state'] not in ('running','missing'):break
                time.sleep(.3)
            assert current['translation']['state']=='completed',current['translation']
            assert translator.calls==2
            assert 'exercise.notes' in translator.repaired_fields
            assert '8분' in current['exercise']['rhythm'] and '쉼표' in current['exercise']['rhythm']
            assert '72' in current['exercise']['steps'][0]
            assert (root/'practice.csv').read_bytes()==before
            assert app.store.export(sid)==midi
            canonical=r.records(r.read_events(root))[0]['target']
            for key in ('notation','accompaniment','bpm','bars','key'):
                assert current['exercise'][key]==canonical['exercise'][key]
            assert current['difficulty']['features']==canonical['difficulty']['features']
            for axis,rating in canonical['difficulty']['axes'].items():
                for key in ('level','status','anchor_ids'):
                    assert current['difficulty']['axes'][axis][key]==rating[key]
            summary={'passed':True,'synthetic_only':True,'seconds':round(time.monotonic()-start,1),
                     'real_translation_calls':translator.calls,'repaired_fields':translator.repaired_fields,
                     'preserved_ledger_midi_music_and_difficulty':True}
            output=Path(__file__).resolve().parents[1]/'build/translation-smoke.json'
            output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(summary,indent=2))
            print(json.dumps(summary,indent=2))
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
