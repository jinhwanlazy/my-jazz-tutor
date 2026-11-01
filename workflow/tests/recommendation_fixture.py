"""Synthetic musical material and fake provider, never a production fallback."""
import copy


def result():
    whole = lambda notes: [{'beat': 0, 'duration': 4, 'notes': notes}]
    from difficulty import AXES, RUBRIC
    return {'schema_version': 2,
            'difficulty': {'rubric_version': RUBRIC['version'],
                'axes': {axis: {'status': 'rated', 'level': 1, 'anchor_ids': [axis + '-1'],
                               'reason': 'Compare the synthetic task with the first reference at the assigned tempo.'} for axis in AXES},
                'focus_axes': ['harmony', 'coordination'],
                'interaction': 'Both hands attack together while chord shapes change.',
                'prediction': {'burden': 'unknown', 'source_ids': ['profile'],
                               'reason': 'There is not enough comparable performance feedback.',
                               'uncertainty': 'This synthetic fixture has no verified performance evidence.'}},
            'evidence': [{'source_ids': ['profile'], 'interpretation': 'A synthetic player requested chord connection practice.', 'confidence': 'low'}],
            'unknowns': ['Actual note and timing accuracy has not been analyzed.'],
            'exercise': {'title': 'D major voice leading', 'objective': 'Connect two chords with a small right-hand movement.',
                         'selection_reason': 'Try a short, specific voice-leading exercise based on the supplied preferences.',
                         'section': 'Original two-bar loop', 'key': 'D', 'bpm': 72, 'bars': 2, 'minutes': 5,
                         'left_hand': 'Hold D3 for bar 1 and G2 for bar 2.',
                         'right_hand': 'Hold F#4+A4 for bar 1 and G4+B4 for bar 2.',
                         'notes': 'Bar 1: LH D3, RH F#4+A4; bar 2: LH G2, RH G4+B4.',
                         'rhythm': 'Whole notes, one chord on beat 1 per bar in 4/4.',
                         'instructions': 'Play each chord for four beats and connect the two bars. Listen to the upper voices.',
                         'steps': ['Play each hand separately for one minute.', 'Join both hands at 72 BPM for three minutes.'],
                         'notation': {'beats_per_bar': 4, 'bars': [
                             {'chord': 'D', 'left': whole(['D3']), 'right': whole(['F#4', 'A4'])},
                             {'chord': 'G', 'left': whole(['G2']), 'right': whole(['G4', 'B4'])}]},
                         'notation_reason': 'The score specifies the exact two chord shapes.',
                         'accompaniment': {'beats_per_bar': 4, 'bars': [
                             {'chord': 'D', 'notes': [50, 54, 57]}, {'chord': 'G', 'notes': [43, 47, 50]}]}}}


class SyntheticRunner:
    def plan(self, context, **kwargs):
        return plan(), {'provider': 'synthetic-test'}

    def generate(self, context, **kwargs):
        return abc_result(), {'provider': 'synthetic-test'}


def plan():
    return {'objective': 'Connect chord shapes in a musical phrase.', 'evidence_ids': ['profile'],
            'stretch': 'Keep the bass quiet while connecting upper voices.', 'form': 'A short original phrase.',
            'material_reason': 'This synthetic transport test needs no external material.', 'material_requests': [],
            'example_requirements': {'key': None, 'bars': None, 'focus': ['voice leading']}}


class SyntheticTranslator:
    def __init__(self):
        self.calls = 0

    def translate(self, context, schema):
        self.calls += 1
        prefix = '번역: ' if context['target_language'] == 'Korean' else 'Translated: '
        return {'strings': {key: prefix + text for key, text in context['strings'].items()}}, {'provider': 'synthetic-test'}


def abc_result(bars=2, meter=4):
    value = result()
    value.update(schema_version=3, references=[], music_claims=[
        {'bar': 1, 'beat': 0, 'voice': 'RH', 'pitch': 'F#4', 'chord': 'D', 'degree': 3, 'alteration': 0}])
    e = value['exercise']
    e['bars'] = bars
    e['section'] = f'Original {bars}-bar phrase'
    e['rhythm'] = f'Hold each chord for {meter} quarter-note beats in {meter}/4.'
    e['instructions'] = f'Connect the chords in {meter}/4. Keep the melody louder than the bass.'
    e['development'] = {'focus': 'Connect chord tones with a quiet bass.', 'musical_structure': 'Alternate D and G in a balanced phrase.',
                        'expression': 'Keep the right hand mf and the bass p.', 'application': 'Repeat with a different final chord tone.',
                        'difference_from_recent': 'No comparable synthetic history was supplied.'}
    def abc(right):
        rh = ' '.join(('"D"!mf!' + right[0] if i % 2 == 0 else '"G"' + right[1]) + str(meter*2) + ' |' for i in range(bars))
        lh = ' '.join(('D,' if i % 2 == 0 else 'G,,') + str(meter*2) + ' |' for i in range(bars))
        return {'format':'abc','profile':'jazz-abc-1','abc':f'X:1\nT:Synthetic chord connection\nM:{meter}/4\nL:1/8\n%%score {{ RH LH }}\nV:RH clef=treble\nV:LH clef=bass\nK:D\n[V:RH] {rh}\n[V:LH] !p!{lh}\n'}
    e['notation'] = abc(('[FA]', '[GB]'))
    e['accompaniment'] = abc(('[F,A,]', '[B,,D]'))
    return value
