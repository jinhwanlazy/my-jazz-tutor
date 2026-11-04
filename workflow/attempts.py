"""One-sweep attempts, versioned MIDI analysis and explicit task transitions."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import review as r
from notation import score_for
from sessions import SessionStore, midi_messages, reflection_measurements

HERE = Path(__file__).resolve().parent
ANALYSIS_VERSION = 'midi-analysis-2'
SUPPORTED_ANALYSIS_VERSIONS = ('midi-analysis-1', 'midi-analysis-2')


def js(value):
    node = os.environ.get('JAZZ_NODE_BIN') or shutil.which('node')
    r.require(node, 'Node.js is required for MIDI analysis.')
    process = subprocess.run([node, str(HERE / 'midi-analysis-cli.mjs')], input=r.jdump(value),
                             capture_output=True, text=True, timeout=15)
    r.require(process.returncode == 0, 'MIDI analysis could not finish. The original recording is preserved.')
    return json.loads(process.stdout)


@lru_cache(maxsize=256)
def _contract(target_json, bpm, manual, latency):
    target = json.loads(target_json)
    value = js({'action': 'contract', 'score': score_for(target), 'conditions': target,
                'options': {'bpm': bpm, 'manual': manual, 'latency_ms': latency}})
    value['target_hash'] = hashlib.sha256(target_json.encode()).hexdigest()
    return value


def contract_for(target, bpm=None, manual=False, latency=0):
    return json.loads(r.jdump(_contract(r.jdump(target), bpm or target['bpm'], manual, latency)))


def cycle(task):
    return (task.get('reopening') or task['assignment'])['event_id']


def recording_coverage(task, sessions=(), attempts=()):
    """Describe what was captured, never infer no practice from absent take rows."""
    tid = task['assignment']['task_id']
    takes = [a for a in attempts if a['task_id'] == tid]
    take_sessions = {a['session_id'] for a in takes}
    older = [s for s in sessions if s['task_id'] == tid and s['id'] not in take_sessions]
    release = task['assignment']['release']
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', release)
    tracked = bool(match and tuple(map(int, match.groups())) >= (0, 7, 0))
    legacy = bool(older or not tracked or task['report'] and not takes)
    mode = 'mixed' if takes and legacy else 'finite_attempts' if takes or not legacy else 'legacy'
    return {'mode': mode, 'recorded_attempts': len(takes) if mode != 'legacy' else None,
            'legacy_session_count': len(older),
            'interpretation': 'Legacy records did not track individual takes; their absence does not mean the user did not practice. Keep original completion, feedback, notes and measurements.'
                if legacy else 'Count of saved finite attempts only, not all practice performed by the user.'}


class AttemptStore:
    def __init__(self, root):
        self.root = Path(root)
        self.sessions = SessionStore(root)

    @contextmanager
    def database(self):
        with self.sessions.database() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, session_id TEXT UNIQUE NOT NULL,
                    cycle_id TEXT NOT NULL, created_at TEXT NOT NULL, contract TEXT NOT NULL,
                    state TEXT NOT NULL, finished_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_recording_attempt
                    ON attempts((1)) WHERE state='recording';
                CREATE TABLE IF NOT EXISTS attempt_analyses (
                    attempt_id TEXT NOT NULL, version TEXT NOT NULL, result TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(attempt_id,version)
                );
                PRAGMA user_version = 2;
            ''')
            yield db

    @staticmethod
    def public(row, result=None, detail=False):
        contract = json.loads(row['contract'])
        value = {k: row[k] for k in ('id', 'task_id', 'session_id', 'cycle_id', 'created_at', 'state', 'finished_at')}
        value.update(bpm=contract['bpm'], mode=contract['mode'], result=(result or {}).get('result'),
                     analysis_version=(result or {}).get('version'),
                     qualified_pass=(result or {}).get('qualified_pass', False),
                     counts=(result or {}).get('counts', {}), timing=(result or {}).get('timing', {}),
                     expression=(result or {}).get('expression', {}), manual_reason=contract.get('manual_reason'))
        if detail:
            value.update(contract=contract, analysis=result)
        return value

    def list(self, task_id=None):
        if not self.sessions.path.exists():
            return []
        with self.database() as db:
            rows = db.execute('SELECT * FROM attempts' + (' WHERE task_id=?' if task_id else '') +
                              ' ORDER BY created_at,id', (task_id,) if task_id else ()).fetchall()
            values = []
            for row in rows:
                saved = db.execute('SELECT result FROM attempt_analyses WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1', (row['id'],)).fetchone()
                values.append(self.public(row, json.loads(saved[0]) if saved else None))
            return values

    def details(self, attempt_id):
        r.require(isinstance(attempt_id, str) and re.fullmatch(r'A-[a-f0-9]{32}', attempt_id), 'Invalid attempt ID.')
        r.require(self.sessions.path.exists(), 'Attempt not found.')
        with self.database() as db:
            row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            r.require(row is not None, 'Attempt not found.')
            saved = db.execute('SELECT result FROM attempt_analyses WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1', (attempt_id,)).fetchone()
            return self.public(row, json.loads(saved[0]) if saved else None, True)

    def start(self, task_id, attempt_id, bpm, manual=False, latency_ms=0):
        r.require(isinstance(attempt_id, str) and re.fullmatch(r'A-[a-f0-9]{32}', attempt_id), 'Invalid attempt ID.')
        r.number(bpm, 'bpm', 20, 240)
        r.number(latency_ms, 'latency_ms', -250, 250)
        r.require(type(manual) is bool, 'Invalid manual mode.')
        sid = 'S-' + attempt_id[2:]
        with r.log_lock(self.root), self.database() as db:
            old = db.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if old:
                old_contract = json.loads(old['contract'])
                r.require(old['task_id'] == task_id and old_contract['bpm'] == bpm and old_contract['latency_ms'] == latency_ms
                          and old_contract['requested_manual'] == manual,
                          'This attempt ID belongs to another attempt.')
                session = db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
                return {'attempt': self.public(old, detail=True), 'session': self.sessions.public(session)}
            task = next((t for t in r.records(r.read_events(self.root)) if t['assignment']['task_id'] == task_id), None)
            r.require(task is not None and r.is_pending(task), 'Choose an active practice.')
            r.require(not db.execute("SELECT 1 FROM sessions WHERE status='recording'").fetchone(),
                      'Finish or recover the current recording before starting another attempt.')
            contract = contract_for(task['target'], bpm, manual, latency_ms)
            created = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)',
                       (sid, task_id, task['assignment']['release'], r.jdump(task['target']), created, 'recording'))
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,NULL)',
                       (attempt_id, task_id, sid, cycle(task), created, r.jdump(contract), 'recording'))
            row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            return {'attempt': self.public(row, detail=True), 'session': self.sessions.public(db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone())}

    def finish_session(self, session_id):
        """Called after durable session sealing; retries never replace an analysis."""
        with r.log_lock(self.root), self.database() as db:
            row = db.execute('SELECT * FROM attempts WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                return None
            saved = db.execute('SELECT result FROM attempt_analyses WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1', (row['id'],)).fetchone()
            if saved:
                return self.public(row, json.loads(saved[0]), True)
            session = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
            r.require(session['status'] != 'recording', 'Save the recording before analysis.')
            chunks = self.sessions.chunks(db, session_id)
            events = [event for chunk in chunks for event in chunk['events']]
            plays = [e for e in events if e['type'] == 'play']
            aborted = any(e['type'] == 'aborted' for e in events) or not plays
            contract = json.loads(row['contract'])
            origin = plays[0]['at_ms'] if plays else 0
            elapsed = max((c['elapsed_ms'] for c in chunks), default=0)
            interrupted = (session['status'] == 'interrupted' or len(plays) != 1 or
                           any(e['type'] in ('disconnect', 'audio_interrupted', 'recovered') or
                               e['type'] == 'visibility' and e.get('hidden') for e in events) or
                           elapsed + contract['tolerance_ms'] < origin + contract['duration_ms'] or
                           not any(e['type'] == 'attempt_end' for e in events))
            if plays and any(e.get('bpm') != contract['bpm'] for e in plays + [e for e in events if e['type'] == 'tempo']):
                interrupted = True
            relevant = ({'at_ms': at, 'port': port, 'data': list(data)} for c in chunks
                        for at, port, data in midi_messages(c['midi']) if len(data) >= 3 and
                        (data[0] & 0xf0 in (0x80, 0x90) or data[0] & 0xf0 == 0xb0 and data[1] in (64, 120, 121, 123)))
            messages = list(islice(relevant, 60001))
            try:
                r.require(len(messages) <= 60000, 'Analysis input limit exceeded; recording preserved.')
                result = js({'contract': contract, 'messages': messages, 'options': {
                    'origin_ms': origin, 'end_ms': elapsed, 'final': True, 'interrupted': interrupted or aborted,
                    'initial_state': plays[0].get('initial_state', {}) if plays else {}}})
            except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                result = {'version': ANALYSIS_VERSION, 'result': 'unknown', 'qualified_pass': False,
                          'reason': 'Analysis unavailable; original MIDI is preserved.', 'bars': [], 'counts': {}}
            result.update(origin_ms=origin, recorded_end_ms=elapsed)
            state = 'aborted' if aborted else 'interrupted' if interrupted else 'finished'
            now = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO attempt_analyses VALUES (?,?,?,?)', (row['id'], ANALYSIS_VERSION, r.jdump(result), now))
            db.execute('UPDATE attempts SET state=?,finished_at=? WHERE id=?', (state, now, row['id']))
            return self.public(db.execute('SELECT * FROM attempts WHERE id=?', (row['id'],)).fetchone(), result, True)

    def summary(self, task, attempts=None):
        history = attempts if attempts is not None else self.list(task['assignment']['task_id'])
        history = [a for a in history if a['task_id'] == task['assignment']['task_id']]
        current = [a for a in history if a['task_id'] == task['assignment']['task_id'] and a['cycle_id'] == cycle(task)]
        passed = [a for a in current if a['state'] == 'finished' and a['qualified_pass']]
        manual = [a for a in current if a['state'] == 'finished' and a['mode'] == 'manual' and a['bpm'] >= task['target']['bpm']]
        return {'cycle_id': cycle(task), 'successes': len(passed), 'eligible': bool(passed),
                'manual_available': bool(manual), 'attempt_count': len(history),
                'last_attempt_id': current[-1]['id'] if current else None}

    def complete(self, data, task_id, expected_event_id, manual_confirmed=False, attempt_id=None):
        r.require(type(manual_confirmed) is bool, 'Invalid confirmation.')
        with r.log_lock(self.root):
            events = r.read_events(self.root)
            task = next((t for t in r.records(events) if t['assignment']['task_id'] == task_id), None)
            r.require(task is not None and not task['cancelled'] and not task['deleted'], 'Active practice not found.')
            if not r.is_pending(task):
                previous = r.reflection_observations(task['completion']) or {}
                if previous.get('attempt_completion', {}).get('expected_event_id') == expected_event_id:
                    return {'task_id': task_id, 'event_id': task['completion']['event_id']}
            r.require(r.is_pending(task) and task['lifecycle_event_id'] == expected_event_id, 'This practice changed. Refresh before completing it.')
            candidates = [a for a in self.list(task_id) if a['cycle_id'] == cycle(task) and a['state'] == 'finished']
            eligible = [a for a in candidates if a['qualified_pass'] or manual_confirmed and a['mode'] == 'manual' and a['bpm'] >= task['target']['bpm']]
            chosen = next((a for a in eligible if not attempt_id or a['id'] == attempt_id), None)
            r.require(chosen is not None, 'Complete a successful attempt at the target BPM first, or explicitly confirm an unscored attempt.')
            sessions = self.sessions.list(task_id)
            r.require(not any(s['status'] == 'recording' for s in sessions), 'Finish the current attempt first.')
            current_ids = {a['session_id'] for a in self.list(task_id) if a['cycle_id'] == cycle(task)}
            sessions = [s for s in sessions if s['id'] in current_ids]
            profile_path = self.root / 'profile.json'
            profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
            measured = reflection_measurements(sessions, profile)
            measured['attempt_completion'] = {'policy': 'attempt-policy-1', 'attempt_id': chosen['id'],
                'analysis_version': chosen['analysis_version'], 'basis': 'midi-analysis' if chosen['qualified_pass'] else 'user-confirmation',
                'cycle_id': cycle(task), 'expected_event_id': expected_event_id}
            event = r.new_event('completed', task_id, data, task['assignment']['exercise_id'])
            event.update(release=task['assignment']['release'], practice_date=measured['practice_date'],
                         actual_json='{}', checks_json='{}', reason=r.jdump(measured),
                         actual_minutes='' if measured['minutes'] is None else str(measured['minutes']))
            r.records(events + [event]); r.append_event(self.root, event)
        return {'task_id': task_id, 'event_id': event['event_id']}

    def context_summary(self, limit=5, task_ids=None, values=None):
        values = self.list() if values is None else values
        if task_ids is not None:
            values = [a for a in values if a['task_id'] in task_ids]
        latest = values[-limit:]
        return {'policy': 'attempt-context-2', 'recorded_attempts': len(values),
                'automatic_passes': sum(a['qualified_pass'] for a in values),
                'omitted_detailed_attempts': max(0, len(values)-limit),
                'recent': [{k: a[k] for k in ('id','task_id','cycle_id','created_at','state','bpm','mode','result','qualified_pass','counts','timing','expression')} for a in latest],
                'provenance': 'Only saved finite attempts are counted. Legacy sessions and self-reports are not represented by these counts; their absence is not no practice. Versioned MIDI analysis is not audio verification or mastery. Manual mode is unassessed.'}
