"""Synthetic notation for timing/engraving checks; no personal records."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from abc_score import parse_score


def scores():
    header = ('X:1\nM:4/4\nL:1/8\n%%score { RH LH }\n'
              'V:RH clef=treble\nV:LH clef=bass\nK:C\n')
    phrases = {
        'mixed_durations': (
            'C2 D E z F G2 | A2 B2 c4 | C D E F G A B c | C8 |',
            'C,8 | F,,8 | G,,8 | C,8 |'),
        'accidentals_and_sixteenths': (
            'C8 | ^C/ D/ _E/ =E/ ^F/ G/ _A/ =A/ _B/ =B/ c/ ^c/ d/ _e/ =e/ f/ | C8 | C2 z C z3 G |',
            'C,8 | C,8 | G,,8 | C,8 |'),
        'triplets_and_rests': (
            '(3CDE F2 G2 A2 | z2 (3EFG A2 B2 | C8 | z2 C D E4 |',
            'C,8 | F,,8 | G,,8 | C,8 |'),
        'partial_last_line': ('C8 | ' * 5, 'C,8 | ' * 5),
        'ties_across_lines': ('C8 | C8 | C8 | C8- | C4 D4 | E8 | F8 | G8 |', 'C,8 | ' * 8),
        'silent_hand': ('C2 z C E4 | ' * 4, 'z8 | ' * 4),
        'three_four': ('C3 D E F | z2 G2 C2 | ' * 6, 'C,6 | ' * 12),
        'expression_and_slur': (
            '"C7"!mf!(C2 D E !accent!F2 G2 | C8 | C8 | C8 | D4 E4) | F8 | G8 | C8 |',
            '!p!C,8 | ' * 8),
        'key_signature_and_chords': (
            '"Bb7"[=B^CD]2 z !accent![_BDF] z4 | ' * 4,
            'B,,8 | ' * 4),
    }
    values = {}
    for name, (right, left) in phrases.items():
        source = header.replace('M:4/4', 'M:3/4') if name == 'three_four' else header
        if name == 'key_signature_and_chords':
            source = source.replace('K:C', 'K:Bb')
        values[name] = {'format': 'abc', 'profile': 'jazz-abc-1',
                        'abc': source + '[V:RH] ' + right + '\n[V:LH] ' + left + '\n'}
    poly = header.replace('{ RH LH }', '{ (RH RH2) (LH LH2) }').replace(
        'V:LH clef=bass', 'V:RH2 clef=treble\nV:LH clef=bass\nV:LH2 clef=bass')
    values['independent_voices'] = {'format': 'abc', 'profile': 'jazz-abc-1', 'abc': poly +
        '[V:RH] ' + ('E2 z E G4 | ' * 8) + '\n[V:RH2] ' + ('z4 C4 | ' * 8) +
        '\n[V:LH] ' + ('C,8 | ' * 8) + '\n[V:LH2] ' + ('G,,4 z4 | ' * 8) + '\n'}
    return {name: parse_score(value) for name, value in values.items()}


if __name__ == '__main__':
    print(json.dumps(scores()))
