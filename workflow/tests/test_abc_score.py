"""Synthetic music with independently specified expected events."""
import copy
import unittest

from abc_score import parse_score, playback_for, validate_claims


def notation(right='"D"[FA]8 | "G"[GB]8 |', left='D,8 | G,,8 |', meter='4/4', extra=''):
    return {'format': 'abc', 'profile': 'jazz-abc-1', 'abc':
            f'X:1\nT:Synthetic notation\nM:{meter}\nL:1/8\n%%score {{ RH LH }}\n'
            f'V:RH clef=treble\nV:LH clef=bass\n{extra}K:D\n[V:RH] {right}\n[V:LH] {left}\n'}


class ABCScoreTests(unittest.TestCase):
    def test_key_spelling_pitches_and_full_bar_events(self):
        source = notation()
        original = copy.deepcopy(source)
        score = parse_score(source, key='D', bpm=72, bars=2)
        self.assertEqual(source, original)
        self.assertEqual(score['bars'][0]['right'][0]['notes'], ['F#4', 'A4'])
        self.assertEqual([p['midi'] for p in score['bars'][1]['left'][0]['pitches']], [43])
        self.assertEqual(score['bars'][0]['right'][0]['duration_fraction'], [4, 1])
        score['bars'][0]['right'][0]['notes'].clear()
        self.assertEqual(parse_score(source)['bars'][0]['right'][0]['notes'], ['F#4', 'A4'])

    def test_triplets_cross_bar_ties_and_explicit_expression(self):
        score = parse_score(notation('!mf!F4 !accent!E4- | E2 (3FGA z4 |', '!p!D,8 | G,,8 |'))
        right = score['bars'][1]['right']
        self.assertEqual([e['duration_fraction'] for e in right], [[1, 1], [1, 3], [1, 3], [1, 3], [2, 1]])
        self.assertEqual(right[0]['pitches'][0]['tie_from'], 'RH:0:1')
        self.assertEqual(score['bars'][0]['right'][1]['pitches'][0]['tie_to'], 'RH:1:0')
        self.assertEqual(score['bars'][0]['right'][1]['decorations'], ['accent'])
        played = playback_for(notation('F4 E4- | E2 (3FGA z4 |'))['events']
        self.assertEqual([(e['start'], e['duration']) for e in played if e['pitch'] == 64], [(2, 3)])

    def test_accidentals_reset_but_tied_accidentals_cross_bar(self):
        score = parse_score(notation('=F4 ^G4- | G4 F4 |'))
        self.assertEqual(score['bars'][0]['right'][0]['notes'], ['F4'])
        self.assertEqual(score['bars'][1]['right'][0]['notes'], ['G#4'])
        self.assertEqual(score['bars'][1]['right'][1]['notes'], ['F#4'])

    def test_three_four_and_dotted_sixteenths(self):
        score = parse_score(notation('F3/2 G/2 A2 z2 |', 'D,6 |', '3/4'))
        self.assertEqual(score['beats_per_bar'], 3)
        self.assertEqual([e['duration_fraction'] for e in score['bars'][0]['right']], [[3, 4], [1, 4], [1, 1], [1, 1]])

    def test_two_independent_voices_on_one_hand(self):
        n = notation()
        n['abc'] = n['abc'].replace('{ RH LH }', '{ (RH RH2) LH }').replace('V:LH clef=bass', 'V:RH2 clef=treble\nV:LH clef=bass')
        n['abc'] += '[V:RH2] z4 D4 | z8 |\n'
        score = parse_score(n)
        self.assertEqual([v['id'] for v in score['voices']], ['RH', 'RH2', 'LH'])
        self.assertEqual([(e['voice'], e['beat']) for e in score['bars'][0]['right']], [('RH', 0), ('RH2', 0), ('RH2', 2)])

    def test_slurs_have_matching_boundaries_in_the_same_voice(self):
        score = parse_score(notation('(F4 G4 | A8) |'))
        self.assertEqual(score['bars'][0]['right'][0]['slur_starts'], [101])
        self.assertEqual(score['bars'][1]['right'][0]['slur_ends'], [101])
        for right in ('(F8 | G8 |', 'F8) | G8 |'):
            with self.subTest(right=right), self.assertRaisesRegex(ValueError, 'slur'):
                parse_score(notation(right))

    def test_engraved_chord_accidentals_keep_the_spelled_root_for_claims(self):
        for chord, note, pitch in [('Bbmaj7', '=D', 'D4'), ('F#7', '^A', 'A#4'), ('C##7', '^^E', 'E##4')]:
            score = parse_score(notation(f'"{chord}"{note}8 | G8 |'))
            self.assertEqual(score['bars'][0]['chord'], chord)
            claim = {'bar': 1, 'beat': 0, 'voice': 'RH', 'pitch': pitch, 'chord': chord, 'degree': 3, 'alteration': 0}
            validate_claims([claim], score)
            with self.assertRaisesRegex(ValueError, 'third and fifth'):
                validate_claims([claim | {'degree': 5}], score)

    def test_eight_and_twelve_bar_forms(self):
        for count in (8, 12):
            score = parse_score(notation('F8 | ' * count, 'D,8 | ' * count), bars=count)
            self.assertEqual(len(score['bars']), count)
            self.assertEqual(len(score['events']), count * 2)

    def test_reject_incomplete_overflow_mismatched_and_dangling_ties(self):
        for right in ('F4 | G8 |', 'F8 F2 | G8 |', 'F8- | G8 |', 'F8 | G8- |', 'F8- | z8 |'):
            with self.subTest(right=right), self.assertRaises(ValueError):
                parse_score(notation(right))

    def test_reject_unsupported_input_instead_of_silent_loss(self):
        for right in ('|: F8 | G8 :|', '{F}G8 | A8 |', 'F8 | [M:3/4]G6 |', 'F8 | (5GABcd z3 |', '!trill!F8 | G8 |', '!style=x!F8 | G8 |', '"^text"F8 | G8 |'):
            with self.subTest(right=right), self.assertRaises(ValueError):
                parse_score(notation(right))
        for extra in ('%%MIDI gchord fzcz\n', '%%beginsvg\n', 'Q:1/8=72\n'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_score(notation(extra=extra))
        for conditions in ({'key': 'C'}, {'bars': 4}, {'bpm': 90}):
            with self.subTest(conditions=conditions), self.assertRaises(ValueError):
                parse_score(notation(extra='Q:1/4=72\n'), **conditions)


if __name__ == '__main__':
    unittest.main()
