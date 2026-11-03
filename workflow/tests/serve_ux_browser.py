"""Disposable UI review fixture. No real user records or Codex calls."""
import base64
from datetime import datetime, timedelta, timezone
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

root=Path(sys.argv[1]).resolve()
assert root.name.startswith('jazz-browser-ux-review-')
(root/'profile.json').write_text(json.dumps({'language':'en','timezone':'UTC','daily_minutes':30,
 'goal':'Synthetic UI review; these are not a real student\u2019s performance records.'}))
data=r.curriculum();app=Application(root,data)

def assign(title,bars=12,bpm=72,days=0):
    value=abc_result(bars)
    value['exercise'].update(title=title,bpm=bpm)
    target=make_target(value,data,{'source_language':'en','provider':'synthetic-ui-review'})
    tid='T-'+uuid.uuid4().hex[:10]
    event=r.new_event('assigned',tid,data,target['exercise_id'])
    event.update(target_json=r.jdump(target),recorded_at=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat())
    r.append_event(root,event);return tid

def attempt(tid,wrong=False,manual=False):
    started=app.attempts.start(tid,'A-'+uuid.uuid4().hex,72,manual)
    contract=started['attempt']['contract'];sid=started['session']['id'];beat=60000/72;origin=1000
    frames=[]
    if not manual:
        for n in contract['expected']:
            at=origin+n['at']*beat;pitch=n['pitch']+(1 if wrong else 0)
            velocity=90 if any('RH' in v for v in n['voices']) else 60
            frames += [(at,[0x90,pitch,velocity]),(at+n['duration']*beat*.95,[0x80,pitch,0])]
    blob=b''.join(FRAME.pack(at,0,len(message))+bytes(message) for at,message in sorted(frames))
    end=origin+contract['duration_ms']
    app.store.append(sid,{'sequence':0,'midi':base64.b64encode(blob).decode(),
      'events':[{'type':'play','at_ms':origin,'bpm':72},{'type':'attempt_end','at_ms':end},{'type':'pause','at_ms':end}],
      'elapsed_ms':end+beat})
    app.store.finish(sid,1);return app.attempts.finish_session(sid)

def complete(tid,manual=False):
    task=next(t for t in app.state()['history'] if t['id']==tid)
    return app.attempts.complete(data,tid,task['lifecycle_event_id'],manual)

tasks={}
for days in (3,2):
    tid=assign(f'Synthetic completed chord study \u00b7 day {days}',4,days=days)
    task=next(t for t in r.records(r.read_events(root)) if t['assignment']['task_id']==tid)
    event=r.new_event('reported',tid,data,task['assignment']['exercise_id'])
    event.update(recorded_at=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),
      practice_date=(datetime.now(timezone.utc)-timedelta(days=days)).date().isoformat(),actual_json='{}',checks_json='{}',
      difficulty='challenging',raw_note='Synthetic review note: coordinating the bass and upper voice took concentration.')
    r.append_event(root,event)

tasks['completed']=assign('Synthetic completed shell-voicing study',4)
attempt(tasks['completed']);complete(tasks['completed'])
app.store.reflect(data,tasks['completed'],'challenging','Synthetic note: the upper line became clearer when I kept the bass quiet.')
tasks['skipped']=assign('Synthetic familiar progression',4)
r.discard(root,data,tasks['skipped'],'Synthetic skip reason: I practiced this pattern yesterday.','already_practiced')
tasks['reopened']=assign('Synthetic resumed practice with a previous successful take',8)
attempt(tasks['reopened']);saved=complete(tasks['reopened'])
r.reopen(root,data,tasks['reopened'],saved['event_id'])
tasks['manual']=assign('Synthetic practice without MIDI',8)
attempt(tasks['manual'],manual=True)
tasks['main']=assign('Synthetic twelve-bar guide-tone study with a connected upper voice',12)
for i in range(14):attempt(tasks['main'],wrong=i%4!=0)
tasks['ready']=assign('Synthetic new practice with no attempts',8)
tasks['blank']=assign('Synthetic untouched practice with the same score',8)
r.records(r.read_events(root))
server=make_server(root,data,0,recommender=SyntheticRunner(),translator=SyntheticTranslator())
print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}','tasks':tasks}),flush=True)
server.serve_forever()
