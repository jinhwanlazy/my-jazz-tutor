"""Synthetic current/legacy note feedback. Never reads real records or calls Codex."""
import base64
import json
from pathlib import Path
import sys
import uuid

SOURCE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(SOURCE),str(SOURCE/'tests')]
import review as r
from recommendation import make_target
from recommendation_fixture import abc_result,SyntheticRunner,SyntheticTranslator
from sessions import FRAME
from webapp import Application,make_server

root=Path(sys.argv[1]).resolve();assert root.name.startswith('jazz-browser-note-feedback-')
(root/'profile.json').write_text('{"language":"en","timezone":"UTC","goal":"Synthetic note feedback verification"}')
data=r.curriculum();app=Application(root,data)

def assign(title,bars=2):
    value=abc_result(bars)
    value['music_claims']=[{'bar':1,'beat':0,'voice':'RH','pitch':'E4','chord':'C','degree':3,'alteration':0}]
    value['exercise'].update(title=title,key='C',bpm=120,accompaniment=None,
      rhythm='A quarter-note chord, a quarter rest and two quarter notes; then a whole note.',
      instructions='Play the written C major phrase; hold the bass notes as written.',
      notation={'format':'abc','profile':'jazz-abc-1','abc':
        'X:1\nM:4/4\nL:1/4\n%%score { RH LH }\nV:RH clef=treble\nV:LH clef=bass\nK:C\n'
        '[V:RH] "C"!mf![CEG] z G A | "C"c4 |\n[V:LH] !p!C,2 z2 | C,4 |\n'})
    if bars==16:
        value['exercise']['notation']['abc']=value['exercise']['notation']['abc'].split('[V:RH]')[0]+\
          '[V:RH] '+('"C"[CEG] [CEG] [CEG] [CEG] | '*bars)+'\n[V:LH] '+('C,4 | '*bars)+'\n'
    target=make_target(value,data,{'source_language':'en','provider':'synthetic-note-feedback'})
    tid='T-'+uuid.uuid4().hex[:10];event=r.new_event('assigned',tid,data,target['exercise_id'])
    event.update(target_json=r.jdump(target));r.append_event(root,event);return tid

def seed(tid,legacy=False):
    started=app.attempts.start(tid,'A-'+uuid.uuid4().hex,120);contract=started['attempt']['contract']
    origin=1000;beat=500;frames=[]
    for note in contract['expected']:
        at=origin+note['at']*beat
        frames.extend([(at,[0x90,note['pitch'],80]),(at+note['duration']*beat*.95,[0x80,note['pitch'],0])])
    blob=b''.join(FRAME.pack(at,0,len(message))+bytes(message) for at,message in sorted(frames))
    end=origin+contract['duration_ms'];sid=started['session']['id']
    app.store.append(sid,{'sequence':0,'midi':base64.b64encode(blob).decode(),
     'events':[{'type':'play','at_ms':origin,'bpm':120},{'type':'attempt_end','at_ms':end},{'type':'pause','at_ms':end}],
     'elapsed_ms':end+beat})
    app.store.finish(sid,1);saved=app.attempts.finish_session(sid)['analysis']
    if legacy:
        saved['version']='midi-analysis-1'
        for key in ('notes','extra_notes','final'):saved.pop(key,None)
        for note in contract['expected']:note.pop('locations',None)
        # Only this disposable fixture simulates the earlier persisted format.
        with app.attempts.database() as db:
            db.execute('UPDATE attempts SET contract=? WHERE id=?',(r.jdump(contract),started['attempt']['id']))
            db.execute('UPDATE attempt_analyses SET version=?,result=? WHERE attempt_id=?',('midi-analysis-1',r.jdump(saved),started['attempt']['id']))
    return started['attempt']['id']

legacy=assign('Synthetic saved v1 note study');legacy_attempt=seed(legacy,legacy=True)
many=assign('Synthetic full 208-note study',16);many_attempt=seed(many)
current=assign('Synthetic live note study')
server=make_server(root,data,0,recommender=SyntheticRunner(),translator=SyntheticTranslator())
print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}','current':current,'legacy':legacy,'legacy_attempt':legacy_attempt,'many':many,'many_attempt':many_attempt}),flush=True)
server.serve_forever()
