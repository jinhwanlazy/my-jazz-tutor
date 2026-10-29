"""Versioned task demands, score facts and prospective burden predictions.

The rubric is a provisional comparison scale, not a measured ability model.
Feedback never changes an assigned assessment or supplies note/timing accuracy.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

RUBRIC = json.loads((Path(__file__).with_name('difficulty-rubric.json')).read_text())
AXES = tuple(RUBRIC['axes'])


def score_features(exercise):
    """Facts from assigned notation only; no inferred fingering or played tempo."""
    from notation import pitches
    score = exercise.get('notation')
    facts = {'source': 'assigned_notation', 'metronome_target_bpm': exercise['bpm'],
             'bars': exercise['bars'], 'available': bool(score)}
    if not score:
        return facts
    facts['beats_per_bar'] = score['beats_per_bar']
    hands, starts = {}, {}
    for hand in ('left', 'right'):
        events = [(i * 4 + e['beat'], e) for i, bar in enumerate(score['bars'])
                  for e in bar[hand] if e['notes']]
        notes = [[pitches(n)[0]['midi'] for n in e['notes']] for _, e in events]
        flat = [n for chord in notes for n in chord]
        starts[hand] = {beat for beat, _ in events}
        hands[hand] = {
            'onsets': len(events), 'offbeat_onsets': sum(beat % 1 != 0 for beat, _ in events),
            'shortest_duration_beats': min((e['duration'] for _, e in events), default=None),
            'pitch_range_semitones': max(flat) - min(flat) if flat else None,
            'max_simultaneous_notes': max(map(len, notes), default=0),
            'max_chord_span_semitones': max((max(chord) - min(chord) for chord in notes), default=0),
            'max_top_note_step_semitones': max((abs(max(b) - max(a)) for a, b in zip(notes, notes[1:])), default=0),
            'pitch_classes': sorted({n % 12 for n in flat}),
            'onsets_per_second_at_target': round(len(events) * exercise['bpm'] / (60 * 4 * len(score['bars'])), 3),
            'rhythm_patterns': len({tuple((e['beat'], e['duration'], bool(e['notes'])) for e in bar[hand])
                                    for bar in score['bars']}),
        }
    union = starts['left'] | starts['right']
    facts.update(hands=hands, both_hands_active=bool(starts['left'] and starts['right']),
                 shared_onsets=len(starts['left'] & starts['right']),
                 nonshared_onsets=len(starts['left'] ^ starts['right']), total_onset_positions=len(union))
    return facts


def validate(assessment, context=None):
    if assessment['rubric_version'] != RUBRIC['version']:
        raise ValueError('Unknown difficulty rubric.')
    for axis, rating in assessment['axes'].items():
        anchors = {a['id']: a['level'] for a in RUBRIC['axes'][axis]['anchors']}
        if any(a not in anchors for a in rating['anchor_ids']):
            raise ValueError('Difficulty cites an anchor from another axis or rubric.')
        if rating['status'] == 'rated':
            if rating['level'] is None or rating['level'] not in [anchors[a] for a in rating['anchor_ids']]:
                raise ValueError('A rated axis must cite its corresponding anchor.')
        elif rating['level'] is not None:
            raise ValueError('Unknown, inapplicable or out-of-range axes have no numerical level.')
    if len(set(assessment['focus_axes'])) != len(assessment['focus_axes']):
        raise ValueError('Duplicate difficulty focus axes.')
    prediction = assessment['prediction']
    if context is not None:
        from coaching_context import evidence_ids
        sources = evidence_ids(context)
        if any(ref not in sources for ref in prediction['source_ids']):
            raise ValueError('Burden prediction cites evidence that was not supplied.')
        if prediction['burden'] != 'unknown' and not prediction['source_ids']:
            raise ValueError('A personal prediction requires supplied evidence.')


def result_from_target(target):
    """Recover the model contract without app-derived facts; v1 stays unchanged."""
    result = {'schema_version': target['schema_version'], **copy.deepcopy(target['analysis']),
              'exercise': copy.deepcopy(target['exercise'])}
    if target['schema_version'] == 2:
        result['difficulty'] = {k: copy.deepcopy(v) for k, v in target['difficulty'].items() if k != 'features'}
    return result


def prediction_observation(task):
    """Join an earlier forecast and latest feedback without calling utility a score."""
    report = task.get('report')
    difficulty = task['target'].get('difficulty')
    if not difficulty or not report:
        return None
    label = report['difficulty']
    meaning = {'impossible': 'reported_overload', 'challenging': 'reported_challenge_not_failure',
               'good': 'reported_utility_burden_unknown', 'too_easy': 'reported_underload'}.get(label, 'legacy_report')
    import review as r
    observed = r.reflection_observations(report) or {}
    return {'task_id': task['assignment']['task_id'], 'source_id': 'event:' + report['event_id'],
            'rubric_version': difficulty['rubric_version'],
            'predicted_burden_at_assignment': difficulty['prediction']['burden'],
            'reported_label': label, 'meaning': meaning,
            'assigned_bpm': task['target']['bpm'],
            'metronome_setting_bpm': observed.get('metronome_bpm'),
            'reused_prediction': task['assignment']['reason'].startswith('Explicit repeat of '),
            'rule': 'Compare conditions first. This is not an accuracy or mastery observation.'}
