"""Opt-in real Codex exercise generation with synthetic evidence only.

Artifacts go to ignored build/. Never accepts a production practice root.
Use --cache-seed only for a public-material test cache, never a practice directory.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recommendation as rec
import review
from recommendation_fixture import abc_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--scenario', choices=['phrasing', 'blues', 'reuse'], default='phrasing')
    parser.add_argument('--repeat', type=int, choices=[1, 2, 3], default=1)
    parser.add_argument('--cache-seed', type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'build' / 'coaching-smoke' / args.scenario
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for repeat in range(args.repeat):
        with tempfile.TemporaryDirectory(prefix='jazz-synthetic-coaching-') as directory:
            root = Path(directory)
            cache = root / 'materials'
            if args.cache_seed:
                if (args.cache_seed / 'practice.csv').exists() or (args.cache_seed / 'profile.json').exists():
                    raise ValueError('A practice directory must never be used as a source test cache.')
                shutil.copytree(args.cache_seed, cache)
            os.environ['JAZZ_MATERIALS_CACHE'] = str(cache)
            (root / 'profile.json').write_text(json.dumps({'language': 'en', 'timezone': 'UTC', 'daily_minutes': 20,
                'piano_experience': 'Synthetic player can read both staves and play triads.',
                'jazz_experience': 'Synthetic player has practiced root-plus-shell voicings.',
                'goal': 'Use jazz vocabulary in expressive phrases.'}))
            data = review.curriculum()
            if args.scenario in ('phrasing', 'blues'):
                for index in range(2):
                    value = abc_result(4)
                    value['exercise']['title'] = f'Synthetic earlier sustained chords {index + 1}'
                    target = rec.make_target(value, data, {'provider': 'synthetic-history'})
                    tid = 'T-' + str(index) * 10
                    assigned = review.new_event('assigned', tid, data, target['exercise_id'])
                    assigned.update(recorded_at=f'2026-01-0{index + 1}T10:00:00+00:00', target_json=review.jdump(target))
                    reported = review.new_event('reported', tid, data, target['exercise_id'])
                    reported.update(recorded_at=f'2026-01-0{index + 1}T10:10:00+00:00', practice_date=f'2026-01-0{index + 1}',
                                    actual_json='{}', checks_json='{}', difficulty='challenging' if args.scenario == 'blues' else 'too_easy',
                                    raw_note=('Synthetic feedback: coordinating both hands is still challenging. I would like a recognizable blues form while keeping the bass simple; timing is not verified.' if args.scenario == 'blues' else
                                              'Synthetic feedback: sustained chords felt repetitive. I want a melodic phrase and clear accents; no claim about verified timing.'))
                    for event in (assigned, reported): review.append_event(root, event)
                request = ('Synthetic scenario: a complete 12-bar blues in F, with a sparse single-note left-hand root on each first beat, a recognizable right-hand motif, specific accents and one bounded application. Keep coordination manageable while developing form; do not claim accuracy from the feedback. Use an original melody; no external source is needed for this transport test.' if args.scenario == 'blues' else
                           'Synthetic scenario: an 8-bar call-and-response phrase in C with a clear accent, a new melodic demand and one bounded application. Consider Open Studio Jazz Piano for Beginners PDF page 44 as an optional teaching reference.')
            else:
                request = 'Synthetic source-reuse scenario: practice the exact reviewed one-bar C major Dm7–G7–Cmaj7 shell example from Open Studio Jazz Piano for Beginners PDF page 44. Select the supplied verified example unchanged, if available. The goal is smooth 3rd/7th voice leading with roots; one bar is appropriate here.'
            manager = rec.Recommendations(root, data)
            print(f'Starting {args.scenario} sample {repeat + 1}: Sol/high, synthetic context', flush=True)
            job = manager.start('R-' + {'phrasing':'4', 'reuse':'5', 'blues':'6'}[args.scenario] * 31 + str(repeat),
                                request=request, asynchronous=False)
            artifact = json.loads(manager._path(job['id']).read_text())
            destination = output / f'sample-{repeat + 1}'
            destination.mkdir(exist_ok=True)
            (destination / 'artifact.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
            for index, image in enumerate(artifact['context'].get('preparation', {}).get('images', []), 1):
                if Path(image).is_file(): shutil.copyfile(image, destination / f'source-page-{index}.png')
            if job['state'] == 'completed':
                task = next(t for t in review.records(review.read_events(root)) if t['assignment']['task_id'] == job['task_id'])
                rec.validate_target(task['target'])
                (destination / 'target.json').write_text(json.dumps(task['target'], ensure_ascii=False, indent=2))
                if args.scenario == 'reuse':
                    references = artifact['result']['references']
                    exact = [r for r in references if r['mode'] == 'source_original']
                    assert len(exact) == 1, 'The source-reuse test must select one reviewed asset.'
                    examples = [e for p in artifact['context']['preparation']['materials'] for e in p['verified_examples']]
                    example = next(e for e in examples if e['id'] == exact[0]['example_id'])
                    assert task['target']['exercise']['notation'] == example['notation']
            result = {'state': job['state'], 'error': job.get('error_code'), 'attempts': len(artifact.get('attempts', [])),
                      'validation_errors': [a.get('validation_error') for a in artifact.get('attempts', []) if a.get('validation_error')],
                      'title': artifact.get('result', {}).get('exercise', {}).get('title'),
                      'bars': artifact.get('result', {}).get('exercise', {}).get('bars')}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    (output / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r['state'] == 'completed' for r in results) else 1


if __name__ == '__main__': raise SystemExit(main())
