"""Versioned task demands, score facts and prospective burden predictions.

The rubric is a provisional comparison scale, not a measured ability model.
Feedback never changes an assigned assessment or supplies note/timing accuracy.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

RUBRIC = json.loads((Path(__file__).with_name('difficulty-rubric.json')).read_text())
LEGACY_RUBRIC = json.loads((Path(__file__).with_name('difficulty-rubric.v1.json')).read_text())
RUBRICS = {rubric['version']: rubric for rubric in (LEGACY_RUBRIC, RUBRIC)}
AXES = tuple(RUBRIC['axes'])


def score_features(exercise):
    """Facts from assigned notation only; no inferred fingering or played tempo."""
    from notation import pitches
    score = exercise.get('notation')
    facts = {'source': 'assigned_notation', 'metronome_target_bpm': exercise['bpm'],
             'bars': exercise['bars'], 'available': bool(score)}
    if not score:
        return facts
    if score.get('format') == 'abc':
        return abc_features(exercise, facts)
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


def abc_features(exercise, facts):
    from abc_score import parse_score
    score = parse_score(exercise['notation'], **{k: exercise[k] for k in ('key', 'bpm', 'bars')})
    beats = score['beats_per_bar']
    hands, starts = {}, {}
    for hand in ('left', 'right'):
        events = [e for e in score['events'] if e['hand'] == hand]
        attacks, sounding = {}, []
        for event in events:
            at = event['bar'] * beats + event['beat']
            for note in event['pitches']:
                sounding.append((at, at + event['duration'], note['midi']))
                if not note['tie_from']:
                    attacks.setdefault(at, []).append((note['midi'], event['duration']))
        starts[hand] = set(attacks)
        flat = [p for _, _, p in sounding]
        chords = [[p for p, _ in attacks[at]] for at in sorted(attacks)]
        simultaneous = [{p for start, end, p in sounding if start <= at < end} for at in sorted({s for s, _, _ in sounding})]
        hands[hand] = {
            'onsets': len(attacks), 'offbeat_onsets': sum(at % 1 != 0 for at in attacks),
            'shortest_duration_beats': min((e['duration'] for e in events if e['pitches']), default=None),
            'pitch_range_semitones': max(flat) - min(flat) if flat else None,
            'max_simultaneous_notes': max(map(len, simultaneous), default=0),
            'max_chord_span_semitones': max((max(c) - min(c) for c in simultaneous if c), default=0),
            'max_top_note_step_semitones': max((abs(max(b) - max(a)) for a, b in zip(chords, chords[1:])), default=0),
            'pitch_classes': sorted({p % 12 for p in flat}),
            'onsets_per_second_at_target': round(len(attacks) * exercise['bpm'] / (60 * beats * len(score['bars'])), 3),
            'rhythm_patterns': len({tuple((e['voice'], e['beat'], e['duration'], bool(e['pitches'])) for e in b[hand]) for b in score['bars']}),
            'voices': sum(v['hand'] == hand for v in score['voices']),
            'tie_continuations': sum(bool(n['tie_from']) for e in events for n in e['pitches']),
        }
    return facts | {'beats_per_bar': beats, 'hands': hands,
        'both_hands_active': bool(starts['left'] and starts['right']),
        'shared_onsets': len(starts['left'] & starts['right']),
        'nonshared_onsets': len(starts['left'] ^ starts['right']),
        'total_onset_positions': len(starts['left'] | starts['right']),
        'written_expression': sorted({d for e in score['events'] for d in e['decorations']} |
                                     ({'slur'} if any(e['slur_starts'] for e in score['events']) else set()))}


def validate(assessment, context=None):
    rubric = RUBRICS.get(assessment['rubric_version'])
    if rubric is None:
        raise ValueError('Unknown difficulty rubric.')
    if context is not None and context.get('difficulty_rubric', {}).get('version', rubric['version']) != rubric['version']:
        raise ValueError('New assessments must use the supplied difficulty rubric.')
    for axis, rating in assessment['axes'].items():
        anchors = {a['id']: a['level'] for a in rubric['axes'][axis]['anchors']}
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


def task_characteristics(score):
    """Read-only presentation of saved conditions, shared by old and new tasks.

    Display notation already distinguishes written notes from improvisation and
    illustrative short attacks. Neither becomes evidence of actual performance.
    """
    tags = []
    if score is None:
        return {'source': 'assigned_conditions', 'tags': [], 'notation_available': False}
    bars = score['bars']
    events = {hand: [event for bar in bars for event in bar[hand]] for hand in ('left', 'right')}
    def attack(event):
        return event['kind'] != 'rest' and (score.get('format') != 'abc' or any(not n['tie_from'] for n in event['pitches']))
    active = {hand: any(e['kind'] != 'rest' for e in part) for hand, part in events.items()}
    improvised = any(e['kind'] == 'improv' for part in events.values() for e in part)
    # Descriptive facts are not inferred from rubric numbers or axis reasons.
    if any(attack(e) and e['beat'] % 1 != 0 for part in events.values() for e in part):
        tags.append('Offbeat entries')
    if any(active[hand] and any(e['kind'] == 'rest' for e in part) for hand, part in events.items()):
        tags.append('Rests in the written parts')
    if active['left'] and len(bars) > 1:
        patterns = {tuple((e['beat'], e['duration'], e['kind']) for e in bar['left']) for bar in bars}
        if len(patterns) == 1 and not any(e['kind'] == 'improv' for e in events['left']):
            tags.append('Repeating left-hand rhythm')
    if improvised:
        tags.append('Improvisation with specified pitches')
    if any(e['kind'] == 'notes' and len(e['pitches']) > 1 for part in events.values() for e in part):
        tags.append('Notes played together')
    if active['left'] and active['right']:
        if improvised:
            tags.append('Both hands have assigned roles')
        else:
            starts = {hand: {(i, e['beat']) for i, bar in enumerate(bars)
                             for e in bar[hand] if attack(e)} for hand in events}
            tags.append('Different entries between hands' if starts['left'] != starts['right']
                        else 'Hands enter together')
    elif active['left']:
        tags.append('Left hand only')
    elif active['right']:
        tags.append('Right hand only')
    if score.get('format') == 'abc':
        if any(n['tie_from'] for e in score['events'] for n in e['pitches']): tags.append('Tied notes')
        if any(e['triplet'] for e in score['events']): tags.append('Triplet rhythm')
        if len(score['voices']) > 2: tags.append('Independent voices')
        if any(e['decorations'] or e['slur_starts'] for e in score['events']): tags.append('Written expression')
    return {'source': 'assigned_notation', 'tags': tags, 'notation_available': True}


def result_from_target(target):
    """Recover the model contract without app-derived facts; v1 stays unchanged."""
    result = {'schema_version': target['schema_version'], **copy.deepcopy(target['analysis']),
              'exercise': copy.deepcopy(target['exercise'])}
    if target['schema_version'] >= 2:
        result['difficulty'] = {k: copy.deepcopy(v) for k, v in target['difficulty'].items() if k != 'features'}
    if target['schema_version'] == 3:
        result.update(music_claims=copy.deepcopy(target['music_claims']), references=copy.deepcopy(target['references']))
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
