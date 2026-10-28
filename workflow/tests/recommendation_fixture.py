"""Synthetic musical material and fake provider, never a production fallback."""
import copy


def result():
    whole = lambda notes: [{'beat': 0, 'duration': 4, 'notes': notes}]
    return {'schema_version': 1,
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
    def generate(self, context):
        return copy.deepcopy(result()), {'provider': 'synthetic-test'}
