"""Opt-in repeated coaching comparisons using only synthetic learner records.

Each invocation gets a fresh temporary practice directory and private copy of a
public-material cache. Point --workflow at a frozen source snapshot. No current
profile, practice records, or production runtime are opened. Artifacts preserve
failures as well as successes; an existing output cannot be overwritten.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid


SCENARIOS = {
    'too_easy': {
        'label': 'too_easy',
        'notes': [
            'Synthetic feedback: this sustained root-and-shell exercise felt too easy. I want an actual musical phrase, not just longer holds.',
            'Synthetic feedback: still too easy and repetitive. Please give me a meaningful musical stretch, not only a faster metronome or a new key.',
        ],
        'expectation': 'Introduce a meaningful musical demand beyond tempo or transposition, while retaining a workable practice goal.',
    },
    'challenging': {
        'label': 'challenging',
        'notes': [
            'Synthetic feedback: useful and challenging. I had to concentrate on finding each shell and keeping the bass quiet.',
            'Synthetic feedback: this is still a useful challenge. Please keep C and 72 BPM for now; I want a musical next step without adding several harder things at once.',
        ],
        'expectation': 'Respect the requested key and tempo; keep the next stretch focused. Challenging is not evidence of failure or mastery.',
    },
    'bored_skip': {
        'label': 'good',
        'notes': [
            'Synthetic feedback: useful introduction to the sound of thirds and sevenths.',
            'Synthetic feedback: useful, but another sustained-chord worksheet would be boring. I would like some melodic movement and a clear musical phrase.',
        ],
        'skip_reason': 'Synthetic skip: I did not attempt this third sustained-chord worksheet. It looks like the same activity again. I want something that sounds like a musical phrase.',
        'expectation': 'Change the repeated activity and respond to the skip reason. Do not count the unattempted task as a failed performance.',
    },
}
REQUEST = 'Please choose my next useful jazz-piano practice from the supplied history and available practice time.'
PROFILE = {
    'language': 'en', 'timezone': 'UTC', 'daily_minutes': 20,
    'piano_experience': 'Synthetic learner: reads both staves and plays major and minor triads.',
    'jazz_experience': 'Synthetic learner: starting jazz, recently introduced to root-plus-third-and-seventh shell shapes in C.',
    'goal': 'Develop musical jazz phrasing and comping vocabulary that can be used in actual playing.',
}


def history_result(index):
    from recommendation_fixture import abc_result
    value = abc_result(4)
    e = value['exercise']
    e.update(title=f'Synthetic sustained C blues shells {index + 1}',
             objective='Find the third and seventh of C7, F7 and G7 while holding a quiet bass root.',
             selection_reason='Synthetic assigned conditions for a comparison; not an observed performance.',
             section='Four-bar sustained-shell worksheet', key='C', bpm=72, bars=4, minutes=10,
             left_hand='Whole-note roots C3, C3, F2, G2 in bars 1–4.',
             right_hand='Whole-note shells Bb3+E4, Bb3+E4, A3+Eb4, B3+F4 in bars 1–4.',
             notes='C7, C7, F7, G7; play only the listed root and shell notes.',
             rhythm='One whole-note attack on beat 1 of each 4/4 measure, hands together.',
             instructions='Find the shells separately, then connect them with a quiet bass at the assigned metronome setting.',
             steps=['Locate each hand separately.', 'Play the four bars together at 72 BPM.'],
             notation_reason='Exact synthetic assigned conditions; no performance accuracy is asserted.', accompaniment=None)
    e['development'] = {
        'focus': 'Find and connect shell shapes.', 'musical_structure': 'C7 C7 F7 G7, one sustained chord per measure.',
        'expression': 'Keep the bass quiet.', 'application': 'Repeat the four bars with the same pitches.',
        'difference_from_recent': 'The synthetic comparison intentionally repeats this activity.'}
    e['notation'] = {'format': 'abc', 'profile': 'jazz-abc-1', 'abc':
        'X:1\nT:Synthetic sustained shells\nM:4/4\nL:1/8\n%%score { RH LH }\nV:RH clef=treble\nV:LH clef=bass\nK:C\n'
        '[V:RH] "C7"!mf![_B,E]8 | "C7"[_B,E]8 | "F7"[A,_E]8 | "G7"[B,F]8 |\n'
        '[V:LH] !p!C,8 | C,8 | F,,8 | G,,8 |\n'}
    value['music_claims'] = [{'bar': 1, 'beat': 0, 'voice': 'RH', 'pitch': 'E4', 'chord': 'C7', 'degree': 3, 'alteration': 0}]
    value['evidence'] = [{'source_ids': ['profile'], 'interpretation': 'Synthetic fixture assignment; no performance evidence.', 'confidence': 'low'}]
    for axis in value['difficulty']['axes'].values():
        axis.update(status='unknown', level=None, anchor_ids=[], reason='Synthetic history does not supply a calibrated axis rating.')
    value['difficulty']['focus_axes'] = ['harmony', 'coordination']
    return value


def seed(root, rec, review, scenario, date):
    (root / 'profile.json').write_text(json.dumps(PROFILE))
    data = review.curriculum()
    spec = SCENARIOS[scenario]
    events = []
    for index in range(3 if 'skip_reason' in spec else 2):
        day = (date - timedelta(days=3 - index)).date().isoformat()
        target = rec.make_target(history_result(index), data, {'provider': 'synthetic-history'})
        task_id = 'T-' + f'{index + 1:010d}'
        assigned = review.new_event('assigned', task_id, data, target['exercise_id'])
        assigned.update(event_id=f'SYNTHETIC-ASSIGN-{index}', recorded_at=day + 'T10:00:00+00:00', target_json=review.jdump(target))
        review.append_event(root, assigned)
        if index == 2:
            result = review.new_event('discarded', task_id, data, target['exercise_id'])
            result.update(event_id=f'SYNTHETIC-SKIP-{index}', recorded_at=day + 'T10:01:00+00:00',
                          reason=review.jdump({'choice': '', 'note': spec['skip_reason']}))
        else:
            result = review.new_event('reported', task_id, data, target['exercise_id'])
            result.update(event_id=f'SYNTHETIC-REPORT-{index}', recorded_at=day + 'T10:10:00+00:00',
                          practice_date=day, actual_json='{}', checks_json='{}', difficulty=spec['label'],
                          raw_note=spec['notes'][index] + ' Actual note and timing accuracy have not been measured.')
        review.append_event(root, result)
        events.extend([assigned, result])
    assert not any(review.is_pending(t) for t in review.records(events))
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', action='store_true', required=True)
    p.add_argument('--prepare-only', action='store_true', help='Validate the synthetic setup without invoking Codex.')
    p.add_argument('--workflow', type=Path, required=True)
    p.add_argument('--cache-seed', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenario', choices=SCENARIOS, required=True)
    p.add_argument('--replicate', type=int, choices=[1, 2, 3], required=True)
    p.add_argument('--date', default=datetime.now(timezone.utc).date().isoformat())
    args = p.parse_args()
    if args.output.exists():
        p.error('Output already exists; preserve prior attempts and choose another output.')
    production = (Path(__file__).resolve().parents[2] / 'practice').resolve()
    for path in (args.workflow, args.cache_seed, args.output):
        resolved = path.resolve()
        if (resolved == production or production in resolved.parents or
                any((path / f).exists() for f in ('practice.csv', 'profile.json', 'sessions.sqlite3', 'runtime.json'))):
            p.error('Do not use a personal practice directory.')
    sys.path.insert(0, str(args.workflow.resolve()))
    import recommendation as rec
    import review
    args.output.mkdir(parents=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='jazz-synthetic-coaching-consistency-') as name:
        root = Path(name)
        shutil.copytree(args.cache_seed, root / 'materials')
        os.environ['JAZZ_MATERIALS_CACHE'] = str(root / 'materials')
        data = seed(root, rec, review, args.scenario, datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc))
        context = rec.context_for(root, data, request=REQUEST)
        (args.output / 'synthetic-context.json').write_text(json.dumps(context, ensure_ascii=False, indent=2))
        if args.prepare_only:
            print(json.dumps({'state': 'prepared_only', 'scenario': args.scenario}), flush=True)
            return 0
        print(f'Starting {args.scenario} #{args.replicate}: {args.workflow}', flush=True)
        manager = rec.Recommendations(root, data)
        job = manager.start('R-' + uuid.uuid4().hex,
                            request=REQUEST, asynchronous=False)
        artifact = json.loads(manager._path(job['id']).read_text())
        (args.output / 'artifact.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        summary = {'state': job['state'], 'error': job.get('error_code'), 'message': rec.ERRORS.get(job.get('error_code')),
                   'attempts': len(artifact.get('attempts', [])), 'scenario': args.scenario, 'replicate': args.replicate,
                   'validation_errors': [a.get('validation_error') for a in artifact.get('attempts', []) if a.get('validation_error')],
                   'synthetic_profile': PROFILE, 'scenario_spec': SCENARIOS[args.scenario], 'request': REQUEST,
                   'policy': rec.POLICY_VERSION, 'elapsed_seconds': round(time.monotonic() - started, 2)}
        if job['state'] == 'completed':
            task = next(t for t in review.records(review.read_events(root)) if t['assignment']['task_id'] == job['task_id'])
            rec.validate_target(task['target'])
            (args.output / 'target.json').write_text(json.dumps(task['target'], ensure_ascii=False, indent=2))
            summary.update(title=task['target']['exercise']['title'], references=artifact['result']['references'])
        (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps({k: summary[k] for k in ('state', 'error', 'scenario', 'replicate', 'attempts', 'elapsed_seconds')}, ensure_ascii=False), flush=True)
        return 0 if job['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
