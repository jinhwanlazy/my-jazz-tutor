"""Opt-in real Codex integration; temporary synthetic records, never user data."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import threading
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review as r
from recommendation import Recommendations
from recommendation_fixture import SyntheticRunner
from webapp import Application, make_server
from test_webapp import chunk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Use the current CLI login and its usage allowance')
    args = parser.parse_args()
    if not args.run:
        parser.error('Use --run to explicitly enable the real connection test.')
    with tempfile.TemporaryDirectory(prefix='jazz-codex-synthetic-') as directory:
        root = Path(directory)
        (root/'profile.json').write_text(json.dumps({'language':'en','timezone':'UTC','daily_minutes':20,
            'piano_experience':'Synthetic player: major triads are comfortable',
            'goal':'Synthetic preference: improve smooth chord connections'}))
        data = r.curriculum()
        app = Application(root, data, recommender=SyntheticRunner())
        first = app.recommendations.start('R-'+'a'*32, asynchronous=False)['task_id']
        sid = app.store.start(first)['id']
        app.store.append(sid, chunk(events=[{'type':'play','at_ms':0,'bpm':80},{'type':'pause','at_ms':5000}]))
        app.store.finish(sid,1); app.store.complete(data,first)
        app.store.reflect(data,first,'too_easy','Synthetic note: I already know these two triad shapes; connecting them was too easy.')
        second = app.recommendations.start('R-'+'b'*32, asynchronous=False)['task_id']
        r.discard(root,data,second,'Synthetic skip: the same two chords again are not useful.','already_practiced')
        before = r.read_events(root)
        started = time.monotonic()
        server = make_server(root,data,0)
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        address = f'http://127.0.0.1:{server.server_port}'
        try:
            state = json.load(urllib.request.urlopen(address+'/api/state'))
            payload = json.dumps({'request_id':'R-'+'c'*32,
                'request':'Use the recorded feedback and skip reason to propose a useful next exercise. These are synthetic test records.'}).encode()
            request = urllib.request.Request(address+'/api/recommend?lang=en', data=payload,
                headers={'Content-Type':'application/json','X-Jazz-Token':state['csrf_token']})
            job = json.load(urllib.request.urlopen(request))
            while job['state'] == 'running' and time.monotonic()-started < 260:
                time.sleep(.5)
                state = json.load(urllib.request.urlopen(address+'/api/state'))
                job = state['recommendation']
        finally:
            server.shutdown();server.server_close();thread.join()

        elapsed=round(time.monotonic()-started,1)
        if job['state'] != 'completed':
            raise AssertionError(f'Real Codex failed: {job}')
        events=r.read_events(root); tasks=r.records(events)
        assert events[:-1] == before and len(tasks) == 3
        target=tasks[-1]['target']
        assert target['exercise_id'].startswith('G-') and target['analysis']['unknowns']
        refs=[ref for e in target['analysis']['evidence'] for ref in e['source_ids']]
        assert any(ref.startswith(('task:','event:')) for ref in refs), refs
        artifact=json.loads((root/target['generation']['context_file']).read_text())
        summary={'passed':True,'path':'HTTP /api/recommend -> asynchronous Codex -> validated assignment','seconds':elapsed,'history_tasks_analyzed':artifact['context']['history_window']['included_tasks'],
                 'title':target['title'],'key':target['key'],'bars':target['bars'],'source_ids':refs,
                 'provenance':artifact['provenance'],'preserved_previous_events':len(before)}
        output=Path(__file__).resolve().parents[1]/'build/codex-smoke.json'
        output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
