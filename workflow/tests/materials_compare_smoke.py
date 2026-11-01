"""Opt-in full recommendation-path comparison on identical synthetic history.

Run each side with --workflow pointing to its source snapshot, and a copied public
material cache. A fresh temporary practice directory is mandatory and automatic.
Outputs are development artifacts only. This does not publish or accept user tasks.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--cache-seed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario', choices=['cadence', 'phrasing'], default='cadence')
    args = parser.parse_args()
    for path in (args.workflow, args.cache_seed, args.output):
        if (path / 'practice.csv').exists() or (path / 'profile.json').exists():
            raise ValueError('Do not use a personal practice directory.')
    sys.path.insert(0, str(args.workflow.resolve()))
    import recommendation as rec
    import review
    from recommendation_fixture import abc_result
    with tempfile.TemporaryDirectory(prefix='jazz-synthetic-material-comparison-') as name:
        root = Path(name)
        shutil.copytree(args.cache_seed, root / 'materials')
        os.environ['JAZZ_MATERIALS_CACHE'] = str(root / 'materials')
        profile = {'language': 'en', 'timezone': 'UTC', 'daily_minutes': 20,
                   'piano_experience': 'Synthetic player reads both staves and plays triads.',
                   'jazz_experience': 'Synthetic player has practiced sustained root-plus-shell shapes.',
                   'goal': 'Use jazz vocabulary and voice leading in musical phrases.'}
        (root / 'profile.json').write_text(json.dumps(profile))
        data = review.curriculum()
        for index in range(2):
            value = abc_result(4)
            value['exercise']['title'] = f'Synthetic sustained chords {index + 1}'
            target = rec.make_target(value, data, {'provider': 'synthetic-history'})
            tid = 'T-' + str(index) * 10
            assigned = review.new_event('assigned', tid, data, target['exercise_id'])
            assigned.update(recorded_at=f'2026-01-0{index + 1}T10:00:00+00:00', target_json=review.jdump(target))
            reported = review.new_event('reported', tid, data, target['exercise_id'])
            reported.update(recorded_at=f'2026-01-0{index + 1}T10:10:00+00:00', practice_date=f'2026-01-0{index + 1}',
                            actual_json='{}', checks_json='{}', difficulty='too_easy',
                            raw_note='Synthetic feedback: sustained chords feel repetitive. I want connected shell voicings through changing keys. Timing and note accuracy have not been measured.')
            for event in (assigned, reported): review.append_event(root, event)
        request = ('Synthetic comparison: a four-bar shell-voicing study with one complete ii-V-I cadence per bar, '
                   'cadences in C, Bb, A, then C. Use a C/no-key-signature notation envelope with written accidentals. '
                   'The goal is efficient third/seventh voice leading through changing keys, with simple roots in the left hand '
                   'and quarter-quarter-half timing in each bar. Consider Open Studio Jazz Piano for Beginners PDF page 44. '
                   'Prefer an exact reviewed example if it serves this whole goal; otherwise compose an original study '
                   'without claiming invented notes are published. Keep the four-bar form, with a quiet bass and a bounded application.')
        if args.scenario == 'phrasing':
            request = ('Synthetic comparison: an eight-bar call-and-response phrase in C. The learner needs an interesting '
                       'right-hand jazz motif, one productive rhythmic stretch, a precise accent pattern, a quiet simple left hand, '
                       'and a bounded application with two concrete choices. Do not shorten the eight-bar melodic objective '
                       'to fit a cached shell-voicing example. Open Studio Jazz Piano for Beginners PDF page 44 may serve '
                       'as a conceptual voice-leading reference, but only reuse a published score if it actually fulfills '
                       'the complete eight-bar phrasing goal. Otherwise write original music. Actual playing accuracy is unknown.')
        manager = rec.Recommendations(root, data)
        print('Starting synthetic comparison: ' + str(args.workflow), flush=True)
        job = manager.start('R-' + '7' * 32, request=request, asynchronous=False)
        artifact = json.loads(manager._path(job['id']).read_text())
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'artifact.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        summary = {'state': job['state'], 'error': job.get('error_code'), 'attempts': len(artifact.get('attempts', [])),
                   'validation_errors': [a.get('validation_error') for a in artifact.get('attempts', []) if a.get('validation_error')],
                   'synthetic_profile': profile, 'request': request, 'policy': rec.POLICY_VERSION}
        if job['state'] == 'completed':
            task = next(t for t in review.records(review.read_events(root)) if t['assignment']['task_id'] == job['task_id'])
            rec.validate_target(task['target'])
            (args.output / 'target.json').write_text(json.dumps(task['target'], ensure_ascii=False, indent=2))
            summary.update(title=task['target']['exercise']['title'], references=artifact['result']['references'])
        (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 0 if job['state'] == 'completed' else 1


if __name__ == '__main__': raise SystemExit(main())
