"""Synthetic import/review/retrieval boundaries; never uses private practice data."""
import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from abc_score import parse_score
import coaching_materials as cm
import materials as m
import musicxml_import as mx
import score_extract as sx
from recommendation_fixture import abc_result, plan


ATTR = '<attributes><divisions>6</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>'


def note(step='C', octave=4, beats=4, staff=1, voice=None, extra='', written='whole', chord=False, alter=0):
    return f'<note>{"<chord/>" if chord else ""}<pitch><step>{step}</step><alter>{alter}</alter><octave>{octave}</octave></pitch><duration>{beats * 6}</duration><voice>{voice or staff}</voice><type>{written}</type><staff>{staff}</staff>{extra}</note>'


def score(right=None, left=None, attributes=ATTR, extra=''):
    return ('<score-partwise version="4.0"><part-list/><part id="P1"><measure number="7"><print/>' + attributes + extra +
            (right or note()) + '<backup><duration>24</duration></backup>' + (left or note(octave=3, staff=2)) + '</measure></part></score-partwise>').encode()


class ImportTests(unittest.TestCase):
    def test_accidentals_follow_bar_state_without_marking_every_natural(self):
        plain = mx.convert(score())['notation']
        self.assertIn('[V:RH] C4 |', plain['abc'])
        right = ''.join(note('F', alter=a, beats=1, written='quarter') for a in (1, 1, 0, 0))
        notation = mx.convert(score(right))['notation']
        self.assertIn('[V:RH] ^F F =F F |', notation['abc'])
        self.assertEqual([e['notes'] for e in parse_score(notation)['events'] if e['voice'] == 'RH'],
                         [['F#4'], ['F#4'], ['F4'], ['F4']])

    def test_signature_and_bar_reset_preserve_pitch_without_repeated_signs(self):
        from xml.etree import ElementTree as ET
        for fifths, step, altered in ((1, 'F', 1), (-2, 'B', -1)):
            with self.subTest(fifths=fifths):
                attributes = ATTR.replace('<fifths>0</fifths>', f'<fifths>{fifths}</fifths>')
                right = note(step, alter=altered, beats=2, written='half') + note(step, beats=2, written='half')
                root = ET.fromstring(score(right, attributes=attributes))
                second = ET.fromstring(score(note(step, alter=altered))).find('part/measure')
                second.remove(second.find('attributes'))
                root.find('part').append(second)
                notation = mx.convert(ET.tostring(root))['notation']
                self.assertIn(f'[V:RH] {step}2 ={step}2 | {step}4 |', notation['abc'])
                expected = step + ('#' if altered > 0 else 'b') + '4'
                self.assertEqual([e['notes'] for e in parse_score(notation)['events'] if e['voice'] == 'RH'],
                                 [[expected], [step + '4'], [expected]])

    def test_printed_cautionary_signs_are_retained_and_conflicts_rejected(self):
        notation = mx.convert(score(note(extra='<accidental cautionary="yes">natural</accidental>')))['notation']
        self.assertIn('[V:RH] =C4 |', notation['abc'])
        right = ''.join(note('F', alter=1, beats=2, written='half', extra='<accidental>sharp</accidental>') for _ in range(2))
        self.assertIn('[V:RH] ^F2 ^F2 |', mx.convert(score(right))['notation']['abc'])
        with self.assertRaisesRegex(ValueError, 'disagrees with pitch'):
            mx.convert(score(note(extra='<accidental>sharp</accidental>')))
        with self.assertRaisesRegex(ValueError, 'enclosed/custom'):
            mx.convert(score(note(extra='<accidental parentheses="yes">natural</accidental>')))

    def test_accidentals_do_not_leak_between_octaves_staves_or_voices(self):
        right = ''.join(note('F', octave=o, alter=1, beats=1, written='quarter') for o in (4, 5, 4, 5))
        right += '<backup><duration>24</duration></backup>' + note('F', voice=3)
        notation = mx.convert(score(right, note('F', octave=3, staff=2)))['notation']
        self.assertIn('[V:RH] ^F ^f F f |', notation['abc'])
        self.assertIn('[V:RH2] F4 |', notation['abc'])
        self.assertIn('[V:LH] F,4 |', notation['abc'])
        parsed = parse_score(notation)
        self.assertEqual(next(e['notes'] for e in parsed['events'] if e['voice'] == 'RH2'), ['F4'])

    def test_cross_bar_tie_does_not_set_accidental_for_later_untied_note(self):
        from xml.etree import ElementTree as ET
        right = ''.join(note(s, beats=1, written='quarter') for s in 'CDE')
        right += note('F', alter=1, beats=1, written='quarter', extra='<tie type="start"/>')
        root = ET.fromstring(score(right))
        next_right = note('F', alter=1, beats=1, written='quarter', extra='<tie type="stop"/>')
        next_right += note('F', alter=1, beats=1, written='quarter') + note('F', beats=2, written='half')
        second = ET.fromstring(score(next_right)).find('part/measure')
        second.remove(second.find('attributes'))
        root.find('part').append(second)
        notation = mx.convert(ET.tostring(root))['notation']
        self.assertIn('[V:RH] C D E ^F- | F ^F =F2 |', notation['abc'])
        events = [e for e in parse_score(notation)['events'] if e['voice'] == 'RH']
        self.assertEqual(events[3]['pitches'][0]['tie_to'], events[4]['id'])
        self.assertEqual([e['notes'] for e in events[4:]], [['F#4'], ['F#4'], ['F4']])

    def test_mxl_preserves_spelling_chords_dotted_durations_and_articulation(self):
        right = note('E', alter=-1, beats=3, written='half', extra='<dot/><notations><articulations><accent/></articulations></notations>')
        right += note('B', alter=-1, beats=3, written='half', extra='<dot/>', chord=True)
        right += note('D', beats=1, written='quarter')
        data = BytesIO()
        with ZipFile(data, 'w') as z:
            z.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>')
            z.writestr('score.xml', score(right))
        value = mx.convert(data.getvalue())
        parsed = parse_score(value['notation'])
        event = next(e for e in parsed['events'] if e['voice'] == 'RH')
        self.assertEqual(event['notes'], ['Eb4', 'Bb4'])
        self.assertEqual(event['duration_fraction'], [3, 1])
        self.assertIn('accent', event['decorations'])
        self.assertEqual(value['source_fidelity'], 'unreviewed')
        self.assertEqual(value['source_measures'], ['7'])

    def test_triplet_and_tie_round_trip(self):
        triplet = '<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>'
        right = ''.join(note(s, beats=1/3, written='eighth', extra=triplet).replace('<duration>2.0</duration>', '<duration>2</duration>') for s in 'CDE')
        right += note('F', beats=1, written='quarter', extra='<tie type="start"/>') + note('F', beats=2, written='half', extra='<tie type="stop"/>')
        value = mx.convert(score(right))
        parsed = parse_score(value['notation'])
        events = [e for e in parsed['events'] if e['voice'] == 'RH']
        self.assertEqual(events[0]['duration_fraction'], [1, 3])
        self.assertEqual(events[-2]['pitches'][0]['tie_to'], events[-1]['id'])

    def test_full_independent_voices_are_retained_but_gaps_not_filled(self):
        right = note(voice=1) + '<backup><duration>24</duration></backup>' + note('E', voice=3)
        parsed = parse_score(mx.convert(score(right))['notation'])
        self.assertEqual([v['id'] for v in parsed['voices']], ['RH', 'RH2', 'LH'])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            mx.convert(score(note(beats=2, written='half') + '<forward><duration>12</duration></forward>'))

    def test_unsupported_semantics_are_not_silently_removed(self):
        for fragment in ('<grace/>', '<notations><slur type="start"/></notations>', '<notations><ornaments><trill-mark/></ornaments></notations>'):
            with self.subTest(fragment=fragment), self.assertRaises(ValueError): mx.convert(score(note(extra=fragment)))
        for fragment in ('<barline><repeat direction="backward"/></barline>', '<direction><direction-type><dynamics><sf/></dynamics></direction-type></direction>'):
            with self.subTest(fragment=fragment), self.assertRaises(ValueError): mx.convert(score(extra=fragment))
        with self.assertRaisesRegex(ValueError, 'durations disagree'): mx.convert(score(note(beats=2)))
        with self.assertRaisesRegex(ValueError, 'tie crosses'): mx.convert(score(note(extra='<tie type="stop"/>')))

    def test_headers_require_inspected_overrides_and_entities_are_rejected(self):
        bare = ATTR.replace('<key><fifths>0</fifths></key>', '').replace('<time><beats>4</beats><beat-type>4</beat-type></time>', '')
        with self.assertRaisesRegex(ValueError, 'missing key/meter'): mx.convert(score(attributes=bare))
        result = mx.convert(score(attributes=bare), missing_key='C', missing_meter='4/4')
        self.assertIn('Missing key supplied explicitly: C', result['normalizations'])
        with self.assertRaisesRegex(ValueError, 'entities'):
            mx.convert(b'<!DOCTYPE x [<!ENTITY x "test">]>' + score())
        with self.assertRaisesRegex(ValueError, '1–16'): mx.convert(score(), first=0)


class ReviewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {'id': 'synthetic-score', 'title': 'Synthetic score', 'author': 'Test', 'publisher': 'Test',
                       'url': 'https://example.test/score.xml', 'format': 'musicxml', 'topics': ['harmony']}
        self.body = score()
        self.store = m.MaterialStore(self.root / 'cache', [self.source], lambda *args: {'status': 200, 'body': self.body})
        manifest = self.store.fetch(self.source['id'])
        self.locator = self.store.extract(manifest)['chunks'][0]['locator']
        self.spec = {'source_id': self.source['id'], 'locator': self.locator, 'selection': {'kind': 'musicxml', 'first': 1, 'last': 1}}

    def review(self, candidate):
        return {'candidate_id': candidate['id'], 'source_sha256': candidate['source_sha256'], 'method': 'symbolic_source_comparison',
                'reviewer': 'Synthetic test only', 'scope': 'Synthetic complete bar', 'notes': 'Compared synthetic input and expected events.',
                'checked': ['pitches', 'durations', 'spelling', 'voices', 'expression'], 'corrections': []}

    def test_unreviewed_candidate_is_not_searchable_and_review_retains_provenance(self):
        value = sx.candidate(self.store, self.spec)
        self.assertFalse(value['issues']); self.assertEqual(value['state'], 'unreviewed')
        self.assertFalse(list((self.store.root / 'examples').glob('*')))
        learning = {'objectives': ['Connect guide tones through a cadence'], 'tags': ['guide tones', 'cadence']}
        asset = sx.register(self.store, value['id'], self.review(value), learning=learning)
        self.assertEqual(asset['review']['extraction']['files']['raw-score'], m.sha(self.body))
        result = self.store.retrieve([{'source_id': self.source['id'], 'query': 'guide tones cadence', 'pages': []}])
        self.assertEqual(result['materials'][0]['verified_examples'][0]['id'], asset['id'])
        self.assertIn(asset['id'], result['materials'][0]['retrieval']['matched_examples'])
        self.assertNotIn('guide tones', result['materials'][0]['text'])  # Found via reviewed-unit metadata.

    def test_failed_conversion_needs_corrections_and_hash_bound_review(self):
        self.body = score(extra='<direction><direction-type><dynamics><sf/></dynamics></direction-type></direction>')
        self.store.fetch(self.source['id'], refresh=True)
        value = sx.candidate(self.store, self.spec)
        self.assertIsNone(value['notation']); self.assertTrue(value['issues'])
        fixed = mx.convert(score())['notation']
        with self.assertRaisesRegex(ValueError, 'corrections'):
            sx.register(self.store, value['id'], self.review(value), notation=fixed)
        record = self.review(value); record['corrections'] = ['Synthetic sf recognition error removed after source comparison.']
        self.assertIn('EX-', sx.register(self.store, value['id'], record, notation=fixed)['id'])
        path = self.store.root / 'candidates' / value['id'] / 'raw-score'; path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity'): sx.register(self.store, value['id'], record, notation=fixed)

    def test_no_hit_does_not_return_first_page_and_old_hashes_are_not_retrieved(self):
        query = [{'source_id': self.source['id'], 'query': 'xyzzynosuchterm', 'pages': []}]
        result = self.store.retrieve(query)
        self.assertEqual(result['materials'], []); self.assertIn('No matching', result['material_failures'][0]['reason'])
        value = sx.candidate(self.store, self.spec)
        sx.register(self.store, value['id'], self.review(value), learning={'objectives': ['Synthetic cadence'], 'tags': ['xyzzynosuchterm']})
        self.assertTrue(self.store.retrieve(query)['materials'])
        self.body += b'\n'; self.store.fetch(self.source['id'], refresh=True)
        self.assertEqual(self.store.retrieve(query)['materials'], [])

    def test_wrong_bar_goal_cannot_reuse_a_reviewed_example(self):
        value = sx.candidate(self.store, self.spec)
        asset = sx.register(self.store, value['id'], self.review(value), learning={'objectives': ['cadence'], 'tags': ['cadence']})
        fetched = self.store.retrieve([{'source_id': self.source['id'], 'query': 'cadence', 'pages': []}], requirements={'key': 'C', 'bars': 8, 'focus': ['melodic phrase']})
        packet = fetched['materials'][0]
        self.assertEqual(packet['example_fit'][asset['id']]['mismatches'], ['bars'])
        result = abc_result(); result['exercise']['notation'] = None
        result['references'] = [{'source_id': self.source['id'], 'excerpt_id': packet['excerpt_id'], 'example_id': asset['id'],
                                 'role': 'exercise_source', 'mode': 'source_original', 'source_excerpt': None, 'changes': []}]
        with self.assertRaisesRegex(ValueError, 'planned key/bar'):
            cm.hydrate_result(result, {'preparation': fetched})

    def test_crop_validation_and_missing_optional_tools(self):
        for crop in ([0, 0, 2, 1], [0, float('nan'), 1, 1], [0, 0, 0, 1]):
            with self.assertRaises(m.MaterialError): sx.checked_crop(crop)
        from PIL import Image
        image = Image.new('RGB', (500, 400), 'white'); pdf = self.root / 'test.pdf'; image.save(pdf); image.close()
        self.body = pdf.read_bytes(); self.source['format'] = 'pdf'
        store = m.MaterialStore(self.root / 'pdf', [self.source], lambda *args: {'status': 200, 'body': self.body})
        spec = {'source_id': self.source['id'], 'locator': {'kind': 'pdf_page', 'page': 1, 'label': 'PDF page 1'},
                'selection': {'kind': 'pdf', 'page': 1, 'crop': [0, 0, 1, 1]}}
        with patch.dict('os.environ', {'JAZZ_AUDIVERIS_BIN': ''}), patch.object(sx.shutil, 'which', return_value=None):
            value = sx.candidate(store, spec)
        self.assertIn('source.png', value['files']); self.assertIsNone(value['notation'])
        self.assertIn('not installed', value['issues'][0])


if __name__ == '__main__': unittest.main()
